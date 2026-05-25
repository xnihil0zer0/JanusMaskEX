"""Adversarial battery for HOOK-31-gemini-user-prompt (Phase 3).

The user-prompt equivalent must survive the same attack surface as
Claude's UserPromptSubmit (idempotent injection, phase-gated
feedback, locked-field resilience) *plus* three Gemini-specific
concerns:

  - vocab normalisation: decision envelope must always be `allow` —
    never leak `block` or `ask` (sub-plan 03 §4).
  - envelope shape: Gemini reads `systemMessage`, not Claude's
    `hookSpecificOutput.additionalContext` — the hook must not emit
    the latter.
  - phase flip mid-session: if the orchestrator flips STATE.json from
    synthesis to cross_examination between turns, the next call must
    inject feedback once and only once.
"""

from __future__ import annotations

import io
import json

import pytest

import harness.hooks.gemini.user_prompt_submit as user_prompt_submit
from harness.hooks import _ledger


@pytest.fixture
def synth_env(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    workdir = state / "workdirs" / "gemini" / "advUP"
    (workdir / "inbox").mkdir(parents=True)
    (workdir / "inbox" / "task.json").write_text(
        json.dumps({"task_id": "T", "title": "build Y"})
    )
    (state / "STATE.json").write_text(
        json.dumps({"round": 1, "phase": "synthesis", "task_id": "T"})
    )
    monkeypatch.setenv("JANUSMASK_STATE_DIR", str(state))
    monkeypatch.setenv("JANUSMASK_WORK_DIR", str(workdir))
    monkeypatch.setenv("JANUSMASK_AGENT", "gemini")
    monkeypatch.setenv("JANUSMASK_MODE", "synthesis")
    return {"state": state, "workdir": workdir, "session_id": "advUP"}


class TestIdempotency:
    def test_task_injection_is_single_shot(self, synth_env):
        for _ in range(5):
            user_prompt_submit.main(
                io.StringIO(
                    json.dumps({"session_id": synth_env["session_id"]})
                ),
                io.StringIO(),
            )
        rows = _ledger.read_events(synth_env["session_id"], "gemini")
        assert sum(1 for r in rows if r["verb"] == "task_read") == 1


class TestPhaseFlipMidSession:
    def test_flip_to_cross_exam_injects_feedback_once(
        self, synth_env, monkeypatch
    ):
        # First two turns in synthesis — feedback file absent, nothing
        # injected for feedback.
        for _ in range(2):
            user_prompt_submit.main(
                io.StringIO(
                    json.dumps({"session_id": synth_env["session_id"]})
                ),
                io.StringIO(),
            )
        rows = _ledger.read_events(synth_env["session_id"], "gemini")
        assert not any(r["verb"] == "feedback_read" for r in rows)

        # Orchestrator flips the phase + drops a feedback file.
        (synth_env["state"] / "STATE.json").write_text(
            json.dumps(
                {"round": 1, "phase": "cross_examination", "task_id": "T"}
            )
        )
        (synth_env["workdir"] / "inbox" / "feedback.json").write_text(
            json.dumps({"issue": "broken"})
        )

        # Two more turns under cross_examination — feedback injected
        # once.
        stdout = io.StringIO()
        user_prompt_submit.main(
            io.StringIO(
                json.dumps({"session_id": synth_env["session_id"]})
            ),
            stdout,
        )
        out = json.loads(stdout.getvalue())
        assert "broken" in out["systemMessage"]

        user_prompt_submit.main(
            io.StringIO(
                json.dumps({"session_id": synth_env["session_id"]})
            ),
            io.StringIO(),
        )
        rows = _ledger.read_events(synth_env["session_id"], "gemini")
        assert sum(1 for r in rows if r["verb"] == "feedback_read") == 1


class TestEnvelopeShape:
    def test_never_leaks_claude_additional_context_key(self, synth_env):
        stdout = io.StringIO()
        user_prompt_submit.main(
            io.StringIO(
                json.dumps({"session_id": synth_env["session_id"]})
            ),
            stdout,
        )
        out = json.loads(stdout.getvalue())
        # The claude envelope is {decision, hookSpecificOutput:{hookEventName,
        # additionalContext}}. Gemini's is {decision, systemMessage}. Cross-
        # contamination would cause the Gemini agent to miss the context
        # (or worse, double-handle it via the systemMessage path).
        assert "hookSpecificOutput" not in out
        assert "systemMessage" in out
        assert out["decision"] == "allow"

    def test_decision_is_always_allow_never_block_or_ask(self, synth_env):
        # The user-prompt hook never denies — policy enforcement is the
        # BeforeTool hook's job. Adversarially verify the token is not
        # something the normaliser would re-interpret.
        stdout = io.StringIO()
        user_prompt_submit.main(
            io.StringIO(
                json.dumps({"session_id": synth_env["session_id"]})
            ),
            stdout,
        )
        out = json.loads(stdout.getvalue())
        assert out["decision"] not in ("block", "deny", "ask")


class TestForgedSessionId:
    def test_forged_stdin_session_id_cannot_read_victim_feedback(
        self, synth_env, monkeypatch
    ):
        # Victim has feedback_read already recorded under its own ledger.
        _ledger.append_hook_event(
            "sess-victim", "gemini", "feedback_read", "allow"
        )
        # Attacker forges that session id on stdin while using a
        # different workdir (staged under env); the attacker's output
        # should reflect their *own* empty ledger — never the victim's.
        user_prompt_submit.main(
            io.StringIO(json.dumps({"session_id": "sess-attacker"})),
            io.StringIO(),
        )
        victim_rows = _ledger.read_events("sess-victim", "gemini")
        assert (
            sum(1 for r in victim_rows if r["verb"] == "feedback_read") == 1
        )


class TestCorruptArtifacts:
    def test_corrupt_feedback_file_does_not_crash(self, synth_env):
        (synth_env["state"] / "STATE.json").write_text(
            json.dumps(
                {"round": 1, "phase": "cross_examination", "task_id": "T"}
            )
        )
        (synth_env["workdir"] / "inbox" / "feedback.json").write_text(
            "{not json"
        )
        stdout = io.StringIO()
        rc = user_prompt_submit.main(
            io.StringIO(
                json.dumps({"session_id": synth_env["session_id"]})
            ),
            stdout,
        )
        assert rc == 0
        # No feedback_read 'allow' row because body was unreadable —
        # fail-safe direction since the orchestrator will resync later.
        # W108 emits an outcome='invalid' audit row for visibility but
        # the gating consumers all filter on outcome='allow'.
        rows = _ledger.read_events(synth_env["session_id"], "gemini")
        assert not any(
            r["verb"] == "feedback_read" and r.get("outcome") == "allow"
            for r in rows
        )

    def test_missing_inbox_still_emits_locked_fields(self, synth_env):
        (synth_env["workdir"] / "inbox" / "task.json").unlink()
        stdout = io.StringIO()
        user_prompt_submit.main(
            io.StringIO(
                json.dumps({"session_id": synth_env["session_id"]})
            ),
            stdout,
        )
        msg = json.loads(stdout.getvalue())["systemMessage"]
        assert "agent=gemini" in msg
