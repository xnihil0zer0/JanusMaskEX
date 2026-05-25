"""Env resolution + safe_subpath wrapper for hook scripts.

The orchestrator seeds these env vars on the worker process:
    JANUSMASK_AGENT      claude|gemini
    JANUSMASK_STATE_DIR  absolute path to state/
    JANUSMASK_MODE       synthesis|planning|reconciliation
    JANUSMASK_ROUND      integer (overrides STATE.json.round per P0.4)
    JANUSMASK_PROJECT_DIR  absolute repo root

Hooks must never trust agent-supplied paths. `safe_subpath` re-exports
`harness.safe_subpath.is_safe_subpath` unchanged — this module only adds
the convenience of rooting against the authoritative state/project dirs.
"""
from __future__ import annotations
import json
import os
import pathlib
from typing import Any
from harness.safe_subpath import is_safe_subpath
_DEFAULT_PROJECT_DIR = pathlib.Path(__file__).resolve().parent.parent.parent

def project_dir() -> pathlib.Path:
    raw = os.environ.get('JANUSMASK_PROJECT_DIR')
    if not raw:
        raw = os.environ.get('CLAUDE_PROJECT_DIR')
    if raw:
        return pathlib.Path(raw).resolve()
    default_dir = globals().get('_DEFAULT_PROJECT_DIR')
    if default_dir is not None:
        return default_dir
    try:
        from harness.hooks._paths import _DEFAULT_PROJECT_DIR as fallback_default
        return fallback_default
    except ImportError:
        pass
    return pathlib.Path(__file__).resolve().parent.parent.parent

def state_dir() -> pathlib.Path:
    raw = os.environ.get('JANUSMASK_STATE_DIR')
    if not raw:
        raw = os.environ.get('CLAUDE_STATE_DIR')
    if raw:
        return pathlib.Path(raw).resolve()
    return (project_dir() / 'state').resolve()

def agent() -> str:
    raise NotImplementedError

def mode() -> str:
    raise NotImplementedError

def round_number() -> int:
    """Prefer JANUSMASK_ROUND env (authoritative post-P0.4), else -1 sentinel.

    Callers that also need to consult STATE.json should use
    `_state_gates.current_round` which layers env -> STATE.json fallback.
    """
    raise NotImplementedError

def safe_under_state(candidate: str) -> bool:
    """True iff `candidate` resolves inside the state dir."""
    raise NotImplementedError

def safe_under_project(candidate: str) -> bool:
    """True iff `candidate` resolves inside the project root."""
    raise NotImplementedError

def load_inbox_task(inbox_dir: pathlib.Path) -> dict[str, Any]:
    """Read ``<inbox_dir>/task.json`` and return the parsed dict.

    Returns ``{}`` when the file is missing, unreadable, or contains
    malformed JSON — callers downstream expect a dict and derive their
    own defaults (``task_id="default"`` etc.) from the empty result.

    ``inbox_dir`` is supplied by the caller (typically the agent's
    ``_env.inbox_dir(session_id)``) so this hoist stays agent-agnostic
    and avoids an otherwise-circular import on the per-agent ``_env``.
    """
    raise NotImplementedError