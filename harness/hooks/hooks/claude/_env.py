"""Claude-worker env + workdir resolution shim (T2-3).

The implementation lives in ``harness.hooks._env`` (shared with gemini);
this shim binds the ``agent="claude"`` identity so existing importers
(``from . import _env``, ``from harness.hooks.claude import _env``) keep
working without churn. Public surface is preserved byte-for-byte against
the pre-T2-3 module: ``work_dir``, ``inbox_dir``, ``outbox_dir``,
``ledger_dir``, ``expected_inbox_files``, ``inbox_ready``,
``ensure_workdir_skeleton``, ``INBOX_EXPECTATIONS``.

The per-session layout under the work dir is::

    $JANUSMASK_WORK_DIR/
        inbox/     # orchestrator-staged; task.json / brief.json / ...
        outbox/    # agent-written; submission.py, plan_draft.json, ...
        ledger/    # append-only hook_events.jsonl (sub-plan 02 §10)

``JANUSMASK_WORK_DIR`` is authoritative; when absent, the resolver falls
back to ``$JANUSMASK_STATE_DIR/workdirs/claude/<session_id>`` so local
test fixtures can derive a stable path from the session id alone.
"""

from __future__ import annotations

import pathlib

from .. import _env as _shared

_AGENT = "claude"
_DEFAULT_WORKDIR_PREFIX = f"workdirs/{_AGENT}"

INBOX_EXPECTATIONS = _shared._INBOX_EXPECTATIONS


def work_dir(session_id: str | None = None) -> pathlib.Path:
    return _shared._work_dir(session_id, agent=_AGENT)


def inbox_dir(session_id: str | None = None) -> pathlib.Path:
    return _shared._inbox_dir(session_id, agent=_AGENT)


def outbox_dir(session_id: str | None = None) -> pathlib.Path:
    return _shared._outbox_dir(session_id, agent=_AGENT)


def ledger_dir(session_id: str | None = None) -> pathlib.Path:
    return _shared._ledger_dir(session_id, agent=_AGENT)


def expected_inbox_files(mode: str) -> tuple[str, ...]:
    return _shared._expected_inbox_files(mode)


def inbox_ready(mode: str, session_id: str | None = None) -> bool:
    """True iff at least one expected inbox file exists for `mode`.

    Unknown modes return False so the caller can surface a loud stop
    reason rather than silently continuing with an unstaged worker.
    """
    return _shared._inbox_ready(mode, session_id, agent=_AGENT)


def ensure_workdir_skeleton(session_id: str | None = None) -> None:
    """Create outbox/ and ledger/ if absent; inbox stays orchestrator-owned."""
    _shared._ensure_workdir_skeleton(session_id, agent=_AGENT)
