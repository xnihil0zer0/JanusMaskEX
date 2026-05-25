"""Adversarial battery for HOOK-10-scaffold-common (Phase 1).

Phase 1 adv matrix (hooks-augmented plan §5) lists three attacks; the
concurrent-submit and forge-contract variants target `hooks/rpc/submit_code`
which lands under HOOK-11. Here we cover the scaffold-level surface that
HOOK-11 builds on:

1. Path-traversal attempt via JANUSMASK_STATE_DIR — safe_under_state still
   rejects paths that escape the configured state root.
2. Session-id forge attempt: agent-controlled session_id must not let one
   agent overwrite another's ledger counter.
3. Decision vocab confusion: stray tokens ("BLOCK", "  allow "), arrays,
   non-dict payloads — scaffold normalises or rejects cleanly.
4. Ledger tolerates malformed JSONL and still agrees with the state-gate
   counter (idempotency invariant foundation).
5. Round-number env-over-STATE authority (P0.4 invariant) holds through
   the hook path too.
"""

from __future__ import annotations

import io
import json

import pytest

import harness.hooks._common
import harness.hooks._paths
import harness.hooks._ledger
import harness.hooks._state_gates
from harness.hooks import _common, _ledger, _paths, _state_gates


class TestPathTraversalAttack:
    def test_escape_via_dotdot_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setenv("JANUSMASK_STATE_DIR", str(tmp_path / "state"))
        (tmp_path / "state").mkdir()
        escape = tmp_path / "state" / ".." / "escape.txt"
        assert not _paths.safe_under_state(str(escape))

    def test_absolute_path_outside_state_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setenv("JANUSMASK_STATE_DIR", str(tmp_path / "state"))
        (tmp_path / "state").mkdir()
        assert not _paths.safe_under_state("/etc/passwd")

    def test_sibling_directory_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setenv("JANUSMASK_STATE_DIR", str(tmp_path / "state"))
        (tmp_path / "state").mkdir()
        (tmp_path / "sibling").mkdir()
        assert not _paths.safe_under_state(str(tmp_path / "sibling" / "x"))


class TestSessionIdForgeAttack:
    """Contract: the hook always keys the ledger path by (agent, session_id)
    it trusts (from env), never the agent's JSON payload. This ensures an
    agent forging a session_id field cannot overwrite another session."""

    def test_ledger_path_binds_to_agent_and_session(self, tmp_path, monkeypatch):
        monkeypatch.setenv("JANUSMASK_STATE_DIR", str(tmp_path))
        p1 = _ledger.ledger_path("A", agent="claude")
        p2 = _ledger.ledger_path("A", agent="gemini")
        p3 = _ledger.ledger_path("B", agent="claude")
        assert p1 != p2 and p1 != p3 and p2 != p3
        assert "claude_A" in str(p1)
        assert "gemini_A" in str(p2)

    def test_cross_session_counter_isolation(self, tmp_path, monkeypatch):
        monkeypatch.setenv("JANUSMASK_STATE_DIR", str(tmp_path))
        for _ in range(3):
            _ledger.append_hook_event("sess-victim", "claude", "submit_code", "allow")
        _ledger.append_hook_event("sess-attacker", "claude", "submit_code", "allow")
        assert _state_gates.submissions_count("sess-victim", "claude") == 3
        assert _state_gates.submissions_count("sess-attacker", "claude") == 1


class TestDecisionVocabConfusion:
    def test_mixed_case_block_rejected(self):
        # Normalizer removed: PreToolUse vocabulary is strictly
        # {allow, deny}. Any casing of "block" must raise ValueError.
        with pytest.raises(ValueError):
            _common.decision_payload("BLOCK", reason="x")

    def test_whitespace_padding_tolerated(self):
        assert _common.decision_payload("  allow  ")["decision"] == "allow"

    def test_ask_not_accepted(self):
        with pytest.raises(ValueError):
            _common.decision_payload("ask")

    def test_empty_decision_raises(self):
        with pytest.raises(ValueError):
            _common.decision_payload("")

    def test_non_dict_stdin_rejected(self):
        with pytest.raises(_common.HookInputError):
            _common.read_input(io.StringIO('"just a string"'))
        with pytest.raises(_common.HookInputError):
            _common.read_input(io.StringIO("42"))

    def test_array_stdin_rejected(self):
        with pytest.raises(_common.HookInputError):
            _common.read_input(io.StringIO("[1,2,3]"))


class TestLedgerResilience:
    def test_counter_agrees_with_state_gate_after_corruption(self, tmp_path, monkeypatch):
        monkeypatch.setenv("JANUSMASK_STATE_DIR", str(tmp_path))
        for _ in range(2):
            _ledger.append_hook_event("s", "claude", "submit_code", "allow")
        p = _ledger.ledger_path("s", agent="claude")
        p.write_text(p.read_text() + "{not json\n")
        _ledger.append_hook_event("s", "claude", "submit_code", "allow")
        events = _ledger.read_events("s", "claude")
        assert _ledger.count_verb(events, "submit_code", outcome="allow") == 3
        assert _state_gates.submissions_count("s", "claude") == 3


class TestRoundEnvAuthority:
    """Mutation-style: break the P0.4 invariant; confirm it's detectable."""

    def test_env_overrides_state_round(self, tmp_path, monkeypatch):
        monkeypatch.setenv("JANUSMASK_STATE_DIR", str(tmp_path))
        (tmp_path / "STATE.json").write_text(json.dumps({"round": 999}))
        monkeypatch.setenv("JANUSMASK_ROUND", "0")
        assert _state_gates.current_round() == 0

    def test_env_unset_falls_back_to_state(self, tmp_path, monkeypatch):
        monkeypatch.setenv("JANUSMASK_STATE_DIR", str(tmp_path))
        (tmp_path / "STATE.json").write_text(json.dumps({"round": 7}))
        monkeypatch.delenv("JANUSMASK_ROUND", raising=False)
        assert _state_gates.current_round() == 7
