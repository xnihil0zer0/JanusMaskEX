"""Unit tests for harness/hooks/ scaffold (HOOK-10-scaffold-common).

Covers: JSON envelope, decision vocabulary normalisation, path resolution,
session ledger append/read/count, and STATE.json gating helpers.

These tests are the test partner for harness.hooks._common, ._paths, ._ledger,
._state_gates per the hooks-augmented plan §3.2 gate 3.
"""

from __future__ import annotations

import io
import json
import os

import pytest

import harness.hooks._common
import harness.hooks._paths
import harness.hooks._ledger
import harness.hooks._state_gates
from harness.hooks import _common, _ledger, _paths, _state_gates


# ---------- _common ----------


class TestCommon:
    def test_read_input_parses_json_object(self):
        stream = io.StringIO(json.dumps({"tool_name": "Write", "foo": 1}))
        assert _common.read_input(stream) == {"tool_name": "Write", "foo": 1}

    def test_read_input_empty_returns_empty_dict(self):
        assert _common.read_input(io.StringIO("")) == {}
        assert _common.read_input(io.StringIO("   \n  ")) == {}

    def test_read_input_rejects_non_object(self):
        with pytest.raises(_common.HookInputError):
            _common.read_input(io.StringIO("[1,2,3]"))

    def test_read_input_rejects_malformed_json(self):
        with pytest.raises(_common.HookInputError):
            _common.read_input(io.StringIO("{not json"))

    def test_decision_allow(self):
        payload = _common.decision_payload("allow")
        assert payload == {"decision": "allow"}

    def test_decision_block_raises_value_error(self):
        # The block->deny normalizer was removed: PreToolUse vocabulary
        # is now strictly {allow, deny}. Passing "block" must raise.
        with pytest.raises(ValueError):
            _common.decision_payload("block", reason="bad")

    def test_decision_unknown_raises(self):
        with pytest.raises(ValueError):
            _common.decision_payload("maybe")

    def test_decision_carries_optional_fields(self):
        payload = _common.decision_payload(
            "allow",
            additional_context="hello",
            tool_input={"file_path": "/tmp/x"},
        )
        assert payload["additionalContext"] == "hello"
        assert payload["tool_input"] == {"file_path": "/tmp/x"}

    def test_write_decision_round_trip(self):
        buf = io.StringIO()
        _common.write_decision(_common.decision_payload("deny", reason="nope"), buf)
        assert json.loads(buf.getvalue()) == {"decision": "deny", "reason": "nope"}


# ---------- _paths ----------


class TestPaths:
    def test_project_dir_defaults_to_repo_root(self, monkeypatch):
        monkeypatch.delenv("JANUSMASK_PROJECT_DIR", raising=False)
        monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
        pd = _paths.project_dir()
        assert (pd / "harness" / "hooks" / "__init__.py").exists()

    def test_state_dir_honours_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("JANUSMASK_STATE_DIR", str(tmp_path))
        assert _paths.state_dir() == tmp_path.resolve()

    def test_round_env_wins_over_state(self, monkeypatch):
        monkeypatch.setenv("JANUSMASK_ROUND", "7")
        assert _paths.round_number() == 7

    def test_round_missing_returns_sentinel(self, monkeypatch):
        monkeypatch.delenv("JANUSMASK_ROUND", raising=False)
        assert _paths.round_number() == -1

    def test_round_invalid_returns_sentinel(self, monkeypatch):
        monkeypatch.setenv("JANUSMASK_ROUND", "not-a-number")
        assert _paths.round_number() == -1

    def test_safe_under_state_accepts_descendant(self, tmp_path, monkeypatch):
        monkeypatch.setenv("JANUSMASK_STATE_DIR", str(tmp_path))
        child = tmp_path / "sessions" / "x.json"
        child.parent.mkdir(parents=True)
        child.write_text("{}")
        assert _paths.safe_under_state(str(child))

    def test_safe_under_state_rejects_traversal(self, tmp_path, monkeypatch):
        monkeypatch.setenv("JANUSMASK_STATE_DIR", str(tmp_path))
        outside = tmp_path.parent / "escape.txt"
        assert not _paths.safe_under_state(str(outside))


# ---------- _ledger ----------


class TestLedger:
    def test_ledger_path_shape(self, tmp_path, monkeypatch):
        monkeypatch.setenv("JANUSMASK_STATE_DIR", str(tmp_path))
        p = _ledger.ledger_path("abc123", agent="claude")
        assert p == tmp_path / "sessions" / "claude_abc123.ledger.jsonl"

    def test_append_and_read_round_trip(self, tmp_path, monkeypatch):
        monkeypatch.setenv("JANUSMASK_STATE_DIR", str(tmp_path))
        monkeypatch.setenv("JANUSMASK_AGENT", "claude")
        _ledger.append_hook_event("sess1", "claude", "submit_code", "allow", round_number=1)
        _ledger.append_hook_event("sess1", "claude", "submit_code", "deny", round_number=1)
        rows = _ledger.read_events("sess1", "claude")
        assert [r["verb"] for r in rows] == ["submit_code", "submit_code"]
        assert [r["outcome"] for r in rows] == ["allow", "deny"]

    def test_count_verb_filters_outcome(self, tmp_path, monkeypatch):
        monkeypatch.setenv("JANUSMASK_STATE_DIR", str(tmp_path))
        _ledger.append_hook_event("s", "claude", "submit_code", "allow")
        _ledger.append_hook_event("s", "claude", "submit_code", "deny")
        _ledger.append_hook_event("s", "claude", "clarification", "allow")
        events = _ledger.read_events("s", "claude")
        assert _ledger.count_verb(events, "submit_code", outcome="allow") == 1
        assert _ledger.count_verb(events, "submit_code", outcome="deny") == 1
        assert _ledger.count_verb(events, "clarification", outcome="allow") == 1

    def test_read_tolerates_malformed_line(self, tmp_path, monkeypatch):
        monkeypatch.setenv("JANUSMASK_STATE_DIR", str(tmp_path))
        path = _ledger.ledger_path("sess", "claude")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"verb": "x", "outcome": "allow"}) + "\n"
            "this is not json\n"
            + json.dumps({"verb": "y", "outcome": "allow"}) + "\n"
        )
        rows = _ledger.read_events("sess", "claude")
        assert [r["verb"] for r in rows] == ["x", "y"]

    def test_read_missing_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setenv("JANUSMASK_STATE_DIR", str(tmp_path))
        assert _ledger.read_events("none", "claude") == []


# ---------- _state_gates ----------


class TestStateGates:
    def _write_state(self, tmp_path, **fields):
        state_file = tmp_path / "STATE.json"
        state_file.write_text(json.dumps(fields))
        return state_file

    def test_read_state_returns_dict(self, tmp_path, monkeypatch):
        monkeypatch.setenv("JANUSMASK_STATE_DIR", str(tmp_path))
        self._write_state(tmp_path, round=3, phase="synthesis", task_id="T")
        s = _state_gates.read_state_besteffort()
        assert s == {"round": 3, "phase": "synthesis", "task_id": "T"}

    def test_read_state_tolerates_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("JANUSMASK_STATE_DIR", str(tmp_path))
        assert _state_gates.read_state_besteffort() == {}

    def test_read_state_tolerates_corrupt(self, tmp_path, monkeypatch):
        monkeypatch.setenv("JANUSMASK_STATE_DIR", str(tmp_path))
        (tmp_path / "STATE.json").write_text("{not json")
        assert _state_gates.read_state_besteffort() == {}

    def test_current_round_env_wins(self, tmp_path, monkeypatch):
        monkeypatch.setenv("JANUSMASK_STATE_DIR", str(tmp_path))
        monkeypatch.setenv("JANUSMASK_ROUND", "9")
        self._write_state(tmp_path, round=2)
        assert _state_gates.current_round() == 9

    def test_current_round_fallback_to_state(self, tmp_path, monkeypatch):
        monkeypatch.setenv("JANUSMASK_STATE_DIR", str(tmp_path))
        monkeypatch.delenv("JANUSMASK_ROUND", raising=False)
        self._write_state(tmp_path, round=4)
        assert _state_gates.current_round() == 4

    def test_current_round_defaults_to_zero(self, tmp_path, monkeypatch):
        monkeypatch.setenv("JANUSMASK_STATE_DIR", str(tmp_path))
        monkeypatch.delenv("JANUSMASK_ROUND", raising=False)
        assert _state_gates.current_round() == 0

    def test_submissions_count_cap(self, tmp_path, monkeypatch):
        monkeypatch.setenv("JANUSMASK_STATE_DIR", str(tmp_path))
        for _ in range(3):
            _ledger.append_hook_event("s", "claude", "submit_code", "allow")
        assert _state_gates.submissions_count("s", "claude") == 3
        assert _state_gates.submissions_remaining("s", "claude") == _state_gates.MAX_SUBMISSIONS - 3

    def test_clarifications_cap(self, tmp_path, monkeypatch):
        monkeypatch.setenv("JANUSMASK_STATE_DIR", str(tmp_path))
        _ledger.append_hook_event("s", "claude", "clarification", "allow")
        _ledger.append_hook_event("s", "claude", "clarification", "allow")
        assert _state_gates.clarifications_count("s", "claude") == 2
        assert _state_gates.clarifications_remaining("s", "claude") == 0

    def test_plan_submitted_idempotency(self, tmp_path, monkeypatch):
        monkeypatch.setenv("JANUSMASK_STATE_DIR", str(tmp_path))
        assert not _state_gates.plan_submitted("s", "claude")
        _ledger.append_hook_event("s", "claude", "plan_draft", "allow")
        assert _state_gates.plan_submitted("s", "claude")

    def test_reconciliation_submitted_idempotency(self, tmp_path, monkeypatch):
        monkeypatch.setenv("JANUSMASK_STATE_DIR", str(tmp_path))
        assert not _state_gates.reconciliation_submitted("s", "claude")
        _ledger.append_hook_event("s", "claude", "reconciliation", "allow")
        assert _state_gates.reconciliation_submitted("s", "claude")
