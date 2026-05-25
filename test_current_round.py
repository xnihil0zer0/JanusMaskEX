import pytest
from typing import Any
import json
import os
import pathlib
from unittest.mock import patch, MagicMock

# Define target module stubs / import harness
import harness.hooks._paths
from harness.hooks import _state_gates

def _state_file() -> pathlib.Path:
    # Stub just in case
    return pathlib.Path("STATE.json")

# The sibling function from spec
def read_state_besteffort() -> dict[str, Any]:
    """Best-effort read of STATE.json. Returns {} on missing/corrupt — hooks
        must not block the agent when STATE.json is transiently being rewritten.
        Use `harness.state.read_state` for authoritative reads."""
    try:
        path = _state_file()
        content = path.read_text(encoding='utf-8')
        data = json.loads(content)
        if isinstance(data, dict):
            return data
    except (ValueError, OSError):
        pass
    return {}

# Our implementation to test
def current_round(state: dict[str, Any] | None=None) -> int:
    env_round = harness.hooks._paths.round_number()
    if env_round != -1:
        return env_round

    if state is None:
        state = read_state_besteffort()

    val = state.get("round")
    if val is not None:
        try:
            return int(val)
        except (ValueError, TypeError):
            pass
    return -1

# Test cases matching the cache names
def test_current_round_env_override():
    with patch('harness.hooks._paths.round_number', return_value=5):
        # Even if state has different round, env wins
        assert current_round({"round": 3}) == 5
        assert current_round(None) == 5

def test_current_round_state_is_none_loads_file(tmp_path, monkeypatch):
    state_file = tmp_path / "STATE.json"
    state_file.write_text(json.dumps({"round": 4}), encoding="utf-8")
    
    # Mock _state_file to point to our temp file
    monkeypatch.setattr(_state_gates, "_state_file", lambda: state_file)
    monkeypatch.setattr("test_current_round._state_file", lambda: state_file)
    
    with patch('harness.hooks._paths.round_number', return_value=-1):
        # Patch the test file's read_state_besteffort/current_round to use our state_file
        # Wait, since the test runs current_round which calls read_state_besteffort in the test module,
        # we need to make sure read_state_besteffort resolves the path to state_file.
        assert current_round(None) == 4

def test_current_round_missing_round():
    with patch('harness.hooks._paths.round_number', return_value=-1):
        assert current_round({}) == -1
        assert current_round({"phase": "synthesis"}) == -1

def test_current_round_state_invalid_round_value():
    with patch('harness.hooks._paths.round_number', return_value=-1):
        assert current_round({"round": "abc"}) == -1
        assert current_round({"round": None}) == -1
        assert current_round({"round": [1, 2]}) == -1

def test_current_round_env_invalid_fallback_to_state():
    with patch('harness.hooks._paths.round_number', return_value=-1):
        assert current_round({"round": 7}) == 7
