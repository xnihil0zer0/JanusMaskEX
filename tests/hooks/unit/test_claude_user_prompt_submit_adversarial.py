"""Adversarial battery for HOOK-21-claude-user-prompt-submit (Phase 2).

Targets the invariants preserved from mcp_server (sub-plan 04 §4):
phase-gate on get_feedback, session-id forge resistance on the
task_read marker, feedback freshness, and robustness against
malformed inbox payloads.
"""

from __future__ import annotations

import io
import json

import pytest

import harness.hooks.claude.user_prompt_submit as user_prompt_submit
from harness.hooks import _ledger


def _stage(tmp_path, monkeypatch, *, mode, phase=None, files=None):
    state = tmp_path / "state"
    state.mkdir(exist_ok=True)
    workdir = state / "workdirs" / "claude" / "sess-adv"
    (workdir / "inbox").mkdir(parents=True, exist_ok=True)
    for name, body in (files or {}).items():
        (workdir / "inbox" / name).write_text(json.dumps(body))
    (state / "STATE.json").write_text(
        json.dumps({"round": 1, "phase": phase or mode})
    )
    monkeypatch.setenv("JANUSMASK_STATE_DIR", str(state))
    monkeypatch.setenv("JANUSMASK_WORK_DIR", str(workdir))
    monkeypatch.setenv("JANUSMASK_AGENT", "claude")
    monkeypatch.setenv("JANUSMASK_MODE", mode)
    return {"state": state, "workdir": workdir, "session_id": "sess-adv"}


def _run(session_id: str):
    stdin = io.StringIO(
        json.dumps({"hook_event_name": "UserPromptSubmit", "session_id": session_id})
    )
    stdout = io.StringIO()
    user_prompt_submit.main(stdin, stdout)
    return json.loads(stdout.getvalue())


class TestPhaseGateOnFeedback:
    """Feedback must never leak into synthesis — mcp_server.cmd_get_feedback
    enforced `phase == cross_examination`; the hook must too."""

    def test_feedback_not_leaked_in_synthesis(self, tmp_path, monkeypatch):
        env = _stage(
            tmp_path, monkeypatch, mode="synthesis", phase="synthesis",
            files={"feedback.json": {"secret": "do not leak"}},
        )
        out = _run(env["session_id"])
        ctx = out["hookSpecificOutput"]["additionalContext"]
        assert "do not leak" not in ctx

    def test_feedback_not_leaked_in_planning(self, tmp_path, monkeypatch):
        env = _stage(
            tmp_path, monkeypatch, mode="planning", phase="planning",
            files={"feedback.json": {"secret": "nope"}},
        )
        out = _run(env["session_id"])
        ctx = out["hookSpecificOutput"]["additionalContext"]
        assert "nope" not in ctx

    def test_phase_flip_to_cross_exam_allows_injection(self, tmp_path, monkeypatch):
        env = _stage(
            tmp_path, monkeypatch, mode="synthesis", phase="cross_examination",
            files={"feedback.json": {"notes": "now visible"}},
        )
        out = _run(env["session_id"])
        ctx = out["hookSpecificOutput"]["additionalContext"]
        assert "now visible" in ctx


class TestForgedSessionId:
    def test_forged_session_does_not_set_victim_task_read(
        self, tmp_path, monkeypatch
    ):
        # Seed victim with a task_read row — they've already seen their task.
        _stage(tmp_path, monkeypatch, mode="synthesis",
               files={"task.json": {"task_id": "T-victim"}})
        _ledger.append_hook_event("sess-victim", "claude", "task_read", "allow")
        # Attacker runs the hook with a forged session id; this must not
        # bleed into the victim's ledger.
        out = _run("sess-attacker")
        # Attacker gets their task (first time) — inbox shared via workdir.
        assert "T-victim" in out["hookSpecificOutput"]["additionalContext"]
        victim_rows = _ledger.read_events("sess-victim", "claude")
        attacker_rows = _ledger.read_events("sess-attacker", "claude")
        assert sum(1 for r in victim_rows if r["verb"] == "task_read") == 1
        assert any(r["verb"] == "task_read" for r in attacker_rows)


class TestCorruptInbox:
    def test_corrupt_feedback_does_not_crash(self, tmp_path, monkeypatch):
        env = _stage(
            tmp_path, monkeypatch, mode="synthesis", phase="cross_examination",
            files={},
        )
        (env["workdir"] / "inbox" / "feedback.json").write_text("{not json")
        out = _run(env["session_id"])
        assert out["decision"] == "allow"
        # Corrupt file silently skipped, no feedback section.
        assert "FEEDBACK" not in out["hookSpecificOutput"]["additionalContext"]

    def test_corrupt_brief_does_not_crash(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch, mode="planning", files={})
        (env["workdir"] / "inbox" / "brief.json").write_text("}{garbage")
        out = _run(env["session_id"])
        assert out["decision"] == "allow"


class TestIdempotency:
    def test_task_read_injected_exactly_once_per_session(
        self, tmp_path, monkeypatch
    ):
        env = _stage(
            tmp_path, monkeypatch, mode="synthesis",
            files={"task.json": {"task_id": "T", "specification": "do"}},
        )
        ctxs = []
        for _ in range(4):
            out = _run(env["session_id"])
            ctxs.append(out["hookSpecificOutput"]["additionalContext"])
        # Only the first turn has the TASK section body.
        assert sum(1 for c in ctxs if "specification" in c) == 1

    def test_feedback_injected_exactly_once_per_session(
        self, tmp_path, monkeypatch
    ):
        env = _stage(
            tmp_path, monkeypatch, mode="synthesis", phase="cross_examination",
            files={"feedback.json": {"notes": "fb-body"}},
        )
        ctxs = [_run(env["session_id"])["hookSpecificOutput"]["additionalContext"]
                for _ in range(3)]
        assert sum(1 for c in ctxs if "fb-body" in c) == 1


class TestMalformedStdin:
    def test_garbage_stdin_emits_valid_allow_envelope(self, tmp_path, monkeypatch):
        _stage(tmp_path, monkeypatch, mode="synthesis",
               files={"task.json": {"task_id": "T"}})
        stdout = io.StringIO()
        rc = user_prompt_submit.main(io.StringIO("!!!nonjson"), stdout)
        assert rc == 0
        out = json.loads(stdout.getvalue())
        assert out["decision"] == "allow"
