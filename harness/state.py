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
    try:
        from harness.paths import STATE_DIR
        return STATE_DIR.resolve()
    except ImportError:
        return (Path(__file__).resolve().parent.parent / 'state').resolve()

def _state_file(state_dir: Path) -> Path:
    raise NotImplementedError

def _lock_file(state_dir: Path) -> Path:
    raise NotImplementedError

def _ensure_paths(state_dir: Path) -> None:
    raise NotImplementedError

def _read_state_from_disk(state_path: Path) -> dict[str, Any]:
    raise NotImplementedError

def _write_state_to_disk(state_path: Path, state: dict[str, Any]) -> None:
    raise NotImplementedError

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
    raise NotImplementedError

def read_state(state_dir: Path | None=None) -> dict[str, Any]:
    raise NotImplementedError

def init_state(state_dir: Path | None=None) -> dict[str, Any]:
    raise NotImplementedError

def set_phase(state_dir: Path | None=None, *, phase: str) -> dict[str, Any]:
    raise NotImplementedError

def set_agent_status(state_dir: Path | None=None, *, agent: str, status: str) -> dict[str, Any]:
    raise NotImplementedError

def get_phase(state_dir: Path | None=None) -> str:
    raise NotImplementedError

def get_agent_status(state_dir: Path | None=None, *, agent: str) -> str:
    raise NotImplementedError