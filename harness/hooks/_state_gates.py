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
    return _paths.state_dir() / _STATE_FILENAME

def read_state_besteffort() -> dict[str, Any]:
    """Best-effort read of STATE.json. Returns {} on missing/corrupt — hooks
        must not block the agent when STATE.json is transiently being rewritten.
        Use `harness.state.read_state` for authoritative reads."""
    try:
        path = _state_file()
        if not path.exists():
            return {}
        content = path.read_text(encoding='utf-8')
        data = json.loads(content)
        if isinstance(data, dict):
            return data
    except (ValueError, OSError):
        pass
    return {}

def current_round(state: dict[str, Any] | None=None) -> int:
    env_round = _paths.round_number()
    if env_round >= 0:
        return env_round
    state = state if state is not None else read_state_besteffort()
    raw = state.get('round')
    try:
        return int(raw) if raw is not None else 0
    except (TypeError, ValueError):
        return 0

def current_phase(state: dict[str, Any] | None=None) -> str:
    state = state if state is not None else read_state_besteffort()
    return state.get('phase') or ''

def current_task_id(state: dict[str, Any] | None=None) -> str:
    state = state if state is not None else read_state_besteffort()
    return state.get('task_id') or ''

def submissions_count(session_id: str, agent: str | None=None) -> int:
    return _ledger.count_verb(_ledger.read_events(session_id, agent), 'submit_code', outcome='allow')

def clarifications_count(session_id: str, agent: str | None=None) -> int:
    return _ledger.count_verb(_ledger.read_events(session_id, agent), 'clarification', outcome='allow')

def plan_submitted(session_id: str, agent: str | None=None) -> bool:
    return _ledger.has_verb(_ledger.read_events(session_id, agent), 'plan_draft', outcome='allow')

def reconciliation_submitted(session_id: str, agent: str | None=None) -> bool:
    return _ledger.has_verb(_ledger.read_events(session_id, agent), 'reconciliation', outcome='allow')

def submissions_remaining(session_id: str, agent: str | None=None) -> int:
    return max(0, MAX_SUBMISSIONS - submissions_count(session_id, agent))

def clarifications_remaining(session_id: str, agent: str | None=None) -> int:
    return max(0, MAX_CLARIFICATIONS - clarifications_count(session_id, agent))