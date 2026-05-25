#!/usr/bin/env python3
"""Outbox-watcher sidecar — Path A of docs/runbooks/claude_hook_regression_repair.md.

Claude Code 2.1.114's `-p` mode silently drops `--settings` hooks/permissions
so PostToolUse never persists the agent's Write to
``state/sessions/<agent>_round<N>_<task>_submission.json``. This sidecar
replays the PostToolUse persist path from the parent process: polls
``state/workdirs/{claude,gemini}/*/outbox/submission.py``, runs the
persist-time AST gate, and writes the canonical JSON the orchestrator's
``poll_for_submission`` expects. Deny rows mirror
``harness.hooks.rpc.submit_code.AstValidationError`` and land on the
per-session ledger so track-record parity with the in-process hook path is
preserved when the CLI ever regains hook loading.
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import pathlib
import re
import signal
import sys
import time
from typing import Any

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from harness._journal import write_jsonl_row  # noqa: E402
from harness.hooks.rpc import submit_code as rpc_submit_code  # noqa: E402
from harness.session_namer import generate_submission_filename  # noqa: E402

logger = logging.getLogger("impl_outbox_watcher")

_SESSION_RE = re.compile(r"^(claude|gemini)-r(\d+)-(.+)-([0-9a-f]{8})$")
_POLL_INTERVAL = 0.5
_shutdown = False


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _install_signal_handlers() -> None:
    def _handle(signum: int, _frame: Any) -> None:
        global _shutdown
        logger.info("received signal %d; shutting down", signum)
        _shutdown = True

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _handle)
        except (ValueError, OSError):
            pass


def _parse_session(session_slug: str) -> tuple[str, int, str, str] | None:
    m = _SESSION_RE.match(session_slug)
    if not m:
        return None
    agent, round_s, task_id, suffix = m.groups()
    try:
        return agent, int(round_s), task_id, suffix
    except ValueError:
        return None


def _submission_key(path: pathlib.Path) -> tuple[int, int, int]:
    st = path.stat()
    return (st.st_dev, st.st_ino, int(st.st_mtime_ns))


def _append_ledger(
    state_dir: pathlib.Path,
    session_id: str,
    agent: str,
    *,
    verb: str,
    outcome: str,
    round_number: int,
    detail: dict[str, Any],
) -> None:
    target = state_dir / "sessions" / f"{agent}_{session_id}.ledger.jsonl"
    row = {
        "ts": _now_iso(),
        "session_id": session_id,
        "agent": agent,
        "round": round_number,
        "phase": "synthesis",
        "hook": "impl_outbox_watcher",
        "tool": "Write",
        "verb": verb,
        "outcome": outcome,
        "counters": {},
        "digest": "",
        "detail": detail,
    }
    write_jsonl_row(target, row)


def _write_submission_json(
    state_dir: pathlib.Path,
    *,
    agent: str,
    round_number: int,
    task_id: str,
    code: str,
) -> pathlib.Path:
    sessions_dir = state_dir / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    filename = generate_submission_filename(agent, round_number, task_id)
    target = sessions_dir / filename
    tmp = target.with_suffix(f".tmp.{os.getpid()}.{int(time.time()*1e6)}")
    payload = {
        "agent_identity": agent,
        "round_number": round_number,
        "task_id": task_id,
        "code": code,
        "ts": _now_iso(),
    }
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    tmp.rename(target)
    return target


def _process_submission(
    state_dir: pathlib.Path, sub_path: pathlib.Path
) -> str:
    session_slug = sub_path.parent.parent.name
    parsed = _parse_session(session_slug)
    if parsed is None:
        logger.warning("skip: unparseable workdir %s", session_slug)
        return "skip"
    agent, round_number, task_id, _suffix = parsed
    try:
        code = sub_path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("read failed for %s: %s", sub_path, exc)
        return "skip"
    if not code.strip():
        return "skip"
    try:
        rpc_submit_code.ensure_valid(code, allow_nondeterminism=False)
    except rpc_submit_code.AstValidationError as exc:
        errors = [v for v in exc.violations if getattr(v, "severity", "") == "error"]
        violation_dicts = [
            {"rule": v.rule, "severity": v.severity, "line": v.line, "message": v.message}
            for v in errors
        ]
        _append_ledger(
            state_dir,
            session_slug,
            agent,
            verb="submit_code",
            outcome="deny",
            round_number=round_number,
            detail={
                "reason": "persist_time_ast_gate",
                "task_id": task_id,
                "error_count": len(errors),
                "violations": violation_dicts,
                "source": "outbox_watcher",
            },
        )
        logger.info("deny %s: %s", session_slug, exc)
        return "deny"
    target = _write_submission_json(
        state_dir,
        agent=agent,
        round_number=round_number,
        task_id=task_id,
        code=code,
    )
    _append_ledger(
        state_dir,
        session_slug,
        agent,
        verb="submit_code",
        outcome="allow",
        round_number=round_number,
        detail={
            "task_id": task_id,
            "submission_path": str(target),
            "source": "outbox_watcher",
            "bytes": len(code.encode("utf-8")),
        },
    )
    logger.info("accept %s -> %s", session_slug, target.name)
    return "accept"


def _scan_once(state_dir: pathlib.Path, seen: dict[pathlib.Path, tuple[int, int, int]]) -> int:
    workdirs_root = state_dir / "workdirs"
    if not workdirs_root.is_dir():
        return 0
    touched = 0
    for agent_dir in workdirs_root.iterdir():
        if not agent_dir.is_dir() or agent_dir.name not in ("claude", "gemini"):
            continue
        for session_dir in agent_dir.iterdir():
            if not session_dir.is_dir():
                continue
            sub_path = session_dir / "outbox" / "submission.py"
            if not sub_path.is_file():
                continue
            try:
                key = _submission_key(sub_path)
            except OSError:
                continue
            if seen.get(sub_path) == key:
                continue
            seen[sub_path] = key
            try:
                _process_submission(state_dir, sub_path)
                touched += 1
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("processing %s failed: %s", sub_path, exc)
    return touched


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="JanusMask outbox-watcher sidecar.")
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--once", action="store_true", help="single poll pass then exit")
    parser.add_argument("--interval", type=float, default=_POLL_INTERVAL)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    state_dir = pathlib.Path(args.state_dir).resolve()
    if not state_dir.exists():
        logger.warning("state-dir %s does not exist; waiting for it to appear", state_dir)

    _install_signal_handlers()
    seen: dict[pathlib.Path, tuple[int, int, int]] = {}
    logger.info("outbox-watcher polling %s (once=%s)", state_dir, args.once)
    if args.once:
        _scan_once(state_dir, seen)
        return 0
    while not _shutdown:
        _scan_once(state_dir, seen)
        time.sleep(args.interval)
    logger.info("outbox-watcher exiting cleanly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
