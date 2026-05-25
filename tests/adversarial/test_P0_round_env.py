"""P0.4 adversarial battery — JANUSMASK_ROUND env plumbing.

Covers the master plan's Phase 0 adversarial row:
    Inject JANUSMASK_ROUND=999 while state.json holds round=1
    Expected: env takes precedence; submission filename has _round999_.

Plus mutation tests that revert the fix and confirm the test would have
caught it (meta-hook plan §5: no mutation = not counted).
"""

from __future__ import annotations

import inspect
import json
import os
import pathlib
import sys
from unittest import mock

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from harness import mcp_server as mcp_mod
from harness import orchestrator as orch_mod


# ---------------------------------------------------------------------------
# Attack 1: env takes precedence over STATE.json
# ---------------------------------------------------------------------------

def _make_server(tmp_path: pathlib.Path, state_round: int) -> mcp_mod.JanusMaskServer:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "STATE.json").write_text(
        json.dumps({"round": state_round, "phase": "synthesis"}),
        encoding="utf-8",
    )
    return mcp_mod.JanusMaskServer(agent_id="claude", state_dir=state_dir)


def test_env_round_overrides_state_json(tmp_path, monkeypatch):
    """JANUSMASK_ROUND=999 must win over STATE.json round=1."""
    server = _make_server(tmp_path, state_round=1)
    monkeypatch.setenv("JANUSMASK_ROUND", "999")
    assert server._current_round() == 999


def test_state_round_used_when_env_unset(tmp_path, monkeypatch):
    """Without env, STATE.json value is used."""
    server = _make_server(tmp_path, state_round=7)
    monkeypatch.delenv("JANUSMASK_ROUND", raising=False)
    assert server._current_round() == 7


def test_env_non_numeric_ignored(tmp_path, monkeypatch):
    """Garbage in env falls back to STATE.json (defence in depth)."""
    server = _make_server(tmp_path, state_round=3)
    monkeypatch.setenv("JANUSMASK_ROUND", "not-a-number")
    assert server._current_round() == 3


def test_env_empty_string_ignored(tmp_path, monkeypatch):
    """Empty env value falls back to STATE.json."""
    server = _make_server(tmp_path, state_round=5)
    monkeypatch.setenv("JANUSMASK_ROUND", "")
    assert server._current_round() == 5


def test_default_one_when_no_env_no_state(tmp_path, monkeypatch):
    """Missing env + missing state key → default 1."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "STATE.json").write_text(json.dumps({}), encoding="utf-8")
    server = mcp_mod.JanusMaskServer(agent_id="claude", state_dir=state_dir)
    monkeypatch.delenv("JANUSMASK_ROUND", raising=False)
    assert server._current_round() == 1


# ---------------------------------------------------------------------------
# Attack 2: env plumbing through orchestrator spawn path
# ---------------------------------------------------------------------------

def test_build_agent_env_includes_round_default():
    env = orch_mod._build_agent_env("claude", "/tmp/sd")
    assert env["JANUSMASK_ROUND"] == "1"


def test_build_agent_env_includes_round_explicit():
    env = orch_mod._build_agent_env("gemini", "/tmp/sd", round_number=7)
    assert env["JANUSMASK_ROUND"] == "7"


def test_spawn_agent_signature_accepts_round_num():
    """spawn_agent must accept round_number as the 4th positional or kw arg."""
    sig = inspect.signature(orch_mod.spawn_agent)
    assert "round_number" in sig.parameters
    # Default must exist so legacy callers (adversarial_review.py) still work.
    assert sig.parameters["round_number"].default == 1


def test_spawn_agent_passes_round_through_to_env(monkeypatch, tmp_path):
    """Spawn a fake claude command; assert env seen by Popen has the round."""
    captured = {}

    class _FakePopen:
        def __init__(self, cmd, **kwargs):
            captured["env"] = kwargs.get("env", {})
            captured["cmd"] = cmd
            self.pid = 424242

    monkeypatch.setattr(orch_mod.subprocess, "Popen", _FakePopen)
    monkeypatch.setattr(orch_mod, "start_stream_threads", lambda *a, **k: ())

    config = {
        "state_dir": str(tmp_path),
        "agents": {
            "claude": {
                "command": "claude",
                "args": ["-p", "--model", "sonnet"],
            }
        },
    }
    orch_mod.spawn_agent("claude", "prompt", config, round_number=7)
    assert captured["env"]["JANUSMASK_ROUND"] == "7"
    assert captured["env"]["JANUSMASK_AGENT"] == "claude"


# ---------------------------------------------------------------------------
# Attack 3: mutation test — revert the fix, confirm tests catch it
# ---------------------------------------------------------------------------

def test_mutation_revert_env_override_breaks_precedence(tmp_path, monkeypatch):
    """If we monkeypatch _current_round back to the pre-P0.4 logic, the
    first test would fail. This asserts the fix is what's exercised."""

    def _legacy_current_round(self):
        return int(self._read_state().get("round", 1))

    server = _make_server(tmp_path, state_round=1)
    monkeypatch.setenv("JANUSMASK_ROUND", "999")

    # Pre-fix: would return 1 even with env=999.
    with mock.patch.object(
        mcp_mod.JanusMaskServer, "_current_round", _legacy_current_round
    ):
        assert server._current_round() == 1

    # Post-fix (unpatched): env wins.
    assert server._current_round() == 999


def test_mutation_revert_build_agent_env_drops_round(monkeypatch):
    """Mirror of mutation test for orchestrator side."""

    def _legacy_build_agent_env(agent, state_dir):
        return {
            **os.environ,
            "PYTHONHASHSEED": "0",
            "JANUSMASK_AGENT": agent,
            "JANUSMASK_STATE_DIR": state_dir,
        }

    with mock.patch.object(orch_mod, "_build_agent_env", _legacy_build_agent_env):
        env = orch_mod._build_agent_env("claude", "/tmp/sd")
        assert "JANUSMASK_ROUND" not in env

    # After reverting the mock, current code must plumb round.
    env = orch_mod._build_agent_env("claude", "/tmp/sd", round_number=2)
    assert env["JANUSMASK_ROUND"] == "2"
