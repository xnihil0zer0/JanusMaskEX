"""Unit tests for harness.hooks.claude.pre_tool (HOOK-22 / P2).

Gate 3 partner: the full dotted path harness.hooks.claude.pre_tool is
imported below so the post-write gate recognises this file as the test
partner for the new module.
"""

from __future__ import annotations

import io
import json
import pathlib
from textwrap import dedent

import pytest

import harness.hooks.claude.pre_tool as pre_tool
from harness.hooks import _ledger
from harness.hooks.claude import pre_tool as pt_mod


def _stage(tmp_path, monkeypatch, *, mode="synthesis", task_body=None):
    state = tmp_path / "state"
    state.mkdir()
    workdir = state / "workdirs" / "claude" / "sess"
    (workdir / "inbox").mkdir(parents=True)
    (workdir / "outbox").mkdir(parents=True)
    if task_body is None:
        task_body = {
            "task_id": "T1",
            "synthesis_target_type": "pure_function",
            "constraints": {"deterministic": True},
        }
    (workdir / "inbox" / "task.json").write_text(json.dumps(task_body))
    (state / "STATE.json").write_text(
        json.dumps({"round": 1, "phase": mode, "task_id": "T1"})
    )
    monkeypatch.setenv("JANUSMASK_STATE_DIR", str(state))
    monkeypatch.setenv("JANUSMASK_WORK_DIR", str(workdir))
    monkeypatch.setenv("JANUSMASK_AGENT", "claude")
    monkeypatch.setenv("JANUSMASK_MODE", mode)
    return {"state": state, "workdir": workdir, "session_id": "sess"}


def _run(tool_name, tool_input, session_id="sess"):
    stdin = io.StringIO(json.dumps({
        "hook_event_name": "PreToolUse",
        "session_id": session_id,
        "tool_name": tool_name,
        "tool_input": tool_input,
    }))
    stdout = io.StringIO()
    pre_tool.main(stdin, stdout)
    return json.loads(stdout.getvalue())


CLEAN_CODE = "def add(a, b):\n    return a + b\n"
AST_INVALID_CODE = "def bad(:\n    x = y\n"  # syntax error


class TestToolAllowlist:
    def test_disallowed_tool_denied(self, tmp_path, monkeypatch):
        _stage(tmp_path, monkeypatch)
        for tool in ("Bash", "Edit", "WebFetch", "Agent", "Task", "NotebookEdit"):
            out = _run(tool, {"command": "echo"})
            assert out["decision"] == "deny", f"{tool} should be denied"

    def test_allowed_tools_not_auto_denied(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch)
        for tool in ("Read", "Glob", "Grep"):
            out = _run(tool, {"file_path": str(env["workdir"] / "inbox" / "task.json")})
            assert out["decision"] == "allow"


class TestReadPathSafety:
    def test_read_under_workdir_allowed(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch)
        out = _run("Read", {"file_path": str(env["workdir"] / "inbox" / "task.json")})
        assert out["decision"] == "allow"

    def test_read_under_state_allowed(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch)
        target = env["state"] / "tasks" / "foo.json"
        target.parent.mkdir(parents=True)
        target.write_text("{}")
        out = _run("Read", {"file_path": str(target)})
        assert out["decision"] == "allow"

    def test_read_outside_roots_denied(self, tmp_path, monkeypatch):
        _stage(tmp_path, monkeypatch)
        out = _run("Read", {"file_path": "/etc/passwd"})
        assert out["decision"] == "deny"
        assert "allowed roots" in out["reason"].lower()

    def test_traversal_attempt_denied(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch)
        # Create sibling dir outside state/ so traversal lands outside
        # every allowed root (state_dir, docs, briefs, workdir).
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("s")
        escape = str(
            env["workdir"] / ".." / ".." / ".." / ".." / "outside" / "secret.txt"
        )
        out = _run("Read", {"file_path": escape})
        assert out["decision"] == "deny"

    def test_glob_with_no_file_path_allowed(self, tmp_path, monkeypatch):
        _stage(tmp_path, monkeypatch)
        out = _run("Glob", {"pattern": "**/*.py"})
        # Glob/Grep may not carry a path; the hook allows them since
        # there's nothing concrete to gate on here (they'll be Read-
        # gated when results are opened).
        assert out["decision"] == "allow"


class TestWriteSubmissionSynthesis:
    def test_clean_code_allowed(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch)
        target = str(env["workdir"] / "outbox" / "submission.py")
        out = _run("Write", {"file_path": target, "content": CLEAN_CODE})
        assert out["decision"] == "allow"

    def test_ast_invalid_denied_with_violations(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch)
        target = str(env["workdir"] / "outbox" / "submission.py")
        out = _run("Write", {"file_path": target, "content": AST_INVALID_CODE})
        assert out["decision"] == "deny"
        assert "syntax" in out["reason"].lower() or "L1" in out["reason"] or "L2" in out["reason"]

    def test_ast_deny_appends_deny_ledger_row(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch)
        target = str(env["workdir"] / "outbox" / "submission.py")
        _run("Write", {"file_path": target, "content": AST_INVALID_CODE})
        rows = _ledger.read_events(env["session_id"], "claude")
        assert any(
            r["verb"] == "submit_code" and r["outcome"] == "deny" for r in rows
        )

    def test_rate_limit_denies_sixth_submission(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch)
        # Seed 5 accepted submissions in the ledger.
        for _ in range(5):
            _ledger.append_hook_event(env["session_id"], "claude", "submit_code", "allow")
        target = str(env["workdir"] / "outbox" / "submission.py")
        out = _run("Write", {"file_path": target, "content": CLEAN_CODE})
        assert out["decision"] == "deny"
        assert "rate limit" in out["reason"].lower() or "5/5" in out["reason"]

    def test_rate_limit_emits_rate_limited_ledger_row_not_ast_rejection(
        self, tmp_path, monkeypatch
    ):
        env = _stage(tmp_path, monkeypatch)
        for _ in range(5):
            _ledger.append_hook_event(env["session_id"], "claude", "submit_code", "allow")
        target = str(env["workdir"] / "outbox" / "submission.py")
        _run("Write", {"file_path": target, "content": CLEAN_CODE})
        rows = _ledger.read_events(env["session_id"], "claude")
        rate_rows = [
            r for r in rows
            if r["verb"] == "submit_code" and r["outcome"] == "rate_limited"
        ]
        assert rate_rows, "expected rate_limited row on 6th submission"

    def test_deterministic_false_allows_nondet(self, tmp_path, monkeypatch):
        env = _stage(
            tmp_path, monkeypatch,
            task_body={
                "task_id": "T",
                "synthesis_target_type": "pure_function",
                "constraints": {"deterministic": False},
            },
        )
        code_with_random = "import random\ndef r():\n    return random.random()\n"
        target = str(env["workdir"] / "outbox" / "submission.py")
        out = _run("Write", {"file_path": target, "content": code_with_random})
        # With deterministic=False, random import is allowed — should not
        # be denied as an AST error.
        assert out["decision"] == "allow"


class TestWritePlanDraft:
    VALID_PLAN = {
        "plan_version": "v1",
        "tasks": [],
    }

    def test_invalid_json_denied(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch, mode="planning")
        target = str(env["workdir"] / "outbox" / "plan_draft.json")
        out = _run("Write", {"file_path": target, "content": "{not json"})
        assert out["decision"] == "deny"
        assert "json" in out["reason"].lower()

    def test_single_shot_second_write_denied(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch, mode="planning")
        _ledger.append_hook_event(env["session_id"], "claude", "plan_draft", "allow")
        target = str(env["workdir"] / "outbox" / "plan_draft.json")
        out = _run(
            "Write", {"file_path": target, "content": json.dumps(self.VALID_PLAN)}
        )
        assert out["decision"] == "deny"
        assert "single-shot" in out["reason"].lower() or "already" in out["reason"].lower()


class TestWriteReconciliation:
    def test_invalid_json_denied(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch, mode="reconciliation")
        target = str(env["workdir"] / "outbox" / "reconciliation.json")
        out = _run("Write", {"file_path": target, "content": "{not json"})
        assert out["decision"] == "deny"

    def test_unknown_stance_denied(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch, mode="reconciliation")
        # Stage a current_diff.json so diff_item_ids validate.
        diff_dir = env["state"] / "planning"
        diff_dir.mkdir()
        (diff_dir / "current_diff.json").write_text(
            json.dumps({"items": [{"diff_item_id": "D1"}]})
        )
        body = {"responses": [{"diff_item_id": "D1", "stance": "rage"}]}
        target = str(env["workdir"] / "outbox" / "reconciliation.json")
        out = _run("Write", {"file_path": target, "content": json.dumps(body)})
        assert out["decision"] == "deny"
        assert "stance" in out["reason"].lower()

    def test_single_shot_second_write_denied(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch, mode="reconciliation")
        _ledger.append_hook_event(env["session_id"], "claude", "reconciliation", "allow")
        target = str(env["workdir"] / "outbox" / "reconciliation.json")
        out = _run(
            "Write", {"file_path": target, "content": json.dumps({"responses": []})}
        )
        assert out["decision"] == "deny"


class TestWriteClarificationRenumber:
    def test_first_clarification_renumbered_to_slot_1(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch)
        target = str(env["workdir"] / "outbox" / "clarification_42.md")
        out = _run("Write", {"file_path": target, "content": "why?"})
        assert out["decision"] == "allow"
        expected = str(env["workdir"] / "outbox" / "clarification_1.md")
        assert out["tool_input"]["file_path"] == expected

    def test_second_clarification_renumbered_to_slot_2(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch)
        _ledger.append_hook_event(env["session_id"], "claude", "clarification", "allow")
        target = str(env["workdir"] / "outbox" / "clarification_X.md")
        out = _run("Write", {"file_path": target, "content": "follow-up"})
        assert out["decision"] == "allow"
        expected = str(env["workdir"] / "outbox" / "clarification_2.md")
        assert out["tool_input"]["file_path"] == expected

    def test_third_clarification_denied(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch)
        for _ in range(2):
            _ledger.append_hook_event(env["session_id"], "claude", "clarification", "allow")
        target = str(env["workdir"] / "outbox" / "clarification_1.md")
        out = _run("Write", {"file_path": target, "content": "nope"})
        assert out["decision"] == "deny"
        assert "rate limit" in out["reason"].lower() or "2/2" in out["reason"]


class TestWriteErrorReport:
    def test_small_error_allowed(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch)
        target = str(env["workdir"] / "outbox" / "error.md")
        out = _run("Write", {"file_path": target, "content": "oops"})
        assert out["decision"] == "allow"

    def test_oversized_error_denied(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch)
        target = str(env["workdir"] / "outbox" / "error.md")
        big = "x" * (64 * 1024 + 1)
        out = _run("Write", {"file_path": target, "content": big})
        assert out["decision"] == "deny"
        assert "64" in out["reason"]


class TestWritePathDiscipline:
    def test_write_outside_outbox_denied(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch)
        out = _run("Write", {"file_path": "/tmp/escape.py", "content": "x"})
        assert out["decision"] == "deny"

    def test_write_to_inbox_denied(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch)
        target = str(env["workdir"] / "inbox" / "task.json")
        out = _run("Write", {"file_path": target, "content": "x"})
        assert out["decision"] == "deny"

    def test_write_random_outbox_file_denied(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch)
        target = str(env["workdir"] / "outbox" / "random.txt")
        out = _run("Write", {"file_path": target, "content": "x"})
        assert out["decision"] == "deny"
        assert "outbox contract" in out["reason"].lower() or "not in" in out["reason"].lower()


class TestModeGating:
    def test_submission_blocked_in_planning(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch, mode="planning")
        target = str(env["workdir"] / "outbox" / "submission.py")
        out = _run("Write", {"file_path": target, "content": CLEAN_CODE})
        assert out["decision"] == "deny"
        assert "mode" in out["reason"].lower() or "planning" in out["reason"].lower()

    def test_plan_draft_blocked_in_synthesis(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch, mode="synthesis")
        target = str(env["workdir"] / "outbox" / "plan_draft.json")
        out = _run("Write", {"file_path": target, "content": "{}"})
        assert out["decision"] == "deny"

    def test_error_allowed_in_all_modes(self, tmp_path, monkeypatch):
        for mode in ("synthesis", "planning", "reconciliation"):
            sub = tmp_path / mode
            sub.mkdir()
            env = _stage(sub, monkeypatch, mode=mode)
            target = str(env["workdir"] / "outbox" / "error.md")
            out = _run("Write", {"file_path": target, "content": "e"})
            assert out["decision"] == "allow", f"error.md should be allowed in {mode}"


class TestMalformedInput:
    def test_garbage_stdin_denies_with_reason(self, tmp_path, monkeypatch):
        _stage(tmp_path, monkeypatch)
        stdout = io.StringIO()
        pre_tool.main(io.StringIO("{garbage"), stdout)
        out = json.loads(stdout.getvalue())
        assert out["decision"] == "deny"
        assert "malformed" in out["reason"].lower()

    def test_missing_tool_name_denied(self, tmp_path, monkeypatch):
        _stage(tmp_path, monkeypatch)
        out = _run("", {"file_path": "/tmp/x"})
        assert out["decision"] == "deny"
