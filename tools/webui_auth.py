"""tools/webui_auth.py — operator-token + CSRF middleware for the WebUI v2 sidecar.

Single-operator local-only auth model: a 32-byte URL-safe token persisted at
``state/control/operator_token`` (chmod 0600), and single-use CSRF nonces
backed by an append-only ledger at ``state/control/csrf_nonces.jsonl`` with a
5-minute TTL. Every mutating endpoint (POST/PUT/DELETE) must present both a
matching ``X-Operator-Token`` header (compared timing-safely via
``hmac.compare_digest``) and a fresh ``X-CSRF-Nonce``.

Read-only GETs are unauthenticated by default. Setting up
``state/control/auth_required_for_reads`` (any contents) gates GETs too.

Stdlib only. Thread-safe.
"""
from __future__ import annotations

import hmac
import json
import logging
import os
import secrets
import sys
import tempfile
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Optional

logger = logging.getLogger("janusmask.webui.auth")

TOKEN_BYTES = 32
NONCE_TTL_SEC = 300.0
SWEEPER_INTERVAL_SEC = 60.0
SWEEPER_RETENTION_SEC = 3600.0
LRU_CACHE_SIZE = 64
LARGE_LEDGER_BYTES = 10 * 1024 * 1024


def _control_dir(state_dir: Path) -> Path:
    p = Path(state_dir) / "control"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _token_path(state_dir: Path) -> Path:
    return _control_dir(state_dir) / "operator_token"


def _nonces_path(state_dir: Path) -> Path:
    return _control_dir(state_dir) / "csrf_nonces.jsonl"


def _auth_for_reads_flag(state_dir: Path) -> Path:
    return _control_dir(state_dir) / "auth_required_for_reads"


def auth_required_for_reads(state_dir: Path) -> bool:
    return _auth_for_reads_flag(state_dir).exists()


def load_or_mint_token(state_dir: Path) -> bytes:
    """Read the operator token, minting (chmod 0600) if absent.

    Token-file corruption (empty / shorter than 32 chars) raises RuntimeError
    rather than silently re-minting — operators should know if their token
    file was clobbered.
    """
    path = _token_path(state_dir)
    if path.exists():
        raw = path.read_bytes().strip()
        if len(raw) < TOKEN_BYTES:
            raise RuntimeError(
                f"operator token at {path} is corrupt "
                f"(len={len(raw)} < {TOKEN_BYTES}); refusing to silently re-mint. "
                f"Delete the file to re-mint."
            )
        return raw
    token = secrets.token_urlsafe(TOKEN_BYTES).encode("ascii")
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, token)
    finally:
        os.close(fd)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return token


def check_auth(headers: dict, expected_token: bytes) -> bool:
    """Constant-time check of X-Operator-Token against the expected token."""
    presented = headers.get("X-Operator-Token") or headers.get("x-operator-token")
    if not presented:
        return False
    if isinstance(presented, str):
        presented = presented.encode("ascii", errors="replace")
    return hmac.compare_digest(presented, expected_token)


def _append_jsonl(path: Path, row: dict) -> None:
    line = json.dumps(row, separators=(",", ":")) + "\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(line)


def mint_csrf_nonce(state_dir: Path) -> str:
    """Issue a fresh nonce and append {nonce, issued_ts} to the ledger."""
    nonce = secrets.token_urlsafe(32)
    _append_jsonl(_nonces_path(state_dir), {"nonce": nonce, "issued_ts": time.time()})
    path = _nonces_path(state_dir)
    try:
        if path.stat().st_size > LARGE_LEDGER_BYTES:
            logger.warning("csrf nonce ledger >%d bytes; sweeper backlog?", LARGE_LEDGER_BYTES)
    except FileNotFoundError:
        pass
    return nonce


_consumed_cache: "OrderedDict[str, float]" = OrderedDict()
_consumed_cache_lock = threading.Lock()
_consume_lock = threading.Lock()


def _record_consumed(nonce: str) -> None:
    with _consumed_cache_lock:
        _consumed_cache[nonce] = time.time()
        while len(_consumed_cache) > LRU_CACHE_SIZE:
            _consumed_cache.popitem(last=False)


def _is_consumed_in_cache(nonce: str) -> bool:
    with _consumed_cache_lock:
        return nonce in _consumed_cache


def check_and_consume_csrf(state_dir: Path, nonce: str) -> bool:
    """Validate ``nonce`` against the ledger; consume on success.

    Returns True iff the nonce was issued, not yet consumed, and within TTL.
    Race-safe: a process-wide lock serializes the read-then-append, so two
    concurrent consumers see exactly one success.
    """
    if not nonce or not isinstance(nonce, str):
        return False
    if _is_consumed_in_cache(nonce):
        return False
    path = _nonces_path(state_dir)
    if not path.exists():
        return False
    with _consume_lock:
        if _is_consumed_in_cache(nonce):
            return False
        issued_ts: Optional[float] = None
        consumed = False
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if row.get("nonce") != nonce:
                        continue
                    if "consumed_ts" in row:
                        consumed = True
                        break
                    if "issued_ts" in row:
                        issued_ts = row["issued_ts"]
        except OSError:
            return False
        if consumed:
            _record_consumed(nonce)
            return False
        if issued_ts is None:
            return False
        if time.time() - issued_ts > NONCE_TTL_SEC:
            return False
        _append_jsonl(path, {"nonce": nonce, "consumed_ts": time.time()})
        _record_consumed(nonce)
        return True


def _sweep_once(state_dir: Path) -> None:
    path = _nonces_path(state_dir)
    if not path.exists():
        return
    cutoff = time.time() - SWEEPER_RETENTION_SEC
    keep: list[str] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = row.get("issued_ts") or row.get("consumed_ts") or 0
                if ts >= cutoff:
                    keep.append(line)
    except OSError:
        return
    fd, tmp = tempfile.mkstemp(prefix=".csrf_nonces.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for ln in keep:
                f.write(ln + "\n")
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def start_csrf_sweeper(state_dir: Path, stop_event: Optional[threading.Event] = None) -> threading.Thread:
    """Daemon thread that trims the nonce ledger every 60 s."""
    stop_event = stop_event or threading.Event()

    def _run() -> None:
        while not stop_event.wait(SWEEPER_INTERVAL_SEC):
            try:
                _sweep_once(state_dir)
            except Exception:
                logger.exception("csrf sweeper iteration failed; continuing")

    t = threading.Thread(target=_run, daemon=True, name="janusmask-webui-csrf-sweeper")
    t.start()
    return t


def announce_token(state_dir: Path, host: str, port: int, stream=sys.stderr) -> None:
    """Print the ready-URL exactly once to ``stream`` for launcher consumption."""
    token = load_or_mint_token(state_dir).decode("ascii", errors="replace")
    print(f"WebUI ready at http://{host}:{port}/?token={token}", file=stream, flush=True)
