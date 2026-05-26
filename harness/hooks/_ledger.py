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
    agent = agent or _paths.agent() or 'unknown'
    safe_session = session_id or 'nosession'
    return _paths.state_dir() / 'sessions' / f'{agent}_{safe_session}.ledger.jsonl'

def append_hook_event(session_id: str, agent: str, verb: str, outcome: str, *, hook: str='', tool: str='', round_number: int | None=None, phase: str='', counters: dict[str, Any] | None=None, digest: str='', detail: dict[str, Any] | None=None, path: pathlib.Path | None=None) -> dict[str, Any]:
    """Append one row; returns the row dict for the caller's convenience."""
    target = path or ledger_path(session_id, agent)
    row: dict[str, Any] = {'ts': _now_iso(), 'session_id': session_id, 'agent': agent, 'round': round_number, 'phase': phase, 'hook': hook, 'tool': tool, 'verb': verb, 'outcome': outcome, 'counters': counters or {}, 'digest': digest, 'detail': detail or {}}
    write_jsonl_row(target, row)
    return row

def read_events(session_id: str, agent: str | None=None, *, path: pathlib.Path | None=None) -> list[dict[str, Any]]:
    target = path or ledger_path(session_id, agent or _paths.agent())
    if not target.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line_num, raw in enumerate(target.read_text(encoding='utf-8').splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            sys.stderr.write(f'_ledger read_events JSON decode error at {target} line {line_num}: {exc}\n')
            continue
    return rows

def count_verb(events: Iterable[dict[str, Any]], verb: str, *, outcome: str='allow') -> int:
    return sum((1 for r in events if r.get('verb') == verb and (not outcome or r.get('outcome') == outcome)))

def has_verb(events: Iterable[dict[str, Any]], verb: str, *, outcome: str='allow') -> bool:
    return count_verb(events, verb, outcome=outcome) > 0