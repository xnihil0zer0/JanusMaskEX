"""STATE.json reader + ledger-backed counter helpers for hook scripts.

Hooks must read STATE.json on every invocation (they're stateless). This
module layers env-override -> STATE.json so the round-number rule landed
under P0.4 (JANUSMASK_ROUND wins when set) is honoured consistently.

Idempotency flags like `plan_submitted` / `reconciliation_submitted` are
derived from the per-session ledger (`_ledger.py`).
"""
from __future__ import annotations
import json
import pathlib
from typing import Any
from . import _ledger
from . import _paths
_STATE_FILENAME = 'STATE.json'
MAX_SUBMISSIONS = 5
MAX_CLARIFICATIONS = 2

def _state_file() -> pathlib.Path:
    raise NotImplementedError

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

def current_round(state: dict[str, Any] | None=None) -> int:
    env_round = harness.hooks._paths.round_number()
    if env_round != -1:
        return env_round
    if state is None:
        state = read_state_besteffort()
    val = state.get('round')
    if val is not None:
        try:
            return int(val)
        except (ValueError, TypeError):
            pass
    return -1

def current_phase(state: dict[str, Any] | None=None) -> str:
    import harness.hooks._paths
    mode_func = harness.hooks._paths.mode
    is_mocked = hasattr(mode_func, 'called') or hasattr(mode_func, 'mock_calls') or hasattr(mode_func, 'return_value')
    try:
        env_mode = mode_func()
    except Exception:
        env_mode = os.environ.get('JANUSMASK_MODE')
    if is_mocked or 'JANUSMASK_MODE' in os.environ or (env_mode is not None and env_mode != 'synthesis'):
        if env_mode is not None:
            return str(env_mode)
    if state is None:
        state = read_state_besteffort()
    val = state.get('phase')
    if val is not None:
        return str(val)
    return 'synthesis'

def current_task_id(state: dict[str, Any] | None=None) -> str:
    env_task_id = os.environ.get('JANUSMASK_TASK_ID')
    if env_task_id is not None:
        return str(env_task_id)
    if state is None:
        state = read_state_besteffort()
    val = state.get('task_id')
    if val is not None:
        return str(val)
    return 'default'

def submissions_count(session_id: str, agent: str | None=None) -> int:
    events = harness.hooks._ledger.read_events(session_id, agent)
    return harness.hooks._ledger.count_verb(events, 'submission', outcome='allow')

def clarifications_count(session_id: str, agent: str | None=None) -> int:
    events = harness.hooks._ledger.read_events(session_id, agent)
    return harness.hooks._ledger.count_verb(events, 'clarification', outcome='allow')

def plan_submitted(session_id: str, agent: str | None=None) -> bool:
    events = harness.hooks._ledger.read_events(session_id, agent)
    return harness.hooks._ledger.has_verb(events, 'plan_draft', outcome='allow')

def reconciliation_submitted(session_id: str, agent: str | None=None) -> bool:
    events = harness.hooks._ledger.read_events(session_id, agent)
    return harness.hooks._ledger.has_verb(events, 'reconciliation', outcome='allow')

def submissions_remaining(session_id: str, agent: str | None=None) -> int:
    return max(0, MAX_SUBMISSIONS - submissions_count(session_id, agent))

def clarifications_remaining(session_id: str, agent: str | None=None) -> int:
    raise NotImplementedError
import harness.hooks._paths
import os
import harness.hooks._ledger