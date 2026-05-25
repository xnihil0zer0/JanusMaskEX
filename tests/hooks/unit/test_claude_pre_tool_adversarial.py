"""Adversarial battery for HOOK-22-claude-pre-tool (Phase 2).

Maps to the hooks-augmented plan §5 P2 matrix items:
  * 51-violation AST deny truncation
  * 6th-submission rate limit with correct journal row
  * Path-traversal attacks via ``../`` in Write.file_path
  * Clarification overflow (3rd request denied)
  * Planning-vs-synthesis mode confusion (submit_code blocked in planning)
  * Forged session_id cannot bypass a different session's rate limit
"""

from __future__ import annotations

import io
import json
import pathlib

import pytest

import harness.hooks.claude.pre_tool as pre_tool
from harness.hooks import _ledger


def _stage(tmp_path, monkeypatch, *, mode="synthesis"):
    state = tmp_path / "state"
    state.mkdir()
    workdir = state / "workdirs" / "claude" / "sess-adv"
    (workdir / "inbox").mkdir(parents=True)
    (workdir / "outbox").mkdir(parents=True)
    (workdir / "inbox" / "task.json").write_text(
        json.dumps({
            "task_id": "T",
            "synthesis_target_type": "pure_function",
            "constraints": {"deterministic": True},
        })
    )
    (state / "STATE.json").write_text(
        json.dumps({"round": 1, "phase": mode, "task_id": "T"})
    )
    monkeypatch.setenv("JANUSMASK_STATE_DIR", str(state))
    monkeypatch.setenv("JANUSMASK_WORK_DIR", str(workdir))
    monkeypatch.setenv("JANUSMASK_AGENT", "claude")
    monkeypatch.setenv("JANUSMASK_MODE", mode)
    return {"state": state, "workdir": workdir, "session_id": "sess-adv"}


def _run(tool_name, tool_input, session_id="sess-adv"):
    stdin = io.StringIO(json.dumps({
        "hook_event_name": "PreToolUse",
        "session_id": session_id,
        "tool_name": tool_name,
        "tool_input": tool_input,
    }))
    stdout = io.StringIO()
    pre_tool.main(stdin, stdout)
    return json.loads(stdout.getvalue())


class TestASTViolationTruncation:
    def test_fifty_one_errors_truncated_to_fifty(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch)
        # Each `import random` line produces one error-severity violation
        # under deterministic=True; 51 lines > max_show=50 triggers
        # truncation.
        body = (
            "\n".join("import random" for _ in range(51))
            + "\ndef f():\n    return 1\n"
        )
        target = str(env["workdir"] / "outbox" / "submission.py")
        out = _run("Write", {"file_path": target, "content": body})
        assert out["decision"] == "deny"
        # Reason should mention first-50 truncation.
        assert "50" in out["reason"]
        # Count violation bullets in the reason body.
        bullet_lines = [
            ln for ln in out["reason"].splitlines() if ln.lstrip().startswith("- L")
        ]
        assert len(bullet_lines) <= 50


class TestRateLimitInvariants:
    def test_rate_limited_outcome_does_not_touch_track_record(
        self, tmp_path, monkeypatch
    ):
        """Sub-plan 02 §4.3: rate-limit uses distinct journal row; must
        NOT emit ast_rejection track-record event."""
        env = _stage(tmp_path, monkeypatch)
        for _ in range(5):
            _ledger.append_hook_event(env["session_id"], "claude", "submit_code", "allow")
        target = str(env["workdir"] / "outbox" / "submission.py")
        _run("Write", {"file_path": target, "content": "def f(): return 1\n"})
        # track-record events live in state/track_record_events.jsonl; if the
        # hook wrongly emitted ast_rejection, that file would appear.
        # Absence is our assertion.
        tre = env["state"] / "track_record_events.jsonl"
        if tre.exists():
            rows = [
                json.loads(line)
                for line in tre.read_text().splitlines() if line.strip()
            ]
            rej = [r for r in rows if r.get("event_type") == "ast_rejection"]
            assert not rej, "rate-limit path must not emit ast_rejection"

    def test_forged_session_cannot_reset_victim_counter(
        self, tmp_path, monkeypatch
    ):
        env = _stage(tmp_path, monkeypatch)
        # Victim has 5 accepted submissions → maxed out.
        for _ in range(5):
            _ledger.append_hook_event("sess-victim", "claude", "submit_code", "allow")
        target = str(env["workdir"] / "outbox" / "submission.py")
        # Attacker forges session id in the hook envelope — they should
        # get their own empty counter (not borrow victim's maxed-out state)
        # and not be able to mutate victim's ledger.
        out = _run("Write", {"file_path": target, "content": "def f(): return 1\n"},
                   session_id="sess-attacker")
        assert out["decision"] == "allow"
        # Victim counter unchanged.
        assert _ledger.count_verb(
            _ledger.read_events("sess-victim", "claude"),
            "submit_code", outcome="allow",
        ) == 5


class TestPathTraversalAttack:
    def test_outbox_traversal_to_etc_passwd_denied(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch)
        escape = str(
            pathlib.Path(env["workdir"]) / "outbox" / ".." / ".." / ".." / ".." / "etc" / "passwd"
        )
        out = _run("Write", {"file_path": escape, "content": "x"})
        assert out["decision"] == "deny"

    def test_absolute_path_outside_workdir_denied(self, tmp_path, monkeypatch):
        _stage(tmp_path, monkeypatch)
        out = _run("Write", {"file_path": "/etc/hosts", "content": "x"})
        assert out["decision"] == "deny"


class TestClarificationOverflow:
    def test_third_clarification_denied(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch)
        for _ in range(2):
            _ledger.append_hook_event(
                env["session_id"], "claude", "clarification", "allow"
            )
        target = str(env["workdir"] / "outbox" / "clarification_anything.md")
        out = _run("Write", {"file_path": target, "content": "q3"})
        assert out["decision"] == "deny"

    def test_collisions_autonumber_not_overwrite(self, tmp_path, monkeypatch):
        """Agent-chosen filename must not let it overwrite a previous slot
        — the hook rewrites to the next free slot regardless of input."""
        env = _stage(tmp_path, monkeypatch)
        _ledger.append_hook_event(
            env["session_id"], "claude", "clarification", "allow"
        )
        # Agent tries to write over clarification_1.md
        target = str(env["workdir"] / "outbox" / "clarification_1.md")
        out = _run("Write", {"file_path": target, "content": "collision"})
        assert out["decision"] == "allow"
        # Renumbered to slot 2, not 1.
        assert "clarification_2.md" in out["tool_input"]["file_path"]
        assert "clarification_1.md" not in out["tool_input"]["file_path"]


class TestModeConfusion:
    def test_synthesis_cannot_submit_plan_draft(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch, mode="synthesis")
        target = str(env["workdir"] / "outbox" / "plan_draft.json")
        out = _run("Write", {"file_path": target, "content": "{}"})
        assert out["decision"] == "deny"

    def test_planning_cannot_submit_code(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch, mode="planning")
        target = str(env["workdir"] / "outbox" / "submission.py")
        out = _run("Write", {"file_path": target, "content": "def f(): pass\n"})
        assert out["decision"] == "deny"

    def test_reconciliation_cannot_submit_code(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch, mode="reconciliation")
        target = str(env["workdir"] / "outbox" / "submission.py")
        out = _run("Write", {"file_path": target, "content": "def f(): pass\n"})
        assert out["decision"] == "deny"


class TestDisallowedToolsSpecific:
    def test_mcp_janusmask_execute_denied(self, tmp_path, monkeypatch):
        """Regression guard: HOOK-26 settings will deny
        mcp__janusmask__execute via the permissions block, but the hook
        must also deny it at PreToolUse so we're double-belt-and-suspenders
        during the P5 drain phase."""
        _stage(tmp_path, monkeypatch)
        out = _run("mcp__janusmask__execute", {"args": "{}"})
        assert out["decision"] == "deny"

    def test_todowrite_denied(self, tmp_path, monkeypatch):
        _stage(tmp_path, monkeypatch)
        out = _run("TodoWrite", {"todos": []})
        assert out["decision"] == "deny"


class TestWarningsSurfaceAsAdditionalContext:
    def test_warning_not_error_allows_with_context(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch)
        target = str(env["workdir"] / "outbox" / "submission.py")
        # print() is a warning-severity side_effect per ast_enforcer;
        # warnings must not block the write.
        body = "def f():\n    print('hi')\n    return 1\n"
        out = _run("Write", {"file_path": target, "content": body})
        assert out["decision"] == "allow"
        hso = out.get("hookSpecificOutput") or {}
        assert "warning" in hso.get("additionalContext", "").lower()
