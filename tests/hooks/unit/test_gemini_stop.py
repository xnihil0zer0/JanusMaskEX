"""Unit tests for harness.hooks.gemini.stop (HOOK-34 / P3).

Gate 3 partner: the full dotted path harness.hooks.gemini.stop is
imported below so the post-write gate recognises this file as the test
partner for the new module.
"""

from __future__ import annotations

import io
import json

import pytest

import harness.hooks.gemini.stop as stop
from harness.hooks import _ledger
from harness.hooks.gemini import stop as stop_mod


def _stage(tmp_path, monkeypatch, *, mode="synthesis"):
    state = tmp_path / "state"
    state.mkdir()
    workdir = state / "workdirs" / "gemini" / "sess"
    (workdir / "outbox").mkdir(parents=True)
    (state / "STATE.json").write_text(
        json.dumps({"round": 1, "phase": mode, "task_id": "T"})
    )
    monkeypatch.setenv("JANUSMASK_STATE_DIR", str(state))
    monkeypatch.setenv("JANUSMASK_WORK_DIR", str(workdir))
    monkeypatch.setenv("JANUSMASK_AGENT", "gemini")
    monkeypatch.setenv("JANUSMASK_MODE", mode)
    return {"state": state, "workdir": workdir, "session_id": "sess"}


def _run(*, stop_hook_active=False, session_id="sess"):
    stdin = io.StringIO(
        json.dumps(
            {
                "hook_event_name": "SessionEnd",
                "session_id": session_id,
                "stop_hook_active": stop_hook_active,
            }
        )
    )
    stdout = io.StringIO()
    stop.main(stdin, stdout)
    return json.loads(stdout.getvalue())


class TestSynthesisBlockMissingSubmission:
    def test_no_submission_blocks(self, tmp_path, monkeypatch):
        _stage(tmp_path, monkeypatch, mode="synthesis")
        out = _run()
        assert out["decision"] == "deny"
        assert "submit" in out["reason"].lower()

    def test_with_submission_allows(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch, mode="synthesis")
        _ledger.append_hook_event(
            env["session_id"], "gemini", "submit_code", "allow"
        )
        out = _run()
        assert out["decision"] == "allow"

    def test_stop_hook_active_always_allows(self, tmp_path, monkeypatch):
        _stage(tmp_path, monkeypatch, mode="synthesis")
        out = _run(stop_hook_active=True)
        assert out["decision"] == "allow"


class TestPlanningStopGate:
    def test_no_plan_draft_blocks(self, tmp_path, monkeypatch):
        _stage(tmp_path, monkeypatch, mode="planning")
        out = _run()
        assert out["decision"] == "deny"
        assert "plan_draft" in out["reason"]

    def test_with_plan_draft_allows(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch, mode="planning")
        _ledger.append_hook_event(
            env["session_id"], "gemini", "plan_draft", "allow"
        )
        out = _run()
        assert out["decision"] == "allow"


class TestReconciliationStopGate:
    def test_no_reconciliation_blocks(self, tmp_path, monkeypatch):
        _stage(tmp_path, monkeypatch, mode="reconciliation")
        out = _run()
        assert out["decision"] == "deny"

    def test_with_reconciliation_allows(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch, mode="reconciliation")
        _ledger.append_hook_event(
            env["session_id"], "gemini", "reconciliation", "allow"
        )
        out = _run()
        assert out["decision"] == "allow"


class TestSessionEndRowAppended:
    def test_allow_appends_session_end_row(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch, mode="synthesis")
        _ledger.append_hook_event(
            env["session_id"], "gemini", "submit_code", "allow"
        )
        _run()
        rows = _ledger.read_events(env["session_id"], "gemini")
        assert any(
            r["verb"] == "session_end" and r["outcome"] == "allow"
            for r in rows
        )

    def test_block_appends_deny_row(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch, mode="synthesis")
        _run()
        rows = _ledger.read_events(env["session_id"], "gemini")
        assert any(
            r["verb"] == "session_end" and r["outcome"] == "deny"
            for r in rows
        )


class TestMalformedStdin:
    def test_garbage_stdin_defaults_to_allow(self, tmp_path, monkeypatch):
        _stage(tmp_path, monkeypatch, mode="synthesis")
        stdout = io.StringIO()
        rc = stop.main(io.StringIO("{garbage"), stdout)
        assert rc == 0
        out = json.loads(stdout.getvalue())
        assert out["decision"] == "allow"
