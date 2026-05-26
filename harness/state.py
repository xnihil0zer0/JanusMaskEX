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
    return Path(os.environ.get('JANUSMASK_STATE_DIR', STATE_DIR_STR))

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
    tmp_path = state_path.with_suffix('.json.tmp')
    with open(tmp_path, 'w') as f:
        json.dump(state, f, indent=2)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    tmp_path.replace(state_path)

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
    state_dir = state_dir or _default_state_dir()
    _ensure_paths(state_dir)
    lock_path = _lock_file(state_dir)
    state_path = _state_file(state_dir)
    with open(lock_path, 'a') as lock_fd:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            state = _read_state_from_disk(state_path)
            state = modifier_fn(state)
            _write_state_to_disk(state_path, state)
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
    return state

def read_state(state_dir: Path | None=None) -> dict[str, Any]:
    state_dir = state_dir or _default_state_dir()
    _ensure_paths(state_dir)
    lock_path = _lock_file(state_dir)
    state_path = _state_file(state_dir)
    with open(lock_path, 'a') as lock_fd:
        fcntl.flock(lock_fd, fcntl.LOCK_SH)
        try:
            state = _read_state_from_disk(state_path)
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
    return state

def init_state(state_dir: Path | None=None) -> dict[str, Any]:
    state_dir = state_dir or _default_state_dir()
    _ensure_paths(state_dir)
    lock_path = _lock_file(state_dir)
    state_path = _state_file(state_dir)
    initial = {k: list(v) if isinstance(v, list) else v for k, v in INITIAL_STATE.items()}
    with open(lock_path, 'a') as lock_fd:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            if state_path.exists():
                try:
                    with open(state_path, 'r') as f:
                        current_state = json.load(f)
                    if isinstance(current_state, dict) and current_state.get('handoff_pending') is True:
                        current_state['handoff_pending'] = False
                        _write_state_to_disk(state_path, current_state)
                        return current_state
                except Exception:
                    pass
            _write_state_to_disk(state_path, initial)
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
    return initial

def serialize_orchestrator_state(state_dir: Path) -> None:
    """Serializes orchestrator state to disk for exec handover."""

    def _modifier(state: dict[str, Any]) -> dict[str, Any]:
        state['handoff_pending'] = True
        state['handoff_time'] = time.time()
        return state
    locked_read_modify_write(_modifier, state_dir)

def set_phase(state_dir: Path | None=None, *, phase: str) -> dict[str, Any]:
    if phase not in VALID_PHASES:
        raise InvalidPhaseError(f'Invalid phase {phase!r}. Must be one of: {', '.join(sorted(VALID_PHASES))}')

    def _modifier(state: dict[str, Any]) -> dict[str, Any]:
        state['phase'] = phase
        return state
    return locked_read_modify_write(_modifier, state_dir)

def set_agent_status(state_dir: Path | None=None, *, agent: str, status: str) -> dict[str, Any]:
    """Updates the status of a specific agent in the state file under lock."""
    if agent not in VALID_AGENTS:
        raise InvalidAgentError(f'Invalid agent {agent!r}. Must be one of: {', '.join(sorted(VALID_AGENTS))}')
    if status not in VALID_AGENT_STATUSES:
        raise InvalidAgentStatusError(f'Invalid status {status!r}. Must be one of: {', '.join(sorted(VALID_AGENT_STATUSES))}')
    key = f'{agent}_status'

    def _modifier(state: dict[str, Any]) -> dict[str, Any]:
        state[key] = status
        if status == 'running':
            state['status_updated_at_epoch'] = time.time()
        return state
    return locked_read_modify_write(_modifier, state_dir)

def get_phase(state_dir: Path | None=None) -> str:
    state = read_state(state_dir)
    return state['phase']

def get_agent_status(state_dir: Path | None=None, *, agent: str) -> str:
    if agent not in VALID_AGENTS:
        raise InvalidAgentError(f'Invalid agent {agent!r}. Must be one of: {', '.join(sorted(VALID_AGENTS))}')
    state = read_state(state_dir)
    return state[f'{agent}_status']
if 'VALID_AGENTS' not in globals():
    try:
        from harness.state import VALID_AGENTS
    except ImportError:
        VALID_AGENTS = frozenset({'claude', 'gemini', 'antigravity'})
if 'VALID_AGENT_STATUSES' not in globals():
    try:
        from harness.state import VALID_AGENT_STATUSES
    except ImportError:
        VALID_AGENT_STATUSES = frozenset({'pending', 'running', 'submitted', 'error', 'timeout'})
if 'InvalidAgentError' not in globals():
    try:
        from harness.state import InvalidAgentError
    except ImportError:

        class InvalidAgentError(Exception):
            pass
if 'InvalidAgentStatusError' not in globals():
    try:
        from harness.state import InvalidAgentStatusError
    except ImportError:

        class InvalidAgentStatusError(Exception):
            pass
if 'locked_read_modify_write' not in globals():
    try:
        from harness.state import locked_read_modify_write
    except ImportError:

        def locked_read_modify_write(modifier_fn: Callable[[dict[str, Any]], dict[str, Any]], state_dir: Path | None=None) -> dict[str, Any]:
            raise NotImplementedError('locked_read_modify_write not found')
from harness.state import InvalidAgentError
from harness.state import VALID_AGENTS
from harness.state import read_state
'Reconstruction of get_agent_status for harness/state.py.'