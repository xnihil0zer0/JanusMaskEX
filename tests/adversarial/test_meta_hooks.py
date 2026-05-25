"""Smoke-tests for the meta-hooks installed under scripts/impl_*.

Invokes each hook as a subprocess with crafted stdin, asserting deny/allow
outcomes and correct ledger mutations. Covers the §9 step-4 checklist:
  (a) write outside phase allow-list denied,
  (b) Stop with no test_pass blocked,
  (c) git commit when DoD unmet denied.
Plus AST gate, scope_exception bypass, stop_hook_active escape, blocked
escape hatch, settings-mutation gate, and post_write ledger recording.

Each test runs against a tmp_path project dir to keep the real ledger
untouched.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"


def _run(script_name: str, stdin_payload: dict, tmp_path: pathlib.Path,
         extra_env: dict | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
    env["JANUSMASK_PROJECT_DIR"] = str(tmp_path)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script_name)],
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


def _recent_start(task: str, phase: str) -> dict:
    import datetime
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"ts": ts, "phase": phase, "task_id": task, "event": "start",
            "detail": "", "files": [], "exit": 0}


def _old_start(task: str, phase: str, seconds_ago: int = 3600) -> dict:
    import datetime
    dt = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=seconds_ago)
    ts = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"ts": ts, "phase": phase, "task_id": task, "event": "start",
            "detail": "", "files": [], "exit": 0}


def _deny_reason(proc: subprocess.CompletedProcess) -> str:
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    hso = payload.get("hookSpecificOutput") or {}
    assert hso.get("permissionDecision") == "deny", payload
    return hso.get("permissionDecisionReason", "")


def _assert_allow(proc: subprocess.CompletedProcess) -> None:
    assert proc.returncode == 0, proc.stderr
    # Allow = empty stdout (no permissionDecision emitted).
    if proc.stdout.strip():
        payload = json.loads(proc.stdout)
        hso = payload.get("hookSpecificOutput") or {}
        assert hso.get("permissionDecision") != "deny", proc.stdout


# ---------------------- pre_write gate tests ----------------------


def test_write_outside_phase_scope_denied(tmp_path):
    _seed_ledger(tmp_path, [_recent_start("P0.4", "P0")])
    target = tmp_path / "harness" / "hooks" / "claude" / "session_start.py"
    proc = _run("impl_pre_write.py",
                {"tool_name": "Write",
                 "tool_input": {"file_path": str(target), "content": "x = 1\n"}},
                tmp_path)
    reason = _deny_reason(proc)
    assert "out of scope" in reason
    assert "harness/hooks/claude/session_start.py" in reason


def test_write_inside_phase_scope_allowed(tmp_path):
    _seed_ledger(tmp_path, [_recent_start("P0.4", "P0")])
    target = tmp_path / "harness" / "orchestrator.py"
    proc = _run("impl_pre_write.py",
                {"tool_name": "Write",
                 "tool_input": {"file_path": str(target), "content": "x = 1\n"}},
                tmp_path)
    _assert_allow(proc)


def test_ast_invalid_python_denied(tmp_path):
    _seed_ledger(tmp_path, [_recent_start("P0.4", "P0")])
    target = tmp_path / "harness" / "orchestrator.py"
    proc = _run("impl_pre_write.py",
                {"tool_name": "Write",
                 "tool_input": {"file_path": str(target),
                                "content": "def broken(:\n    return 1\n"}},
                tmp_path)
    reason = _deny_reason(proc)
    assert "Python AST parse failed" in reason


def test_scope_exception_row_bypasses_phase_gate(tmp_path):
    rows = [
        _recent_start("P0.4", "P0"),
        {"ts": "2026-04-17T00:00:00Z", "event": "scope_exception",
         "task_id": "P0.4", "phase": "P0",
         "paths": ["harness/hooks/claude/session_start.py"],
         "detail": "test bypass", "files": [], "exit": 0,
         "approved_by": "human"},
    ]
    _seed_ledger(tmp_path, rows)
    target = tmp_path / "harness" / "hooks" / "claude" / "session_start.py"
    proc = _run("impl_pre_write.py",
                {"tool_name": "Write",
                 "tool_input": {"file_path": str(target), "content": "x=1\n"}},
                tmp_path)
    _assert_allow(proc)


def test_settings_mutation_requires_recent_start(tmp_path):
    # Stale start row (far in the past) should not authorise settings edits.
    _seed_ledger(tmp_path, [_old_start("META-00-install-hooks", "META", seconds_ago=7200)])
    target = tmp_path / ".claude" / "settings.local.json"
    proc = _run("impl_pre_write.py",
                {"tool_name": "Write",
                 "tool_input": {"file_path": str(target), "content": "{}"}},
                tmp_path)
    reason = _deny_reason(proc)
    assert "settings" in reason.lower() or "meta-config" in reason.lower()


def test_settings_mutation_allowed_with_recent_start(tmp_path):
    _seed_ledger(tmp_path, [_recent_start("META-00-install-hooks", "META")])
    target = tmp_path / ".claude" / "settings.local.json"
    proc = _run("impl_pre_write.py",
                {"tool_name": "Write",
                 "tool_input": {"file_path": str(target), "content": "{}"}},
                tmp_path)
    _assert_allow(proc)


def test_enforce_flag_requires_p5_gate(tmp_path):
    _seed_ledger(tmp_path, [_recent_start("P5.1", "P5")])
    target = tmp_path / "harness" / "config.yaml"
    content = "hooks:\n  mode: enforce\n  enforce_verbs: [submit_code]\n"
    proc = _run("impl_pre_write.py",
                {"tool_name": "Write",
                 "tool_input": {"file_path": str(target), "content": content}},
                tmp_path)
    reason = _deny_reason(proc)
    assert "P5" in reason or "shadow" in reason.lower()


# ---------------------- pre_bash gate tests ----------------------


def test_git_commit_without_test_pass_denied(tmp_path):
    _seed_ledger(tmp_path, [_recent_start("P0.4", "P0")])
    proc = _run("impl_pre_bash.py",
                {"tool_name": "Bash",
                 "tool_input": {"command": "git commit -m 'wip'"}},
                tmp_path)
    reason = _deny_reason(proc)
    assert "P0.4" in reason
    assert "test_pass" in reason


def test_git_commit_with_full_dod_allowed(tmp_path):
    rows = [
        _recent_start("P0.4", "P0"),
        {"ts": "2026-04-17T00:00:01Z", "event": "test_pass",
         "task_id": "P0.4", "phase": "P0", "detail": "", "files": [], "exit": 0},
        {"ts": "2026-04-17T00:00:02Z", "event": "adv_pass",
         "task_id": "P0.4", "phase": "P0", "detail": "", "files": [], "exit": 0},
    ]
    _seed_ledger(tmp_path, rows)
    proc = _run("impl_pre_bash.py",
                {"tool_name": "Bash",
                 "tool_input": {"command": "git commit -m 'done'"}},
                tmp_path)
    _assert_allow(proc)


def test_non_git_bash_always_allowed(tmp_path):
    _seed_ledger(tmp_path, [_recent_start("P0.4", "P0")])
    proc = _run("impl_pre_bash.py",
                {"tool_name": "Bash",
                 "tool_input": {"command": "pytest tests/"}},
                tmp_path)
    _assert_allow(proc)


# ---------------------- stop gate tests ----------------------


def test_stop_blocked_when_dod_unmet(tmp_path):
    _seed_ledger(tmp_path, [_recent_start("META-00-install-hooks", "META")])
    proc = _run("impl_stop_gate.py", {"stop_hook_active": False}, tmp_path)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload.get("decision") == "block"
    assert "DoD unmet" in payload.get("reason", "")
    # Ledger should record a stop_block.
    ledger = (tmp_path / "state" / "impl_progress.jsonl").read_text()
    assert '"event": "stop_block"' in ledger


def test_stop_hook_active_passthrough(tmp_path):
    _seed_ledger(tmp_path, [_recent_start("META-00-install-hooks", "META")])
    proc = _run("impl_stop_gate.py", {"stop_hook_active": True}, tmp_path)
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""  # No block payload.


def test_stop_blocked_escape_hatch(tmp_path):
    rows = [
        _recent_start("META-00-install-hooks", "META"),
        {"ts": "2026-04-17T00:00:10Z", "event": "blocked",
         "task_id": "META-00-install-hooks", "phase": "META",
         "detail": "waiting on human review", "files": [], "exit": 0},
    ]
    _seed_ledger(tmp_path, rows)
    proc = _run("impl_stop_gate.py", {"stop_hook_active": False}, tmp_path)
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""  # Allowed through.


# ---------------------- post_write ledger recording ----------------------


def test_post_write_records_write_row(tmp_path):
    _seed_ledger(tmp_path, [_recent_start("P0.4", "P0")])
    # Create a real file so ast.parse has something to chew on.
    target = tmp_path / "harness" / "orchestrator.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("x = 1\n", encoding="utf-8")
    proc = _run("impl_post_write.py",
                {"tool_name": "Write",
                 "tool_input": {"file_path": str(target)}},
                tmp_path)
    assert proc.returncode == 0
    ledger_text = (tmp_path / "state" / "impl_progress.jsonl").read_text()
    rows = [json.loads(line) for line in ledger_text.strip().splitlines()]
    # A write row should exist mentioning the just-written file.
    write_rows = [r for r in rows if r.get("event") == "write"
                  and "harness/orchestrator.py" in r.get("files", [])]
    assert write_rows, f"no write row for harness/orchestrator.py in ledger: {rows}"
    # And the trailing test_fail is acceptable (test module absent in tmp fixture).
    assert rows[-1]["event"] in ("write", "test_pass", "test_fail")
