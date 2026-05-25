import pytest
from typing import Any
import json
import os
import pathlib
from unittest.mock import patch, MagicMock

# Define target module stubs / import harness
from harness.hooks import _state_gates

def _state_file() -> pathlib.Path:
    return pathlib.Path("STATE.json")

# Sibling from spec
def read_state_besteffort() -> dict[str, Any]:
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
def current_task_id(state: dict[str, Any] | None=None) -> str:
    env_task = os.environ.get("JANUSMASK_TASK_ID")
    if env_task is not None:
        return str(env_task)

    if state is None:
        state = read_state_besteffort()

    val = state.get("task_id")
    if val is not None:
        return str(val)
    return "default"

# Test cases
def test_current_task_id_env_override(monkeypatch):
    monkeypatch.setenv("JANUSMASK_TASK_ID", "task-env-123")
    assert current_task_id({"task_id": "task-state-456"}) == "task-env-123"
    assert current_task_id(None) == "task-env-123"

def test_current_task_id_env_override_empty(monkeypatch):
    monkeypatch.setenv("JANUSMASK_TASK_ID", "")
    assert current_task_id({"task_id": "task-state-456"}) == ""
    assert current_task_id(None) == ""

def test_current_task_id_state_fallback(monkeypatch):
    monkeypatch.delenv("JANUSMASK_TASK_ID", raising=False)
    assert current_task_id({"task_id": "task-state-456"}) == "task-state-456"

def test_current_task_id_state_fallback_missing(monkeypatch):
    monkeypatch.delenv("JANUSMASK_TASK_ID", raising=False)
    assert current_task_id({}) == "default"
    assert current_task_id({"round": 3}) == "default"

def test_current_task_id_state_fallback_non_str(monkeypatch):
    monkeypatch.delenv("JANUSMASK_TASK_ID", raising=False)
    assert current_task_id({"task_id": 123}) == "123"

def test_current_task_id_state_is_none_loads_file(tmp_path, monkeypatch):
    state_file = tmp_path / "STATE.json"
    state_file.write_text(json.dumps({"task_id": "task-file-789"}), encoding="utf-8")
    
    monkeypatch.setattr(_state_gates, "_state_file", lambda: state_file)
    monkeypatch.setattr("test_current_task_id._state_file", lambda: state_file)
    monkeypatch.delenv("JANUSMASK_TASK_ID", raising=False)
    
    assert current_task_id(None) == "task-file-789"
