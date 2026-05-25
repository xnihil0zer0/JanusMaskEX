"""Adversarial battery for HOOK-25-claude-pre-compact (Phase 2).

PreCompact is a no-op on the JanusMask side; these cases pin the
"never block compaction" guarantee and ledger isolation across
forged session ids.
"""

from __future__ import annotations

import io
import json

import pytest

import harness.hooks.claude.pre_compact as pre_compact
from harness.hooks import _ledger


def _stage(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv("JANUSMASK_STATE_DIR", str(state))
    monkeypatch.setenv("JANUSMASK_AGENT", "claude")
    monkeypatch.setenv("JANUSMASK_MODE", "synthesis")


def _run(*, trigger="auto", session_id="sess"):
    stdin = io.StringIO(json.dumps({
        "hook_event_name": "PreCompact",
        "session_id": session_id,
        "trigger": trigger,
    }))
    stdout = io.StringIO()
    pre_compact.main(stdin, stdout)
    return json.loads(stdout.getvalue())


class TestNeverBlocksCompaction:
    def test_empty_stdin_still_continues(self, tmp_path, monkeypatch):
        _stage(tmp_path, monkeypatch)
        stdout = io.StringIO()
        pre_compact.main(io.StringIO(""), stdout)
        out = json.loads(stdout.getvalue())
        assert out["continue"] is True

    def test_non_object_stdin_still_continues(self, tmp_path, monkeypatch):
        _stage(tmp_path, monkeypatch)
        stdout = io.StringIO()
        pre_compact.main(io.StringIO('"bad"'), stdout)
        out = json.loads(stdout.getvalue())
        assert out["continue"] is True


class TestLedgerIsolation:
    def test_forged_session_does_not_cross_pollute(self, tmp_path, monkeypatch):
        _stage(tmp_path, monkeypatch)
        _ledger.append_hook_event("sess-victim", "claude", "submit_code", "allow")
        _run(session_id="sess-attacker")
        vrows = _ledger.read_events("sess-victim", "claude")
        arows = _ledger.read_events("sess-attacker", "claude")
        # Victim ledger untouched.
        assert not any(r["verb"] == "pre_compact" for r in vrows)
        # Attacker row landed under their own file.
        assert any(r["verb"] == "pre_compact" for r in arows)
