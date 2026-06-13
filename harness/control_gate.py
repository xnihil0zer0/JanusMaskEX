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
    return config.get('control', {}) if isinstance(config, dict) else {}

def pause_flag_path(state_dir: Path, config: dict[str, Any]) -> Path:
    rel = _control_section(config).get('pause_flag_path') or DEFAULT_PAUSE_FLAG
    p = Path(rel)
    if not p.is_absolute():
        p = Path(state_dir).parent / rel
    return p

def decisions_dir(state_dir: Path, config: dict[str, Any]) -> Path:
    rel = _control_section(config).get('decisions_dir') or DEFAULT_DECISIONS_DIR
    p = Path(rel)
    if not p.is_absolute():
        p = Path(state_dir).parent / rel
    return p

def check_pause(state_dir: Path, config: dict[str, Any]) -> bool:
    """Return True iff the pause flag is set to ``paused``.

    Critique #13: tolerates EISDIR/EACCES/FileNotFoundError without
    crashing — degrades to False with a rate-limited WARNING.
    """
    path = pause_flag_path(state_dir, config)
    try:
        contents = path.read_text(errors='replace').strip().lower()
    except FileNotFoundError:
        return False
    except (IsADirectoryError, PermissionError, OSError) as e:
        key = f'{path}:{type(e).__name__}'
        now = time.time()
        if now - _last_pause_warning.get(key, 0) > _PAUSE_LOG_RATE_LIMIT:
            logger.warning('pause flag at %s unreadable (%s); treating as not-paused', path, e)
            _last_pause_warning[key] = now
        return False
    return contents == 'paused'

def require_approval_for(phase: str, config: dict[str, Any]) -> bool:
    requires = _control_section(config).get('require_approval', []) or []
    return phase in requires

def _read_decision(path: Path) -> Optional[dict]:
    """Return decision dict if present + parseable; None on absent/corrupt."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(errors='replace'))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError, ValueError) as e:
        logger.warning('decision file %s corrupt: %s', path, e)
        return None
    if not isinstance(data, dict) or 'decision' not in data:
        return None
    return data

def await_decision(state_dir: Path, task_id: str, phase: str, config: dict[str, Any], *, emit_pending: Optional[Callable]=None, emit_timeout: Optional[Callable]=None, poll_interval: float=_DECISION_POLL_INTERVAL, timeout: Optional[float]=None) -> str:
    """Block until ``state/control/decisions/{task_id}.json`` exists.

    Returns the decision string ('approve' / 'reject' / 'retry') or
    ``'timeout'`` after ``timeout`` seconds. Returns ``'auto'`` immediately
    when the task's phase is not in ``config['control']['require_approval']``
    — this is the default no-op path that keeps the orchestrator
    bit-identical when the operator has not opted in.
    """
    if not require_approval_for(phase, config):
        return 'auto'
    if timeout is None:
        timeout = float(_control_section(config).get('approval_timeout_sec', DEFAULT_APPROVAL_TIMEOUT))
    decisions = decisions_dir(state_dir, config)
    decisions.mkdir(parents=True, exist_ok=True)
    path = decisions / f'{task_id}.json'
    if emit_pending is not None:
        try:
            emit_pending(task_id, phase)
        except Exception:
            logger.exception('emit_pending callback failed')
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        rec = _read_decision(path)
        if rec is not None:
            return str(rec.get('decision', '')).lower() or 'auto'
        time.sleep(poll_interval)
    if emit_timeout is not None:
        try:
            emit_timeout(task_id, phase)
        except Exception:
            logger.exception('emit_timeout callback failed')
    return 'timeout'

def record_agent_pid(state_dir: Path, agent: str, pid: int) -> None:
    """Best-effort: stamp ``STATE.json`` with ``{agent}_pid``.

    Errors are swallowed — pid recording is observability, not correctness.
    """
    try:
        from harness import state as _state
    except Exception:
        return
    try:

        def _set(s):
            s[f'{agent}_pid'] = pid
            return s
        _state.locked_read_modify_write(_set, state_dir)
    except Exception as e:
        logger.warning('could not record %s_pid=%s: %s', agent, pid, e)
from harness import model_backends

def backend_choices():
    return list(model_backends.BACKEND_REGISTRY)
from harness import webui_config_schema

def typed_config_schema():
    return webui_config_schema.CONFIG_FIELDS