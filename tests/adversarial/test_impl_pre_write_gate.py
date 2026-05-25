"""Adversarial tests for the Gate 2 AST parse behaviour in
scripts/impl_pre_write.py.

Pre-patch the gate ran ``ast.parse`` on the Edit snippet in isolation,
which spuriously rejected valid mid-function indented blocks. The patched
gate parses the *resulting full file* on Edit (and the raw content on
Write), so column-offset snippets are accepted while real syntax errors
in the merged result are still rejected.

Drives ``scripts/impl_pre_write.py`` as a subprocess with stdin JSON,
mirroring the pattern in ``tests/adversarial/test_meta_hooks.py``. Each
test points ``JANUSMASK_PROJECT_DIR`` at ``tmp_path`` so the on-disk read
inside Gate 2 sees a synthetic file, and seeds a ledger row that
authorises writes under ``harness/``.
"""

from __future__ import annotations

import datetime
import json
import os
import pathlib
import subprocess
import sys

import pytest

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
        timeout=15,
        env=env,
    )


def _seed_ledger(tmp_path: pathlib.Path, rows: list) -> None:
    ledger = tmp_path / "state" / "impl_progress.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(json.dumps(r) for r in rows)
    ledger.write_text(body + ("\n" if body else ""), encoding="utf-8")


def _recent_start(task: str, phase: str) -> dict:
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"ts": ts, "phase": phase, "task_id": task, "event": "start",
            "detail": "", "files": [], "exit": 0}


def _write_target(tmp_path: pathlib.Path, rel: str, body: str) -> pathlib.Path:
    target = tmp_path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    return target


def _assert_allow(proc: subprocess.CompletedProcess) -> None:
    assert proc.returncode == 0, proc.stderr
    if proc.stdout.strip():
        payload = json.loads(proc.stdout)
        hso = payload.get("hookSpecificOutput") or {}
        assert hso.get("permissionDecision") != "deny", proc.stdout


def _deny_reason(proc: subprocess.CompletedProcess) -> str:
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    hso = payload.get("hookSpecificOutput") or {}
    assert hso.get("permissionDecision") == "deny", payload
    return hso.get("permissionDecisionReason", "")


@pytest.fixture
def seeded(tmp_path):
    """tmp_path with a recent P0.4 start row, ledger seeded, plus a stub
    tests/test_orchestrator.py so Gate 3 (test-partner gate) is satisfied
    for any test that edits harness/orchestrator.py.
    """
    _seed_ledger(tmp_path, [_recent_start("P0.4", "P0")])
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    (tests_dir / "test_orchestrator.py").write_text(
        "def test_smoke():\n    pass\n"
    )
    return tmp_path


# ---------------------- PASS cases (gate must allow) ----------------------


def test_edit_replaces_function_body_with_indented_snippet(seeded):
    """Indented mid-function snippet (column 4) - failed pre-patch."""
    target = _write_target(
        seeded, "harness/orchestrator.py",
        "def foo():\n    return 1\n",
    )
    payload = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(target),
            "old_string": "    return 1\n",
            "new_string": "    x = 2\n    y = x + 1\n    return y\n",
        },
    }
    proc = _run(payload, seeded)
    _assert_allow(proc)


def test_edit_adds_new_top_level_def(seeded):
    """Top-level (column 0) edit - would parse as snippet too, sanity check."""
    target = _write_target(
        seeded, "harness/orchestrator.py",
        "def foo():\n    return 1\n",
    )
    payload = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(target),
            "old_string": "def foo():\n    return 1\n",
            "new_string": "def foo():\n    return 1\n\n\ndef bar():\n    return 2\n",
        },
    }
    proc = _run(payload, seeded)
    _assert_allow(proc)


def test_edit_replaces_one_line_return(seeded):
    target = _write_target(
        seeded, "harness/orchestrator.py",
        "def foo():\n    return 1\n",
    )
    payload = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(target),
            "old_string": "return 1",
            "new_string": "return 42",
        },
    }
    proc = _run(payload, seeded)
    _assert_allow(proc)


def test_write_brand_new_full_file(seeded):
    target = seeded / "harness" / "orchestrator.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": str(target),
            "content": "def foo():\n    return 1\n",
        },
    }
    proc = _run(payload, seeded)
    _assert_allow(proc)


# ---------------------- FAIL cases (gate must deny) ----------------------


def test_edit_with_broken_signature_denied(seeded):
    """`def foo(:` is a SyntaxError in the resulting file."""
    target = _write_target(
        seeded, "harness/orchestrator.py",
        "def foo():\n    return 1\n",
    )
    payload = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(target),
            "old_string": "def foo():",
            "new_string": "def foo(:",
        },
    }
    proc = _run(payload, seeded)
    reason = _deny_reason(proc)
    assert "Python AST parse failed" in reason


def test_edit_unbalanced_parens_in_merged_file_denied(seeded):
    """Snippet alone might parse, but the resulting file is unbalanced."""
    target = _write_target(
        seeded, "harness/orchestrator.py",
        "result = compute(\n    1,\n    2,\n)\n",
    )
    payload = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(target),
            "old_string": "result = compute(\n",
            "new_string": "result = compute\n",
        },
    }
    proc = _run(payload, seeded)
    reason = _deny_reason(proc)
    assert "Python AST parse failed" in reason


def test_write_full_file_with_syntax_error_denied(seeded):
    target = seeded / "harness" / "orchestrator.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": str(target),
            "content": "def broken(:\n    return 1\n",
        },
    }
    proc = _run(payload, seeded)
    reason = _deny_reason(proc)
    assert "Python AST parse failed" in reason


# ---------------------- Fallback / edge cases ----------------------


def test_edit_old_string_absent_falls_back_to_snippet_parse(seeded):
    """old_string not in disk -> patch falls back to parsing the snippet."""
    target = _write_target(
        seeded, "harness/orchestrator.py",
        "def foo():\n    return 1\n",
    )
    payload = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(target),
            "old_string": "this_text_is_not_in_the_file",
            "new_string": "x = 1\n",
        },
    }
    proc = _run(payload, seeded)
    _assert_allow(proc)


def test_edit_old_string_ambiguous_falls_back_to_snippet_parse(seeded):
    """old_string appears twice (replace_all=False) -> snippet fallback."""
    target = _write_target(
        seeded, "harness/orchestrator.py",
        "x = 1\nx = 1\n",
    )
    payload = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(target),
            "old_string": "x = 1",
            "new_string": "y = 2",
        },
    }
    proc = _run(payload, seeded)
    _assert_allow(proc)


def test_edit_replace_all_true_merges_full_file(seeded):
    """replace_all=True with multiple matches still parses the merged file."""
    target = _write_target(
        seeded, "harness/orchestrator.py",
        "def foo():\n    return 1\n\ndef bar():\n    return 1\n",
    )
    payload = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(target),
            "old_string": "    return 1\n",
            "new_string": "    z = 9\n    return z\n",
            "replace_all": True,
        },
    }
    proc = _run(payload, seeded)
    _assert_allow(proc)


def test_edit_target_file_missing_falls_back_to_snippet_parse(seeded):
    """Disk read OSError -> patch falls back to snippet parse.

    Use an allow-listed path (harness/orchestrator.py) but do NOT
    pre-create it in tmp_path, so Gate 1 (scope) passes, the patched
    Gate 2's disk read raises OSError, and parse_src falls back to
    the snippet itself (an indented assignment) which IndentationErrors.
    """
    target = seeded / "harness" / "orchestrator.py"
    assert not target.exists(), "fixture must not pre-create the target"
    payload = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(target),
            "old_string": "anything",
            "new_string": "    indented = True\n",
        },
    }
    proc = _run(payload, seeded)
    reason = _deny_reason(proc)
    assert "Python AST parse failed" in reason
