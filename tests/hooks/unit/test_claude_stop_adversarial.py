"""Adversarial battery for HOOK-24-claude-stop (Phase 2).

Targets the P2 matrix "Worker issues Stop with no submission" case
and the stop-loop prevention invariant (stop_hook_active must be
honoured so we never wedge the agent in a block loop).
"""

from __future__ import annotations

import io
import json

import pytest

import harness.hooks.claude.stop as stop
from harness.hooks import _ledger


def _stage(tmp_path, monkeypatch, *, mode="synthesis"):
    state = tmp_path / "state"
    state.mkdir()
    workdir = state / "workdirs" / "claude" / "sess-adv"
    (workdir / "outbox").mkdir(parents=True)
    (state / "STATE.json").write_text(
        json.dumps({"round": 1, "phase": mode, "task_id": "T"})
    )
    monkeypatch.setenv("JANUSMASK_STATE_DIR", str(state))
    monkeypatch.setenv("JANUSMASK_WORK_DIR", str(workdir))
    monkeypatch.setenv("JANUSMASK_AGENT", "claude")
    monkeypatch.setenv("JANUSMASK_MODE", mode)
    return {"state": state, "workdir": workdir, "session_id": "sess-adv"}


def _run(*, stop_hook_active=False, session_id="sess-adv"):
    stdin = io.StringIO(json.dumps({
        "hook_event_name": "Stop",
        "session_id": session_id,
        "stop_hook_active": stop_hook_active,
    }))
    stdout = io.StringIO()
    stop.main(stdin, stdout)
    return json.loads(stdout.getvalue())


class TestStopLoopPrevention:
    def test_second_stop_with_flag_always_allows(self, tmp_path, monkeypatch):
        """First Stop blocks, second Stop with stop_hook_active=true
        must allow so the agent can always terminate even when the
        gate logic has a bug."""
        _stage(tmp_path, monkeypatch, mode="synthesis")
        first = _run(stop_hook_active=False)
        assert first["decision"] == "deny"
        second = _run(stop_hook_active=True)
        assert second["decision"] == "allow"


class TestForgedSessionId:
    def test_forged_session_cannot_reuse_victim_submissions(
        self, tmp_path, monkeypatch
    ):
        """Attacker lies about session_id to try to leverage a
        different session's accepted submissions. Each session's
        counter must be isolated."""
        _stage(tmp_path, monkeypatch, mode="synthesis")
        # Victim session has 1 accepted submission.
        _ledger.append_hook_event("sess-victim", "claude", "submit_code", "allow")
        # Attacker uses a forged session id — no accepted submission
        # of their own → must still block.
        out = _run(session_id="sess-attacker")
        assert out["decision"] == "deny"


class TestRejectedSubmissionsDoNotCount:
    def test_deny_only_submissions_still_block(self, tmp_path, monkeypatch):
        """Agent sent five AST-denied submissions — none accepted.
        Stop must still block because submissions_count(outcome=allow)
        is 0."""
        env = _stage(tmp_path, monkeypatch, mode="synthesis")
        for _ in range(5):
            _ledger.append_hook_event(
                env["session_id"], "claude", "submit_code", "deny"
            )
        out = _run()
        assert out["decision"] == "deny"


class TestRateLimitedAlsoBlocks:
    def test_rate_limited_with_zero_accepted_still_blocks(
        self, tmp_path, monkeypatch
    ):
        """A worker that hit rate limit without ever landing an accept
        row should still block — otherwise it exits the round with no
        submission file, leaving orchestrator's poll_for_submission to
        time out."""
        env = _stage(tmp_path, monkeypatch, mode="synthesis")
        for _ in range(5):
            _ledger.append_hook_event(
                env["session_id"], "claude", "submit_code", "rate_limited"
            )
        out = _run()
        assert out["decision"] == "deny"
