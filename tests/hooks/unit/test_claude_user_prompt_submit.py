"""Unit tests for harness.hooks.claude.user_prompt_submit (HOOK-21 / P2).

Gate 3 partner: the full dotted path harness.hooks.claude.user_prompt_submit
is imported below so the post-write gate recognises this file as the
test partner for the new module.
"""

from __future__ import annotations

import io
import json

import pytest

import harness.hooks.claude.user_prompt_submit as user_prompt_submit
from harness.hooks import _ledger
from harness.hooks.claude import user_prompt_submit as ups_mod


def _stage(tmp_path, monkeypatch, *, mode, state_round=1, phase=None, files=None):
    state = tmp_path / "state"
    state.mkdir(exist_ok=True)
    workdir = state / "workdirs" / "claude" / "sess"
    (workdir / "inbox").mkdir(parents=True, exist_ok=True)
    files = files or {}
    for name, body in files.items():
        (workdir / "inbox" / name).write_text(json.dumps(body))
    (state / "STATE.json").write_text(
        json.dumps({"round": state_round, "phase": phase or mode})
    )
    monkeypatch.setenv("JANUSMASK_STATE_DIR", str(state))
    monkeypatch.setenv("JANUSMASK_WORK_DIR", str(workdir))
    monkeypatch.setenv("JANUSMASK_AGENT", "claude")
    monkeypatch.setenv("JANUSMASK_MODE", mode)
    monkeypatch.setenv("JANUSMASK_ROUND", str(state_round))
    return {"state": state, "workdir": workdir, "session_id": "sess"}


def _run(session_id: str):
    stdin = io.StringIO(json.dumps({
        "hook_event_name": "UserPromptSubmit",
        "session_id": session_id,
        "prompt": "hi",
    }))
    stdout = io.StringIO()
    rc = user_prompt_submit.main(stdin, stdout)
    return rc, json.loads(stdout.getvalue())


class TestTaskInjection:
    def test_synthesis_injects_task_on_first_turn(self, tmp_path, monkeypatch):
        env = _stage(
            tmp_path, monkeypatch, mode="synthesis",
            files={"task.json": {"task_id": "T1", "specification": "write foo"}},
        )
        rc, out = _run(env["session_id"])
        assert rc == 0
        assert out["decision"] == "allow"
        ctx = out["hookSpecificOutput"]["additionalContext"]
        assert "TASK" in ctx
        assert "write foo" in ctx
        assert out["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"

    def test_task_read_marker_suppresses_second_injection(
        self, tmp_path, monkeypatch
    ):
        env = _stage(
            tmp_path, monkeypatch, mode="synthesis",
            files={"task.json": {"task_id": "T1", "specification": "once"}},
        )
        _run(env["session_id"])
        _, out2 = _run(env["session_id"])
        ctx2 = out2["hookSpecificOutput"]["additionalContext"]
        # Task body gone on turn 2; only locked-field reminder remains.
        assert "TASK" not in ctx2
        assert "once" not in ctx2
        assert "Identity:" in ctx2

    def test_task_read_ledger_row_appended(self, tmp_path, monkeypatch):
        env = _stage(
            tmp_path, monkeypatch, mode="synthesis",
            files={"task.json": {"task_id": "T1"}},
        )
        _run(env["session_id"])
        rows = _ledger.read_events(env["session_id"], "claude")
        task_reads = [r for r in rows if r["verb"] == "task_read"]
        assert task_reads and task_reads[-1]["outcome"] == "allow"


class TestPlanningModeDualBranch:
    def test_planning_prefers_diff_summary_when_present(self, tmp_path, monkeypatch):
        env = _stage(
            tmp_path, monkeypatch, mode="planning",
            files={
                "brief.json": {"title": "brief-body"},
                "diff_summary.json": {"items": [{"diff_item_id": "D1"}]},
            },
        )
        _, out = _run(env["session_id"])
        ctx = out["hookSpecificOutput"]["additionalContext"]
        assert "DIFF_SUMMARY" in ctx
        assert "D1" in ctx
        assert "brief-body" not in ctx

    def test_planning_falls_back_to_brief_when_no_diff_summary(
        self, tmp_path, monkeypatch
    ):
        env = _stage(
            tmp_path, monkeypatch, mode="planning",
            files={"brief.json": {"title": "brief-body"}},
        )
        _, out = _run(env["session_id"])
        ctx = out["hookSpecificOutput"]["additionalContext"]
        assert "BRIEF" in ctx
        assert "brief-body" in ctx

    def test_reconciliation_reads_diff_summary(self, tmp_path, monkeypatch):
        env = _stage(
            tmp_path, monkeypatch, mode="reconciliation",
            files={"diff_summary.json": {"items": []}},
        )
        _, out = _run(env["session_id"])
        ctx = out["hookSpecificOutput"]["additionalContext"]
        assert "DIFF_SUMMARY" in ctx


class TestFeedbackInjection:
    def test_cross_examination_phase_injects_feedback(self, tmp_path, monkeypatch):
        env = _stage(
            tmp_path, monkeypatch, mode="synthesis", phase="cross_examination",
            files={
                "task.json": {"task_id": "T"},
                "feedback.json": {"notes": "review me"},
            },
        )
        _, out = _run(env["session_id"])
        ctx = out["hookSpecificOutput"]["additionalContext"]
        assert "CROSS-EXAMINATION FEEDBACK" in ctx
        assert "review me" in ctx

    def test_non_cross_examination_phase_does_not_inject_feedback(
        self, tmp_path, monkeypatch
    ):
        # Phase is synthesis; feedback.json present but the phase-gate
        # forbids injection — matches mcp_server.cmd_get_feedback guard.
        env = _stage(
            tmp_path, monkeypatch, mode="synthesis", phase="synthesis",
            files={
                "task.json": {"task_id": "T"},
                "feedback.json": {"notes": "leaked?"},
            },
        )
        _, out = _run(env["session_id"])
        ctx = out["hookSpecificOutput"]["additionalContext"]
        assert "FEEDBACK" not in ctx
        assert "leaked?" not in ctx

    def test_feedback_read_marker_suppresses_second_injection(
        self, tmp_path, monkeypatch
    ):
        env = _stage(
            tmp_path, monkeypatch, mode="synthesis", phase="cross_examination",
            files={"feedback.json": {"notes": "once"}},
        )
        _run(env["session_id"])
        _, out2 = _run(env["session_id"])
        ctx2 = out2["hookSpecificOutput"]["additionalContext"]
        assert "once" not in ctx2

    def test_feedback_read_ledger_row_appended(self, tmp_path, monkeypatch):
        env = _stage(
            tmp_path, monkeypatch, mode="synthesis", phase="cross_examination",
            files={"feedback.json": {"notes": "fb"}},
        )
        _run(env["session_id"])
        rows = _ledger.read_events(env["session_id"], "claude")
        hits = [r for r in rows if r["verb"] == "feedback_read"]
        assert hits and hits[-1]["outcome"] == "allow"


class TestLockedFieldsReminder:
    def test_reminder_always_present(self, tmp_path, monkeypatch):
        # No inbox files → nothing to inject, but locked-field reminder
        # still lands so the agent sees its identity on every turn.
        env = _stage(tmp_path, monkeypatch, mode="synthesis", files={})
        _, out = _run(env["session_id"])
        ctx = out["hookSpecificOutput"]["additionalContext"]
        assert "Identity:" in ctx
        assert "agent=claude" in ctx
        assert "round=" in ctx

    def test_reminder_shows_remaining_counters(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch, mode="synthesis", files={})
        # Seed three prior allowed submissions.
        for _ in range(3):
            _ledger.append_hook_event(env["session_id"], "claude", "submit_code", "allow")
        _, out = _run(env["session_id"])
        ctx = out["hookSpecificOutput"]["additionalContext"]
        # submissions_remaining = MAX(5) - 3 = 2
        assert "submissions=2/5" in ctx


class TestMalformedInputs:
    def test_malformed_stdin_fails_open(self, tmp_path, monkeypatch):
        _stage(
            tmp_path, monkeypatch, mode="synthesis",
            files={"task.json": {"task_id": "T"}},
        )
        stdout = io.StringIO()
        rc = user_prompt_submit.main(io.StringIO("{not json"), stdout)
        assert rc == 0
        out = json.loads(stdout.getvalue())
        assert out["decision"] == "allow"

    def test_corrupt_task_json_is_skipped_silently(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch, mode="synthesis", files={})
        (env["workdir"] / "inbox" / "task.json").write_text("{not json")
        _, out = _run(env["session_id"])
        ctx = out["hookSpecificOutput"]["additionalContext"]
        # No TASK section since JSON parse failed, but Identity still there.
        assert "TASK" not in ctx
        assert "Identity:" in ctx

    def test_missing_inbox_file_is_skipped_silently(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch, mode="synthesis", files={})
        _, out = _run(env["session_id"])
        assert out["decision"] == "allow"
