"""Per-session append-only JSONL journal for hook events.

Replaces the MCP server's in-process counters (`self.submissions`,
`self.clarifications`, `self.plan_submitted`) with a file-based ledger at
`state/sessions/{agent}_{session_id}.ledger.jsonl`. Hooks are short-lived
processes; the ledger is their only memory.

Row schema (matches sub-plan 02 §10):
    {ts, session_id, agent, round, phase, hook, tool, verb, outcome,
     counters, digest, detail}

All fields are optional except `ts` — readers must tolerate missing keys
so schema evolution doesn't invalidate old rows.
"""
from __future__ import annotations
import datetime
import json
import pathlib
import sys
from typing import Any
from typing import Iterable
from harness._journal import write_jsonl_row
from . import _paths

def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

def ledger_path(session_id: str, agent: str | None=None) -> pathlib.Path:
    resolved_agent = agent or harness.hooks._paths.agent() or 'unknown'
    resolved_session = session_id or 'nosession'
    return harness.hooks._paths.state_dir() / 'sessions' / f'{resolved_agent}_{resolved_session}.ledger.jsonl'

def append_hook_event(session_id: str, agent: str, verb: str, outcome: str, *, hook: str='', tool: str='', round_number: int | None=None, phase: str='', counters: dict[str, Any] | None=None, digest: str='', detail: dict[str, Any] | None=None, path: pathlib.Path | None=None) -> dict[str, Any]:
    """Append one row; returns the row dict for the caller's convenience."""
    raise NotImplementedError

def read_events(session_id: str, agent: str | None=None, *, path: pathlib.Path | None=None) -> list[dict[str, Any]]:
    raise NotImplementedError

def count_verb(events: Iterable[dict[str, Any]], verb: str, *, outcome: str='allow') -> int:
    raise NotImplementedError

def has_verb(events: Iterable[dict[str, Any]], verb: str, *, outcome: str='allow') -> bool:
    raise NotImplementedError
import harness.hooks._paths