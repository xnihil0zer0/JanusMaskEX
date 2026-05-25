"""harness/control_gate.py — pause-flag + HITL decision helpers consumed by
the orchestrator's run_pipeline loop.

All helpers degrade gracefully on missing/corrupt control state — the
default behavior is "no gate" so a fresh checkout with no
``state/control/`` directory is bit-identical to pre-E4 orchestrator
behavior. Critique #13 (pause-flag IO errors must not crash the loop) is
honored: ``check_pause`` swallows EISDIR/EACCES/FileNotFoundError with a
single rate-limited WARNING and returns False.

Stdlib only.
"""
from __future__ import annotations
import json
import logging
import os
import time
from pathlib import Path
from typing import Any
from typing import Optional
from typing import Callable
logger = logging.getLogger('janusmask.control_gate')
DEFAULT_PAUSE_FLAG = 'state/control/orchestrator.flag'
DEFAULT_DECISIONS_DIR = 'state/control/decisions'
DEFAULT_APPROVAL_TIMEOUT = 1800.0
KNOWN_PHASES: tuple[str, ...] = ('synthesis', 'fuzzing', 'cross_examination', 'ast_validation', 'accepted', 'rejected', 'decomposition')
_DECISION_POLL_INTERVAL = 1.0
_PAUSE_LOG_RATE_LIMIT = 60.0
_last_pause_warning: dict[str, float] = {}

def _control_section(config: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(config, dict):
        return {}
    return config.get('control', {})

def pause_flag_path(state_dir: Path, config: dict[str, Any]) -> Path:
    raise NotImplementedError

def decisions_dir(state_dir: Path, config: dict[str, Any]) -> Path:
    raise NotImplementedError

def check_pause(state_dir: Path, config: dict[str, Any]) -> bool:
    """Return True iff the pause flag is set to ``paused``.

    Critique #13: tolerates EISDIR/EACCES/FileNotFoundError without
    crashing — degrades to False with a rate-limited WARNING.
    """
    raise NotImplementedError

def require_approval_for(phase: str, config: dict[str, Any]) -> bool:
    raise NotImplementedError

def _read_decision(path: Path) -> Optional[dict]:
    """Return decision dict if present + parseable; None on absent/corrupt."""
    raise NotImplementedError

def await_decision(state_dir: Path, task_id: str, phase: str, config: dict[str, Any], *, emit_pending: Optional[Callable]=None, emit_timeout: Optional[Callable]=None, poll_interval: float=_DECISION_POLL_INTERVAL, timeout: Optional[float]=None) -> str:
    """Block until ``state/control/decisions/{task_id}.json`` exists.

    Returns the decision string ('approve' / 'reject' / 'retry') or
    ``'timeout'`` after ``timeout`` seconds. Returns ``'auto'`` immediately
    when the task's phase is not in ``config['control']['require_approval']``
    — this is the default no-op path that keeps the orchestrator
    bit-identical when the operator has not opted in.
    """
    raise NotImplementedError

def record_agent_pid(state_dir: Path, agent: str, pid: int) -> None:
    """Best-effort: stamp ``STATE.json`` with ``{agent}_pid``.

    Errors are swallowed — pid recording is observability, not correctness.
    """
    raise NotImplementedError