"""Gemini-worker env + workdir resolution shim (T2-3).

The implementation lives in ``harness.hooks._env`` (shared with claude);
this shim binds the ``agent="gemini"`` identity so existing importers
(``from . import _env``, ``from harness.hooks.gemini import _env``) keep
working without churn. Public surface is preserved byte-for-byte against
the pre-T2-3 module: ``work_dir``, ``inbox_dir``, ``outbox_dir``,
``ledger_dir``, ``expected_inbox_files``, ``inbox_ready``,
``ensure_workdir_skeleton``, ``INBOX_EXPECTATIONS``, and
``folder_trust_enabled`` (re-exported from
``harness.hooks.gemini._folder_trust``).

The per-session layout under the work dir is::

    $JANUSMASK_WORK_DIR/
        inbox/     # orchestrator-staged; task.json / brief.json / ...
        outbox/    # agent-written; submission.py, plan_draft.json, ...
        ledger/    # append-only hook_events.jsonl (sub-plan 02 §10)

``JANUSMASK_WORK_DIR`` is authoritative; when absent, the resolver falls
back to ``$JANUSMASK_STATE_DIR/workdirs/gemini/<session_id>`` so local
test fixtures can derive a stable path from the session id alone.
"""
from __future__ import annotations
import pathlib
from .. import _env as _shared
from ._folder_trust import _folder_trust_enabled as folder_trust_enabled
_AGENT = 'gemini'
_DEFAULT_WORKDIR_PREFIX = f'workdirs/{_AGENT}'
INBOX_EXPECTATIONS = _shared._INBOX_EXPECTATIONS

def work_dir(session_id: str | None=None) -> pathlib.Path:
    return harness.hooks._env._work_dir(session_id=session_id, agent='gemini')

def inbox_dir(session_id: str | None=None) -> pathlib.Path:
    raise NotImplementedError

def outbox_dir(session_id: str | None=None) -> pathlib.Path:
    raise NotImplementedError

def ledger_dir(session_id: str | None=None) -> pathlib.Path:
    raise NotImplementedError

def expected_inbox_files(mode: str) -> tuple[str, ...]:
    raise NotImplementedError

def inbox_ready(mode: str, session_id: str | None=None) -> bool:
    raise NotImplementedError

def ensure_workdir_skeleton(session_id: str | None=None) -> None:
    raise NotImplementedError
import harness.hooks._env