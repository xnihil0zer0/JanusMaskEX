"""E2 integration tests for tools/webui_auth.py + the dispatcher wiring in
tools/webui_server.py. Owned by E2; E6 may extend append-only."""
from __future__ import annotations
import json
import os
import socket
import stat
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from tools import webui_server as srv
from tools import webui_auth


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def state_dir(tmp_path):
    sd = tmp_path / "state"
    sd.mkdir()
    return sd


@pytest.fixture
def sidecar(tmp_path):
    state_dir = tmp_path / "state"
    logs_dir = tmp_path / "logs"
    state_dir.mkdir()
    logs_dir.mkdir()
    port = _free_port()
    tailer = srv.build_tailer(state_dir, logs_dir, srv.DEFAULT_BUFFER_LINES)
    tailer.start()
    server = srv.WebUIServer(
        ("127.0.0.1", port), srv.WebUIHandler,
        state_dir=state_dir, logs_dir=logs_dir, tailer=tailer,
    )
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True,
    )
    thread.start()
    deadline = time.time() + 2.0
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.05)
    yield {
        "url": f"http://127.0.0.1:{port}",
        "port": port,
        "state_dir": state_dir,
        "logs_dir": logs_dir,
        "token": server.operator_token,
        "server": server,
    }
    server.csrf_sweeper_stop.set()
    server.shutdown()
    server.server_close()
    tailer.stop()
    thread.join(timeout=2.0)


def _request(url, path, method="GET", headers=None, timeout=2.0, body=b""):
    req = urllib.request.Request(url + path, method=method, data=body if method != "GET" else None)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), (e.read() if e.fp else b"")


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


def test_token_minted_on_first_start_with_mode_0600(state_dir):
    token = webui_auth.load_or_mint_token(state_dir)
    assert len(token) >= webui_auth.TOKEN_BYTES
    path = state_dir / "control" / "operator_token"
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600, f"expected 0600, got {oct(mode)}"


def test_token_loaded_idempotently_on_subsequent_starts(state_dir):
    a = webui_auth.load_or_mint_token(state_dir)
    b = webui_auth.load_or_mint_token(state_dir)
    assert a == b


def test_check_auth_rejects_missing_token_with_401(sidecar):
    status, _, body = _request(sidecar["url"], "/api/auth/test_echo", method="POST")
    assert status == 401


def test_check_auth_rejects_wrong_token_via_compare_digest(sidecar):
    status, _, _ = _request(
        sidecar["url"], "/api/auth/test_echo", method="POST",
        headers={"X-Operator-Token": "definitely-wrong"},
    )
    assert status == 401


def test_csrf_nonce_minted_and_persisted_to_ledger(sidecar):
    status, _, body = _request(sidecar["url"], "/api/csrf")
    assert status == 200
    payload = json.loads(body)
    assert "nonce" in payload and len(payload["nonce"]) >= 16
    ledger = sidecar["state_dir"] / "control" / "csrf_nonces.jsonl"
    assert ledger.exists()
    rows = [json.loads(l) for l in ledger.read_text().strip().split("\n") if l.strip()]
    assert any(r.get("nonce") == payload["nonce"] and "issued_ts" in r for r in rows)


def test_csrf_replay_returns_403(sidecar):
    token = sidecar["token"].decode()
    status, _, body = _request(sidecar["url"], "/api/csrf")
    nonce = json.loads(body)["nonce"]
    headers = {"X-Operator-Token": token, "X-CSRF-Nonce": nonce}
    s1, _, _ = _request(sidecar["url"], "/api/auth/test_echo", method="POST", headers=headers)
    assert s1 == 200
    s2, _, _ = _request(sidecar["url"], "/api/auth/test_echo", method="POST", headers=headers)
    assert s2 == 403


def test_csrf_expired_nonce_returns_403_after_5min(sidecar):
    ledger = sidecar["state_dir"] / "control" / "csrf_nonces.jsonl"
    expired = "expired-test-nonce-xxxxxxxxxxxxxxxx"
    with open(ledger, "a") as f:
        f.write(json.dumps({"nonce": expired, "issued_ts": time.time() - 600}) + "\n")
    token = sidecar["token"].decode()
    headers = {"X-Operator-Token": token, "X-CSRF-Nonce": expired}
    status, _, _ = _request(sidecar["url"], "/api/auth/test_echo", method="POST", headers=headers)
    assert status == 403


def test_sweeper_trims_rows_older_than_1h(sidecar):
    ledger = sidecar["state_dir"] / "control" / "csrf_nonces.jsonl"
    with open(ledger, "a") as f:
        f.write(json.dumps({"nonce": "ancient", "issued_ts": time.time() - 7200}) + "\n")
        f.write(json.dumps({"nonce": "recent", "issued_ts": time.time()}) + "\n")
    webui_auth._sweep_once(sidecar["state_dir"])
    remaining = [json.loads(l) for l in ledger.read_text().strip().split("\n") if l.strip()]
    nonces = [r.get("nonce") for r in remaining]
    assert "ancient" not in nonces
    assert "recent" in nonces


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------


def test_post_endpoint_requires_token_and_nonce_round_trip(sidecar):
    token = sidecar["token"].decode()
    status, _, body = _request(sidecar["url"], "/api/csrf")
    nonce = json.loads(body)["nonce"]
    headers = {"X-Operator-Token": token, "X-CSRF-Nonce": nonce}
    status, _, body = _request(sidecar["url"], "/api/auth/test_echo", method="POST", headers=headers)
    assert status == 200
    payload = json.loads(body)
    assert payload["ok"] is True


def test_get_remains_unauthenticated_by_default(sidecar):
    status, _, _ = _request(sidecar["url"], "/api/health")
    assert status == 200
    status, _, _ = _request(sidecar["url"], "/api/auth/whoami")
    assert status == 200


def test_get_requires_token_when_auth_required_for_reads_flag_present(sidecar):
    flag = sidecar["state_dir"] / "control" / "auth_required_for_reads"
    flag.write_text("on")
    try:
        status, _, _ = _request(sidecar["url"], "/api/health")
        assert status == 401
        token = sidecar["token"].decode()
        status, _, _ = _request(sidecar["url"], "/api/health", headers={"X-Operator-Token": token})
        assert status == 200
    finally:
        flag.unlink()


def test_token_printed_to_stderr_once_on_startup(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    port = _free_port()
    repo_root = Path(__file__).resolve().parent.parent.parent
    proc = subprocess.Popen(
        [sys.executable, "-m", "tools.webui_server",
         "--state-dir", str(state_dir),
         "--logs-dir", str(tmp_path / "logs"),
         "--port", str(port), "--host", "127.0.0.1"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=repo_root,
    )
    try:
        deadline = time.time() + 5.0
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.05)
        time.sleep(0.5)
        proc.terminate()
        try:
            _, stderr = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            _, stderr = proc.communicate()
        text = stderr.decode("utf-8", errors="replace")
        assert text.count("WebUI ready at http://") == 1, text
        assert "?token=" in text
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


from hypothesis import given, strategies as st, settings


@given(payload=st.binary(min_size=0, max_size=1024))
@settings(max_examples=30, deadline=None)
def test_arbitrary_token_file_contents_either_load_or_refuse_to_start(tmp_path_factory, payload):
    sd = tmp_path_factory.mktemp("auth")
    (sd / "control").mkdir(parents=True, exist_ok=True)
    (sd / "control" / "operator_token").write_bytes(payload)
    if len(payload.strip()) >= webui_auth.TOKEN_BYTES:
        token = webui_auth.load_or_mint_token(sd)
        assert token == payload.strip()
    else:
        with pytest.raises(RuntimeError):
            webui_auth.load_or_mint_token(sd)


@given(nonce=st.text(min_size=0, max_size=128))
@settings(max_examples=30, deadline=None)
def test_arbitrary_csrf_nonce_strings_either_consumed_or_rejected_with_structured_error(tmp_path_factory, nonce):
    sd = tmp_path_factory.mktemp("csrf")
    assert webui_auth.check_and_consume_csrf(sd, nonce) is False


# ---------------------------------------------------------------------------
# Regression
# ---------------------------------------------------------------------------


def test_v1_read_only_routes_unaffected_by_middleware(sidecar):
    for path in ("/api/health", "/api/state", "/api/track-record", "/api/planner/current"):
        status, _, _ = _request(sidecar["url"], path)
        assert status in (200, 404, 503), f"{path} -> {status}"
