"""Adversarial pins — harness/state.py (Plan 04, CASE-K/L) + GAP-6 dead shims.

CASE-K: set_agent_status rejects 'claude_fallback' (VALID_AGENTS has no fallback
        identity) — the orchestrator records fallback runs under the canonical
        'claude' identity, never 'claude_fallback'. antigravity IS valid.
CASE-L: locked_read_modify_write typed errors on corrupt/missing STATE.json and
        serializes concurrent modifiers under flock.
GAP-6:  the self-import shims at state.py:168-205 are dead no-ops (names already
        defined above). Pin that they don't shadow/break the real symbols.
"""
from __future__ import annotations

import json
import pathlib
import sys
import threading

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from harness import state  # noqa: E402


# ------------------------------------------------------------------- CASE-K


class TestValidAgents:
    def test_claude_fallback_rejected(self, tmp_path):
        state.init_state(tmp_path)
        with pytest.raises(state.InvalidAgentError):
            state.set_agent_status(tmp_path, agent="claude_fallback", status="submitted")

    def test_antigravity_accepted(self, tmp_path):
        state.init_state(tmp_path)
        out = state.set_agent_status(tmp_path, agent="antigravity", status="submitted")
        assert out["antigravity_status"] == "submitted"

    def test_valid_agents_frozenset_has_no_fallback(self):
        assert "claude_fallback" not in state.VALID_AGENTS
        assert state.VALID_AGENTS == frozenset({"claude", "gemini", "antigravity"})

    def test_invalid_status_rejected(self, tmp_path):
        state.init_state(tmp_path)
        with pytest.raises(state.InvalidAgentStatusError):
            state.set_agent_status(tmp_path, agent="claude", status="bogus")


# ------------------------------------------------------------------- CASE-L


class TestLockedReadModifyWrite:
    def test_corrupt_state_raises(self, tmp_path):
        (tmp_path / "STATE.json").write_text("{ not valid json")
        with pytest.raises(state.StateCorruptError):
            state.locked_read_modify_write(lambda s: s, tmp_path)

    def test_root_not_object_raises_corrupt(self, tmp_path):
        (tmp_path / "STATE.json").write_text("[1, 2, 3]")
        with pytest.raises(state.StateCorruptError):
            state.locked_read_modify_write(lambda s: s, tmp_path)

    def test_missing_state_raises(self, tmp_path):
        # _ensure_paths creates the dir but NOT the STATE.json file.
        with pytest.raises(state.StateMissingError):
            state.locked_read_modify_write(lambda s: s, tmp_path)

    def test_concurrent_increments_serialize(self, tmp_path):
        state.init_state(tmp_path)
        n_threads = 12

        def _inc():
            def _m(s):
                s["round"] = s.get("round", 0) + 1
                return s
            state.locked_read_modify_write(_m, tmp_path)

        threads = [threading.Thread(target=_inc) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        final = json.loads((tmp_path / "STATE.json").read_text())
        assert final["round"] == n_threads, (
            f"flock did not serialize: round={final['round']} != {n_threads}"
        )


# ------------------------------------------------------------------- GAP-6


class TestDeadDefensiveShims:
    def test_locked_rmw_is_not_the_notimplemented_stub(self, tmp_path):
        """state.py:192-198 defines a fallback locked_read_modify_write that
        raises NotImplementedError, guarded by `if 'X' not in globals()`. That
        branch is unreachable (the real fn is defined earlier). Prove the live
        symbol is the real one, not the stub."""
        state.init_state(tmp_path)
        out = state.locked_read_modify_write(lambda s: s, tmp_path)
        assert isinstance(out, dict) and "round" in out

    def test_module_defines_symbols_once_usable(self):
        # The self-import shims (168-205) must leave working callables/types.
        for name in ("VALID_AGENTS", "VALID_AGENT_STATUSES", "InvalidAgentError",
                     "InvalidAgentStatusError", "locked_read_modify_write",
                     "read_state", "set_phase", "VALID_PHASES", "InvalidPhaseError"):
            assert hasattr(state, name), f"state lost symbol {name} after shims"
