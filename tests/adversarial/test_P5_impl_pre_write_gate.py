"""scope_revoke semantics in the META pre-write gate.

The gate (scripts/impl_pre_write.py) consults the last 50 ledger rows for
scope_exception rows that whitelist otherwise-out-of-phase paths. A
companion scope_revoke row MUST close a matching earlier exception on a
per-path basis so writes revert to the phase allow-list without waiting
for the 50-row window to age the exception out.

These adversarial tests drive the gate as a subprocess (matching the
existing meta-hook test pattern) against a synthetic ledger under
tmp_path.
"""

from __future__ import annotations

import datetime
import json
import os
import pathlib
import subprocess
import sys


REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"


def _run(stdin_payload: dict, tmp_path: pathlib.Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
    env["JANUSMASK_PROJECT_DIR"] = str(tmp_path)
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "impl_pre_write.py")],
        input=json.dumps(stdin_payload),
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )


def _seed_ledger(tmp_path: pathlib.Path, rows: list[dict]) -> pathlib.Path:
    ledger = tmp_path / "state" / "impl_progress.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(json.dumps(r) for r in rows)
    ledger.write_text(body + ("\n" if body else ""), encoding="utf-8")
    return ledger


def _ts(offset_seconds: int = 0) -> str:
    dt = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        seconds=offset_seconds
    )
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _recent_start(task: str, phase: str, offset_seconds: int = -60) -> dict:
    return {
        "ts": _ts(offset_seconds),
        "phase": phase,
        "task_id": task,
        "event": "start",
        "detail": "",
        "files": [],
        "exit": 0,
    }


def _deny_reason(proc: subprocess.CompletedProcess) -> str:
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    hso = payload.get("hookSpecificOutput") or {}
    assert hso.get("permissionDecision") == "deny", payload
    return hso.get("permissionDecisionReason", "")


def _assert_allow(proc: subprocess.CompletedProcess) -> None:
    assert proc.returncode == 0, proc.stderr
    if proc.stdout.strip():
        payload = json.loads(proc.stdout)
        hso = payload.get("hookSpecificOutput") or {}
        assert hso.get("permissionDecision") != "deny", proc.stdout


# -------------------------------------------------------------------- tests


def test_scope_revoke_closes_matching_exception(tmp_path):
    """scope_exception for foo/bar.py followed by scope_revoke for
    foo/bar.py should cause the gate to deny a Write to foo/bar.py under
    META (foo/bar.py is out of META's allow-list)."""
    rows = [
        _recent_start("META-00-install-hooks", "META", offset_seconds=-120),
        {
            "ts": _ts(-90),
            "phase": "META",
            "task_id": "META-00-install-hooks",
            "event": "scope_exception",
            "detail": "test: open foo/bar.py",
            "paths": ["foo/bar.py"],
            "approved_by": "test",
            "files": [],
            "exit": 0,
        },
        {
            "ts": _ts(-60),
            "phase": "META",
            "task_id": "",
            "event": "scope_revoke",
            "detail": "test: close foo/bar.py",
            "paths": ["foo/bar.py"],
            "approved_by": "test",
            "files": [],
            "exit": 0,
        },
    ]
    _seed_ledger(tmp_path, rows)
    target = tmp_path / "foo" / "bar.py"
    proc = _run(
        {
            "tool_name": "Write",
            "tool_input": {"file_path": str(target), "content": "x = 1\n"},
        },
        tmp_path,
    )
    reason = _deny_reason(proc)
    assert "out of scope" in reason
    assert "foo/bar.py" in reason


def test_scope_revoke_partial_path_list(tmp_path):
    """Exception opens [foo/a.py, foo/b.py]; revoke closes only [foo/a.py].
    foo/a.py should be blocked, foo/b.py should remain writable."""
    rows = [
        _recent_start("META-00-install-hooks", "META", offset_seconds=-120),
        {
            "ts": _ts(-90),
            "phase": "META",
            "task_id": "META-00-install-hooks",
            "event": "scope_exception",
            "detail": "test: open [a, b]",
            "paths": ["foo/a.py", "foo/b.py"],
            "approved_by": "test",
            "files": [],
            "exit": 0,
        },
        {
            "ts": _ts(-60),
            "phase": "META",
            "task_id": "",
            "event": "scope_revoke",
            "detail": "test: close [a] only",
            "paths": ["foo/a.py"],
            "approved_by": "test",
            "files": [],
            "exit": 0,
        },
    ]
    _seed_ledger(tmp_path, rows)

    # a.py must now be denied.
    target_a = tmp_path / "foo" / "a.py"
    proc_a = _run(
        {
            "tool_name": "Write",
            "tool_input": {"file_path": str(target_a), "content": "x = 1\n"},
        },
        tmp_path,
    )
    reason_a = _deny_reason(proc_a)
    assert "foo/a.py" in reason_a

    # b.py must still be allowed (exception still covers it).
    target_b = tmp_path / "foo" / "b.py"
    proc_b = _run(
        {
            "tool_name": "Write",
            "tool_input": {"file_path": str(target_b), "content": "y = 2\n"},
        },
        tmp_path,
    )
    _assert_allow(proc_b)


def test_scope_revoke_before_exception_is_noop(tmp_path):
    """A revoke whose ts is OLDER than the exception (and/or which appears
    earlier in the ledger) must NOT close the exception — the path should
    remain writable."""
    rows = [
        _recent_start("META-00-install-hooks", "META", offset_seconds=-300),
        # Revoke comes FIRST (both by ts and by ledger position).
        {
            "ts": _ts(-240),
            "phase": "META",
            "task_id": "",
            "event": "scope_revoke",
            "detail": "stale revoke (pre-exception)",
            "paths": ["foo/c.py"],
            "approved_by": "test",
            "files": [],
            "exit": 0,
        },
        # Exception lands AFTER the revoke — should still be in force.
        {
            "ts": _ts(-120),
            "phase": "META",
            "task_id": "META-00-install-hooks",
            "event": "scope_exception",
            "detail": "fresh exception",
            "paths": ["foo/c.py"],
            "approved_by": "test",
            "files": [],
            "exit": 0,
        },
    ]
    _seed_ledger(tmp_path, rows)
    target = tmp_path / "foo" / "c.py"
    proc = _run(
        {
            "tool_name": "Write",
            "tool_input": {"file_path": str(target), "content": "z = 3\n"},
        },
        tmp_path,
    )
    _assert_allow(proc)


# ---------------------------------------------- Gate 0: scope_exception paths


def test_gate0_rejects_scope_exception_write_missing_paths_key(tmp_path):
    """Writer-side assertion: an Edit to state/impl_progress.jsonl whose
    new_string contains a scope_exception row missing the ``paths`` key
    must be denied with a clear reason. This blocks the drift that left
    six historical rows silently authorising nothing.
    """
    # Seed an empty ledger so Gate 1 sees no active exceptions.
    _seed_ledger(tmp_path, [])
    ledger_path = tmp_path / "state" / "impl_progress.jsonl"
    bad_row = {
        "ts": _ts(-10),
        "phase": "META",
        "task_id": "T",
        "event": "scope_exception",
        "detail": "malformed row without paths",
        "approved_by": "test",
    }
    proc = _run(
        {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": str(ledger_path),
                "old_string": "",
                "new_string": json.dumps(bad_row) + "\n",
            },
        },
        tmp_path,
    )
    reason = _deny_reason(proc)
    assert "scope_exception" in reason
    assert "paths" in reason


def test_gate0_rejects_scope_exception_write_null_paths(tmp_path):
    """paths=None is the exact drift shape of five of the six historical
    rows — must be rejected."""
    _seed_ledger(tmp_path, [])
    ledger_path = tmp_path / "state" / "impl_progress.jsonl"
    bad_row = {
        "ts": _ts(-10),
        "phase": "META",
        "task_id": "T",
        "event": "scope_exception",
        "detail": "null paths",
        "paths": None,
        "approved_by": "test",
    }
    proc = _run(
        {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": str(ledger_path),
                "old_string": "",
                "new_string": json.dumps(bad_row) + "\n",
            },
        },
        tmp_path,
    )
    reason = _deny_reason(proc)
    assert "scope_exception" in reason
    assert "paths" in reason


def test_gate0_rejects_scope_exception_write_empty_paths_list(tmp_path):
    """An empty list authorises nothing, same failure-mode class as None."""
    _seed_ledger(tmp_path, [])
    ledger_path = tmp_path / "state" / "impl_progress.jsonl"
    bad_row = {
        "ts": _ts(-10),
        "phase": "META",
        "task_id": "T",
        "event": "scope_exception",
        "detail": "empty paths",
        "paths": [],
        "approved_by": "test",
    }
    proc = _run(
        {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": str(ledger_path),
                "old_string": "",
                "new_string": json.dumps(bad_row) + "\n",
            },
        },
        tmp_path,
    )
    reason = _deny_reason(proc)
    assert "scope_exception" in reason
    assert "paths" in reason


def test_gate0_allows_valid_scope_exception_write(tmp_path):
    """Control: a well-formed scope_exception row (non-empty list of
    strings) must NOT be rejected by Gate 0."""
    _seed_ledger(tmp_path, [])
    ledger_path = tmp_path / "state" / "impl_progress.jsonl"
    good_row = {
        "ts": _ts(-10),
        "phase": "META",
        "task_id": "T",
        "event": "scope_exception",
        "detail": "valid paths",
        "paths": ["foo/bar.py", "baz/qux.py"],
        "approved_by": "test",
        "files": [],
        "exit": 0,
    }
    proc = _run(
        {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": str(ledger_path),
                "old_string": "",
                "new_string": json.dumps(good_row) + "\n",
            },
        },
        tmp_path,
    )
    # Gate 0 must not trip. Other gates may still deny for unrelated
    # reasons (state/impl_progress.jsonl is in the META allow-list per
    # UNIVERSAL_ALLOW, so in practice this allows), but Gate 0's error
    # message must not appear.
    assert proc.returncode == 0, proc.stderr
    if proc.stdout.strip():
        payload = json.loads(proc.stdout)
        hso = payload.get("hookSpecificOutput") or {}
        reason = hso.get("permissionDecisionReason", "")
        assert "scope_exception ledger row requires" not in reason, payload


def test_reader_warns_on_null_paths_and_returns_valid_paths(capsys):
    """Reader shim: scope_exception_paths must emit a stderr WARN for
    each malformed row and still return the valid rows' paths."""
    import sys as _sys
    _sys.path.insert(0, str(REPO / "scripts"))
    from impl_common import scope_exception_paths  # noqa: WPS433

    rows = [
        {
            "event": "scope_exception",
            "paths": ["ok_a.py", "ok_b.py"],
            "ts": "2026-04-22T00:00:00Z",
        },
        # paths=None (drift shape)
        {
            "event": "scope_exception",
            "paths": None,
            "ts": "2026-04-22T00:00:01Z",
            "task_id": "NULL-T",
        },
        # paths key absent (drift shape)
        {
            "event": "scope_exception",
            "ts": "2026-04-22T00:00:02Z",
            "task_id": "MISSING-T",
        },
        # paths is a string (malformed type)
        {
            "event": "scope_exception",
            "paths": "not-a-list.py",
            "ts": "2026-04-22T00:00:03Z",
            "task_id": "STR-T",
        },
        # non-scope_exception rows ignored entirely
        {"event": "write", "paths": ["should_not_appear.py"]},
    ]
    out = scope_exception_paths(rows)
    assert out == ["ok_a.py", "ok_b.py"], out
    captured = capsys.readouterr()
    assert "WARN: scope_exception row without paths" in captured.err
    assert "NULL-T" in captured.err
    assert "MISSING-T" in captured.err
    assert "WARN: scope_exception row with non-list paths" in captured.err
    assert "type=str" in captured.err
