"""Flock-based thread-safe JSON state management for JanusMask."""
from __future__ import annotations
import fcntl
import json
import os
import time
from pathlib import Path
from typing import Any
from typing import Callable
from harness.paths import STATE_DIR_STR
VALID_PHASES = frozenset({'idle', 'synthesis', 'ast_validation', 'fuzzing', 'cross_examination', 'decomposition', 'accepted', 'rejected'})
VALID_AGENTS = frozenset({'claude', 'gemini', 'antigravity'})
VALID_AGENT_STATUSES = frozenset({'pending', 'running', 'submitted', 'error', 'timeout'})
INITIAL_STATE: dict[str, Any] = {'task_id': None, 'round': 0, 'phase': 'idle', 'claude_status': 'pending', 'gemini_status': 'pending', 'antigravity_status': 'pending', 'status_updated_at_epoch': None, 'fuzz_results': None, 'cross_exam_round': 0, 'decomposed': False, 'parent_task': None, 'children': []}

def _default_state_dir() -> Path:
    raw = os.environ.get('JANUSMASK_STATE_DIR')
    if not raw:
        raw = os.environ.get('CLAUDE_STATE_DIR')
    if raw:
        return Path(raw).resolve()
    from harness.paths import STATE_DIR
    return STATE_DIR.resolve()

def _state_file(state_dir: Path) -> Path:
    return state_dir / 'STATE.json'

def _lock_file(state_dir: Path) -> Path:
    return state_dir / 'state.lock'

def _ensure_paths(state_dir: Path) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)

def _read_state_from_disk(state_path: Path) -> dict[str, Any]:
    try:
        with open(state_path, 'r') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError('STATE.json root is not a JSON object')
        return data
    except (json.JSONDecodeError, ValueError) as exc:
        raise StateCorruptError(f'Corrupt state file at {state_path}: {exc}') from exc
    except FileNotFoundError as exc:
        raise StateMissingError(f'State file not found at {state_path}') from exc

def _write_state_to_disk(state_path: Path, state: dict[str, Any]) -> None:
    temp_path = state_path.parent / f'{state_path.name}.tmp'
    try:
        with open(temp_path, 'w') as f:
            json.dump(state, f, indent=2)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, state_path)
    except Exception:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass
        raise

class StateError(Exception):
    pass

class StateCorruptError(StateError):
    pass

class StateMissingError(StateError):
    pass

class InvalidPhaseError(StateError):
    pass

class InvalidAgentError(StateError):
    pass

class InvalidAgentStatusError(StateError):
    pass

def locked_read_modify_write(modifier_fn: Callable[[dict[str, Any]], dict[str, Any]], state_dir: Path | None=None) -> dict[str, Any]:
    if state_dir is None:
        state_dir = _default_state_dir()
    _ensure_paths(state_dir)
    state_path = state_dir / 'STATE.json'
    lock_path = state_dir / 'state.lock'
    with open(lock_path, 'a') as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        state = _read_state_from_disk(state_path)
        new_state = modifier_fn(state)
        _write_state_to_disk(state_path, new_state)
        return new_state

def read_state(state_dir: Path | None=None) -> dict[str, Any]:
    if state_dir is None:
        state_dir = _default_state_dir()
    state_path = _state_file(state_dir)
    return _read_state_from_disk(state_path)

def init_state(state_dir: Path | None=None) -> dict[str, Any]:
    if state_dir is None:
        state_dir = _default_state_dir()
    _ensure_paths(state_dir)
    lock_path = _lock_file(state_dir)
    with open(lock_path, 'a') as f:
        pass
    state_path = _state_file(state_dir)
    _write_state_to_disk(state_path, INITIAL_STATE)
    return INITIAL_STATE

def set_phase(state_dir: Path | None=None, *, phase: str) -> dict[str, Any]:
    if phase not in VALID_PHASES:
        raise InvalidPhaseError(f'Invalid phase: {phase}')

    def _mod(s):
        s['phase'] = phase
        return s
    return locked_read_modify_write(_mod, state_dir)

def set_agent_status(state_dir: Path | None=None, *, agent: str, status: str) -> dict[str, Any]:
    if agent not in VALID_AGENTS:
        raise InvalidAgentError(f'Invalid agent: {agent}')
    if status not in VALID_AGENT_STATUSES:
        raise InvalidAgentStatusError(f'Invalid status: {status}')

    def _mod(s):
        s[f'{agent}_status'] = status
        return s
    return locked_read_modify_write(_mod, state_dir)

def get_phase(state_dir: Path | None=None) -> str:
    state = read_state(state_dir)
    return state.get('phase', 'idle')

def get_agent_status(state_dir: Path | None=None, *, agent: str) -> str:
    if agent not in VALID_AGENTS:
        raise InvalidAgentError(f'Invalid agent: {agent}')
    state = read_state(state_dir)
    return state.get(f'{agent}_status', 'pending')
from harness.state import StateCorruptError
from harness.state import StateMissingError