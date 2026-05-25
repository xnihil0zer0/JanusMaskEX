"""Unit tests for harness.hooks.gemini.user_prompt_submit (HOOK-31 / P3).

Gate 3 partner for harness.hooks.gemini.user_prompt_submit: the full dotted
path is imported so the post-write gate recognises this file as its
test partner.
"""

from __future__ import annotations

import io
import json

import pytest

import harness.hooks.gemini.user_prompt_submit as user_prompt_submit
from harness.hooks import _ledger
from harness.hooks.gemini import user_prompt_submit as up_mod


@pytest.fixture
def synth_workdir(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    workdir = state / "workdirs" / "gemini" / "sessUP"
    (workdir / "inbox").mkdir(parents=True)
    task_body = {"task_id": "T", "title": "do it", "constraints": {"deterministic": True}}
    (workdir / "inbox" / "task.json").write_text(json.dumps(task_body))
    (state / "STATE.json").write_text(
        json.dumps({"round": 2, "phase": "synthesis", "task_id": "T"})
    )
    monkeypatch.setenv("JANUSMASK_STATE_DIR", str(state))
    monkeypatch.setenv("JANUSMASK_WORK_DIR", str(workdir))
    monkeypatch.setenv("JANUSMASK_AGENT", "gemini")
    monkeypatch.setenv("JANUSMASK_MODE", "synthesis")
    monkeypatch.setenv("JANUSMASK_ROUND", "2")
    return {
        "state": state,
        "workdir": workdir,
        "session_id": "sessUP",
        "task": task_body,
    }


@pytest.fixture
def planning_workdir(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    workdir = state / "workdirs" / "gemini" / "sessPL"
    (workdir / "inbox").mkdir(parents=True)
    (workdir / "inbox" / "brief.json").write_text(json.dumps({"title": "plan"}))
    (state / "STATE.json").write_text(json.dumps({"round": 1, "phase": "planning"}))
    monkeypatch.setenv("JANUSMASK_STATE_DIR", str(state))
    monkeypatch.setenv("JANUSMASK_WORK_DIR", str(workdir))
    monkeypatch.setenv("JANUSMASK_AGENT", "gemini")
    monkeypatch.setenv("JANUSMASK_MODE", "planning")
    return {"state": state, "workdir": workdir, "session_id": "sessPL"}


@pytest.fixture
def reconciliation_workdir(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    workdir = state / "workdirs" / "gemini" / "sessRC"
    (workdir / "inbox").mkdir(parents=True)
    diff = {"diffs": [{"id": "d1"}, {"id": "d2"}]}
    (workdir / "inbox" / "diff_summary.json").write_text(json.dumps(diff))
    (workdir / "inbox" / "brief.json").write_text(json.dumps({"title": "brief"}))
    (state / "STATE.json").write_text(
        json.dumps({"round": 3, "phase": "reconciliation"})
    )
    monkeypatch.setenv("JANUSMASK_STATE_DIR", str(state))
    monkeypatch.setenv("JANUSMASK_WORK_DIR", str(workdir))
    monkeypatch.setenv("JANUSMASK_AGENT", "gemini")
    monkeypatch.setenv("JANUSMASK_MODE", "reconciliation")
    return {
        "state": state,
        "workdir": workdir,
        "session_id": "sessRC",
        "diff": diff,
    }


class TestBuildLockedFieldsReminder:
    def test_contains_identity_and_budget(self):
        txt = user_prompt_submit.build_locked_fields_reminder(
            agent="gemini",
            session_id="s",
            round_number=4,
            phase="synthesis",
            submissions_remaining=3,
            clarifications_remaining=1,
        )
        assert "agent=gemini" in txt
        assert "round=4" in txt
        assert "phase=synthesis" in txt
        assert "session=s" in txt
        assert "3/5" in txt
        assert "1/2" in txt


class TestFirstTurnInjection:
    def test_synthesis_injects_task_once(self, synth_workdir):
        stdin = io.StringIO(
            json.dumps({"session_id": synth_workdir["session_id"]})
        )
        stdout = io.StringIO()
        rc = user_prompt_submit.main(stdin, stdout)
        assert rc == 0
        out = json.loads(stdout.getvalue())
        assert out["decision"] == "allow"
        msg = out["systemMessage"]
        assert "TASK" in msg.upper()
        assert "do it" in msg

        rows = _ledger.read_events(synth_workdir["session_id"], "gemini")
        reads = [r for r in rows if r["verb"] == "task_read"]
        assert len(reads) == 1
        assert reads[0]["outcome"] == "allow"

    def test_subsequent_turn_does_not_reinject(self, synth_workdir):
        # First turn injects.
        user_prompt_submit.main(
            io.StringIO(
                json.dumps({"session_id": synth_workdir["session_id"]})
            ),
            io.StringIO(),
        )
        # Second turn: ledger shows task_read already allowed, so no new row.
        stdout2 = io.StringIO()
        user_prompt_submit.main(
            io.StringIO(
                json.dumps({"session_id": synth_workdir["session_id"]})
            ),
            stdout2,
        )
        out = json.loads(stdout2.getvalue())
        msg = out["systemMessage"]
        # Locked-field reminder still present; task body should not re-appear.
        assert "do it" not in msg
        assert "agent=gemini" in msg

        rows = _ledger.read_events(synth_workdir["session_id"], "gemini")
        assert len([r for r in rows if r["verb"] == "task_read"]) == 1

    def test_planning_mode_injects_brief(self, planning_workdir):
        stdout = io.StringIO()
        user_prompt_submit.main(
            io.StringIO(
                json.dumps({"session_id": planning_workdir["session_id"]})
            ),
            stdout,
        )
        out = json.loads(stdout.getvalue())
        msg = out["systemMessage"]
        assert "BRIEF" in msg.upper()
        assert "plan" in msg

    def test_reconciliation_prefers_diff_summary_over_brief(
        self, reconciliation_workdir
    ):
        stdout = io.StringIO()
        user_prompt_submit.main(
            io.StringIO(
                json.dumps({"session_id": reconciliation_workdir["session_id"]})
            ),
            stdout,
        )
        out = json.loads(stdout.getvalue())
        msg = out["systemMessage"]
        assert "DIFF_SUMMARY" in msg.upper()
        assert "d1" in msg


class TestFeedbackInjection:
    def test_cross_examination_phase_injects_feedback_once(
        self, synth_workdir, monkeypatch
    ):
        # Flip to cross_examination phase with a feedback file.
        (synth_workdir["state"] / "STATE.json").write_text(
            json.dumps(
                {"round": 2, "phase": "cross_examination", "task_id": "T"}
            )
        )
        fb_body = {"round_1_issues": ["concern-A"]}
        (synth_workdir["workdir"] / "inbox" / "feedback.json").write_text(
            json.dumps(fb_body)
        )
        stdout = io.StringIO()
        user_prompt_submit.main(
            io.StringIO(
                json.dumps({"session_id": synth_workdir["session_id"]})
            ),
            stdout,
        )
        msg = json.loads(stdout.getvalue())["systemMessage"]
        assert "FEEDBACK" in msg.upper()
        assert "concern-A" in msg

        rows = _ledger.read_events(synth_workdir["session_id"], "gemini")
        feedback_rows = [r for r in rows if r["verb"] == "feedback_read"]
        assert len(feedback_rows) == 1

    def test_feedback_only_once_across_prompts(
        self, synth_workdir, monkeypatch
    ):
        (synth_workdir["state"] / "STATE.json").write_text(
            json.dumps(
                {"round": 2, "phase": "cross_examination", "task_id": "T"}
            )
        )
        (synth_workdir["workdir"] / "inbox" / "feedback.json").write_text(
            json.dumps({"x": 1})
        )
        user_prompt_submit.main(
            io.StringIO(
                json.dumps({"session_id": synth_workdir["session_id"]})
            ),
            io.StringIO(),
        )
        user_prompt_submit.main(
            io.StringIO(
                json.dumps({"session_id": synth_workdir["session_id"]})
            ),
            io.StringIO(),
        )
        rows = _ledger.read_events(synth_workdir["session_id"], "gemini")
        assert sum(1 for r in rows if r["verb"] == "feedback_read") == 1

    def test_non_cross_examination_skips_feedback(self, synth_workdir):
        (synth_workdir["workdir"] / "inbox" / "feedback.json").write_text(
            json.dumps({"x": 1})
        )
        stdout = io.StringIO()
        user_prompt_submit.main(
            io.StringIO(
                json.dumps({"session_id": synth_workdir["session_id"]})
            ),
            stdout,
        )
        msg = json.loads(stdout.getvalue())["systemMessage"]
        # Phase is synthesis, feedback must NOT be injected.
        assert "FEEDBACK" not in msg.upper()


class TestEnvelopeShape:
    def test_allow_envelope_uses_gemini_vocab(self, synth_workdir):
        stdout = io.StringIO()
        user_prompt_submit.main(
            io.StringIO(
                json.dumps({"session_id": synth_workdir["session_id"]})
            ),
            stdout,
        )
        out = json.loads(stdout.getvalue())
        assert out["decision"] == "allow"
        # Gemini uses systemMessage; we never leak Claude's
        # `hookSpecificOutput.additionalContext` on the Gemini side.
        assert "systemMessage" in out
        assert "hookSpecificOutput" not in out

    def test_locked_fields_reminder_always_present(self, synth_workdir):
        # Even if the task.json is absent, the reminder should be in the
        # output.
        (synth_workdir["workdir"] / "inbox" / "task.json").unlink()
        stdout = io.StringIO()
        user_prompt_submit.main(
            io.StringIO(
                json.dumps({"session_id": synth_workdir["session_id"]})
            ),
            stdout,
        )
        msg = json.loads(stdout.getvalue())["systemMessage"]
        assert "agent=gemini" in msg
        assert "round=2" in msg


class TestMalformedInputs:
    def test_empty_stdin_tolerated(self, synth_workdir):
        stdout = io.StringIO()
        rc = user_prompt_submit.main(io.StringIO(""), stdout)
        assert rc == 0
        out = json.loads(stdout.getvalue())
        assert out["decision"] == "allow"

    def test_non_json_stdin_emits_valid_envelope(self, synth_workdir):
        stdout = io.StringIO()
        rc = user_prompt_submit.main(io.StringIO("{broken"), stdout)
        assert rc == 0
        out = json.loads(stdout.getvalue())
        assert out["decision"] == "allow"

    def test_corrupt_task_json_skipped_not_crash(self, synth_workdir):
        (synth_workdir["workdir"] / "inbox" / "task.json").write_text("{broken")
        stdout = io.StringIO()
        rc = user_prompt_submit.main(
            io.StringIO(
                json.dumps({"session_id": synth_workdir["session_id"]})
            ),
            stdout,
        )
        assert rc == 0
        out = json.loads(stdout.getvalue())
        msg = out["systemMessage"]
        # Locked-field reminder still there; no task-read ledger row
        # since the body was unreadable.
        assert "agent=gemini" in msg
        rows = _ledger.read_events(synth_workdir["session_id"], "gemini")
        # W108: corrupt body emits an outcome='invalid' audit row but no
        # outcome='allow' row — gating semantics filter on 'allow' only.
        assert not any(
            r["verb"] == "task_read" and r.get("outcome") == "allow"
            for r in rows
        )
