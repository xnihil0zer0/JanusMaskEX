"""Unit tests for harness.hooks.claude.pre_compact (HOOK-25 / P2).

Gate 3 partner: imports the full dotted path
harness.hooks.claude.pre_compact so the post-write gate recognises
this file as the test partner for the new module.
"""

from __future__ import annotations

import io
import json

import pytest

import harness.hooks.claude.pre_compact as pre_compact
from harness.hooks import _ledger
from harness.hooks.claude import pre_compact as pc_mod


def _stage(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv("JANUSMASK_STATE_DIR", str(state))
    monkeypatch.setenv("JANUSMASK_AGENT", "claude")
    monkeypatch.setenv("JANUSMASK_MODE", "synthesis")
    return {"state": state, "session_id": "sess"}


def _run(trigger="auto", session_id="sess"):
    stdin = io.StringIO(json.dumps({
        "hook_event_name": "PreCompact",
        "session_id": session_id,
        "trigger": trigger,
    }))
    stdout = io.StringIO()
    pre_compact.main(stdin, stdout)
    return json.loads(stdout.getvalue())


class TestMain:
    def test_emits_continue_true(self, tmp_path, monkeypatch):
        _stage(tmp_path, monkeypatch)
        out = _run()
        assert out["continue"] is True
        assert out["hookSpecificOutput"]["hookEventName"] == "PreCompact"

    def test_appends_pre_compact_ledger_row(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch)
        _run(trigger="manual")
        rows = _ledger.read_events(env["session_id"], "claude")
        hits = [r for r in rows if r["verb"] == "pre_compact"]
        assert hits
        assert hits[-1]["detail"]["trigger"] == "manual"

    def test_malformed_stdin_fails_open(self, tmp_path, monkeypatch):
        _stage(tmp_path, monkeypatch)
        stdout = io.StringIO()
        rc = pre_compact.main(io.StringIO("{garbage"), stdout)
        assert rc == 0
        assert json.loads(stdout.getvalue())["continue"] is True
