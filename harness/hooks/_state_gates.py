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
    raise NotImplementedError

def current_task_id(state: dict[str, Any] | None=None) -> str:
    raise NotImplementedError

def submissions_count(session_id: str, agent: str | None=None) -> int:
    raise NotImplementedError

def clarifications_count(session_id: str, agent: str | None=None) -> int:
    raise NotImplementedError

def plan_submitted(session_id: str, agent: str | None=None) -> bool:
    raise NotImplementedError

def reconciliation_submitted(session_id: str, agent: str | None=None) -> bool:
    raise NotImplementedError

def submissions_remaining(session_id: str, agent: str | None=None) -> int:
    raise NotImplementedError

def clarifications_remaining(session_id: str, agent: str | None=None) -> int:
    raise NotImplementedError
import harness.hooks._paths