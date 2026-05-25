"""Adversarial battery for HOOK-34-gemini-stop (Phase 3).

Mirrors the Claude stop battery: the must-submit invariant must
survive forged session ids, phase flips, and the escape-hatch loop
while always appending a terminal ``session_end`` ledger row.
"""

from __future__ import annotations

import io
import json

import pytest

import harness.hooks.gemini.stop as stop
from harness.hooks import _ledger


def _stage(tmp_path, monkeypatch, *, mode="synthesis"):
    state = tmp_path / "state"
    state.mkdir()
    workdir = state / "workdirs" / "gemini" / "advS"
    (workdir / "outbox").mkdir(parents=True)
    (state / "STATE.json").write_text(
        json.dumps({"round": 1, "phase": mode, "task_id": "T"})
    )
    monkeypatch.setenv("JANUSMASK_STATE_DIR", str(state))
    monkeypatch.setenv("JANUSMASK_WORK_DIR", str(workdir))
    monkeypatch.setenv("JANUSMASK_AGENT", "gemini")
    monkeypatch.setenv("JANUSMASK_MODE", mode)
    return {"state": state, "workdir": workdir, "session_id": "advS"}


def _run(*, stop_hook_active=False, sid="advS"):
    stdin = io.StringIO(
        json.dumps(
            {
                "hook_event_name": "SessionEnd",
                "session_id": sid,
                "stop_hook_active": stop_hook_active,
            }
        )
    )
    stdout = io.StringIO()
    stop.main(stdin, stdout)
    return json.loads(stdout.getvalue())


class TestForgedSessionId:
    def test_forged_id_cannot_satisfy_victim_requirement(
        self, tmp_path, monkeypatch
    ):
        env = _stage(tmp_path, monkeypatch, mode="synthesis")
        # Victim session has a submission; attacker tries to exit under
        # a different session id and must still be blocked.
        _ledger.append_hook_event(
            env["session_id"], "gemini", "submit_code", "allow"
        )
        out = _run(sid="attacker")
        assert out["decision"] == "deny"


class TestEscapeHatchLoop:
    def test_second_stop_with_active_flag_unblocks(
        self, tmp_path, monkeypatch
    ):
        _stage(tmp_path, monkeypatch, mode="synthesis")
        # First attempt is blocked.
        first = _run()
        assert first["decision"] == "deny"
        # Second attempt carries stop_hook_active=true; the hook honours.
        second = _run(stop_hook_active=True)
        assert second["decision"] == "allow"


class TestPhaseFlipMidSession:
    def test_flip_to_synthesis_mid_session_resets_expectations(
        self, tmp_path, monkeypatch
    ):
        # Worker started in planning, submitted a plan_draft, then
        # STATE.json flipped to synthesis for the next round. A Stop
        # now must re-block because no submit_code has happened yet.
        env = _stage(tmp_path, monkeypatch, mode="planning")
        _ledger.append_hook_event(
            env["session_id"], "gemini", "plan_draft", "allow"
        )
        # Flip both env and STATE.
        monkeypatch.setenv("JANUSMASK_MODE", "synthesis")
        (env["state"] / "STATE.json").write_text(
            json.dumps({"round": 2, "phase": "synthesis", "task_id": "T"})
        )
        out = _run()
        assert out["decision"] == "deny"


class TestAlwaysAppendsSessionEndRow:
    def test_deny_appends_row_with_reason(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch, mode="synthesis")
        _run()
        rows = _ledger.read_events(env["session_id"], "gemini")
        denies = [r for r in rows if r["verb"] == "session_end"]
        assert denies[-1]["outcome"] == "deny"
        assert denies[-1]["detail"]["reason"]


class TestDecisionVocab:
    def test_never_emits_block_token(self, tmp_path, monkeypatch):
        _stage(tmp_path, monkeypatch, mode="synthesis")
        out = _run()
        assert out["decision"] in ("allow", "deny")
        assert out["decision"] != "block"
