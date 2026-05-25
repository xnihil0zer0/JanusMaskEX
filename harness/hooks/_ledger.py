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
    target = path or ledger_path(session_id, agent)
    row: dict[str, Any] = {'ts': _now_iso(), 'session_id': session_id, 'agent': agent, 'round': round_number, 'phase': phase, 'hook': hook, 'tool': tool, 'verb': verb, 'outcome': outcome, 'counters': counters if counters is not None else {}, 'digest': digest, 'detail': detail if detail is not None else {}}
    write_jsonl_row(target, row)
    return row

def read_events(session_id: str, agent: str | None=None, *, path: pathlib.Path | None=None) -> list[dict[str, Any]]:
    target = path or ledger_path(session_id, agent)
    if not target.exists():
        return []
    events: list[dict[str, Any]] = []
    try:
        with open(target, 'r', encoding='utf-8') as f:
            for idx, line in enumerate(f, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    events.append(json.loads(stripped))
                except json.JSONDecodeError as e:
                    print(f'_ledger read_events JSON decode error in {target} at line {idx}: {e}', file=sys.stderr)
    except FileNotFoundError:
        return []
    return events

def count_verb(events: Iterable[dict[str, Any]], verb: str, *, outcome: str='allow') -> int:
    """Tally events whose ``verb`` and ``outcome`` match, tolerating rows that omit either key."""
    return sum((1 for e in events if e.get('verb') == verb and e.get('outcome') == outcome))

def has_verb(events: Iterable[dict[str, Any]], verb: str, *, outcome: str='allow') -> bool:
    raise NotImplementedError
import harness.hooks._paths