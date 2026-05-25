"""Shared worker env + workdir resolution (T2-3).

Consolidates the per-agent ``harness.hooks.claude._env`` and
``harness.hooks.gemini._env`` modules — they were ~95% byte-identical,
differing only in the ``workdirs/<agent>`` prefix and gemini's
``folder_trust_enabled`` helper (moved to
``harness.hooks.gemini._folder_trust``).

Per-session layout (identical across agents)::

    $JANUSMASK_WORK_DIR/
        inbox/     # orchestrator-staged; task.json / brief.json / ...
        outbox/    # agent-written; submission.py, plan_draft.json, ...
        ledger/    # append-only hook_events.jsonl (sub-plan 02 §10)

``JANUSMASK_WORK_DIR`` is authoritative; when absent, the resolver falls
back to ``$JANUSMASK_STATE_DIR/workdirs/<agent>/<session_id>`` where
``<agent>`` is supplied explicitly by the per-agent shim (so agent
identity never depends on ``JANUSMASK_AGENT`` being set in the
caller's environment — local test fixtures often omit it).

All helpers are module-private (leading underscore) so the shared
module itself does not introduce new public symbols — the per-agent
shims re-export them under the public names the rest of the hook
codebase already imports.
"""
from __future__ import annotations
import os
import pathlib
from . import _paths
_INBOX_EXPECTATIONS: dict[str, tuple[str, ...]] = {'synthesis': ('task.json',), 'planning': ('brief.json', 'diff_summary.json'), 'reconciliation': ('diff_summary.json',)}

def _resolve_agent(agent: str | None) -> str:
    """Pick the agent identity: explicit arg wins, else ``_paths.agent()``.

    The per-agent shims pass ``agent="claude"`` / ``agent="gemini"``
    verbatim so the workdir prefix stays stable even when
    ``JANUSMASK_AGENT`` is unset (e.g. unit tests that only configure
    ``JANUSMASK_STATE_DIR``).
    """
    if agent is not None:
        return agent
    return _paths.agent()

def _work_dir(session_id: str | None=None, *, agent: str | None=None) -> pathlib.Path:
    work_dir_env = os.environ.get('JANUSMASK_WORK_DIR', '')
    if work_dir_env:
        return pathlib.Path(work_dir_env).resolve()
    actual_session = session_id
    if not actual_session:
        actual_session = os.environ.get('JANUSMASK_SESSION_ID', '')
    if not actual_session:
        actual_session = 'nosession'
    actual_agent = _resolve_agent(agent)
    return (_paths.state_dir() / 'workdirs' / actual_agent / actual_session).resolve()

def _inbox_dir(session_id: str | None=None, *, agent: str | None=None) -> pathlib.Path:
    return _work_dir(session_id, agent=agent) / 'inbox'

def _outbox_dir(session_id: str | None=None, *, agent: str | None=None) -> pathlib.Path:
    return _work_dir(session_id, agent=agent) / 'outbox'

def _ledger_dir(session_id: str | None=None, *, agent: str | None=None) -> pathlib.Path:
    return _work_dir(session_id, agent=agent) / 'ledger'

def _expected_inbox_files(mode: str) -> tuple[str, ...]:
    """Return the expected inbox files for the given mode."""
    return _INBOX_EXPECTATIONS.get(mode, ())

def _inbox_ready(mode: str, session_id: str | None=None, *, agent: str | None=None) -> bool:
    """True iff at least one expected inbox file exists for ``mode``.

    Unknown modes return False so the caller can surface a loud stop
    reason rather than silently continuing with an unstaged worker.
    """
    expected = _expected_inbox_files(mode)
    if not expected:
        return False
    base = _inbox_dir(session_id, agent=agent)
    return any(((base / name).is_file() for name in expected))

def _ensure_workdir_skeleton(session_id: str | None=None, *, agent: str | None=None) -> None:
    """Create outbox/ and ledger/ if absent; inbox stays orchestrator-owned."""
    _outbox_dir(session_id, agent=agent).mkdir(parents=True, exist_ok=True)
    _ledger_dir(session_id, agent=agent).mkdir(parents=True, exist_ok=True)
from harness.hooks import _paths
from harness.hooks._env import _resolve_agent