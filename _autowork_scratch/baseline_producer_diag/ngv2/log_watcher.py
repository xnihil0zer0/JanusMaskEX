"""ngv2.log_watcher -- deterministic overseer log-rule engine.

Reads a JSONL progress window, applies three guarded rules
(``rate_limit``, ``critical_finding``, ``bash_failure_x3``) and emits
overseer signals.  Every external side effect is routed through an
injected ``sink`` callable, so the engine itself stays pure and is never
responsible for a live dispatch.  File I/O accepts an injected ``path``
so it can be exercised against a temporary directory.

stdlib only.
"""
from __future__ import annotations
import json
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence
WINDOW: int = 200
RATE_LIMIT_COOLDOWN_S: int = 300
BASH_FAIL_THRESHOLD: int = 3

def _parse_iso(value: Any) -> Optional[datetime]:
    """Parse an ISO-8601 string into a timezone-aware datetime, or None."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed

def _coerce_now(events: Sequence[Dict[str, Any]], now: Any=None) -> datetime:
    """Resolve the reference 'now'.

    Preference order: an explicitly injected clock, then the most recent
    timestamp carried by the event data, then the current wall clock used
    only for the documented cooldown comparison.
    """
    if isinstance(now, datetime):
        return now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    parsed = _parse_iso(now)
    if parsed is not None:
        return parsed
    latest: Optional[datetime] = None
    for event in events:
        if not isinstance(event, dict):
            continue
        for field_name in ('ts', 'timestamp', 'time'):
            candidate = _parse_iso(event.get(field_name))
            if candidate is not None and (latest is None or candidate > latest):
                latest = candidate
    if latest is not None:
        return latest
    wall = time.gmtime()
    return datetime(wall.tm_year, wall.tm_mon, wall.tm_mday, wall.tm_hour, wall.tm_min, wall.tm_sec, tzinfo=timezone.utc)

def _message(event: Dict[str, Any]) -> str:
    return str(event.get('message', '') or '')

def _phase(event: Dict[str, Any]) -> Optional[str]:
    return event.get('phase') or event.get('status')

def action_rate_limit_broadcast(sink: Optional[Callable[[Dict[str, Any]], Any]]=None, dry_run: bool=False, **_: Any) -> Dict[str, Any]:
    """Broadcast that the swarm is rate limited."""
    signal = {'signal': 'rate_limit_broadcast'}
    if not dry_run and sink is not None:
        sink(signal)
    return signal

def action_critical_dispatch(task_id: Any=None, sink: Optional[Callable[[Dict[str, Any]], Any]]=None, dry_run: bool=False, **_: Any) -> Dict[str, Any]:
    """Dispatch a worker to triage a critical finding."""
    signal = {'signal': 'dispatch', 'task_id': task_id}
    if not dry_run and sink is not None:
        sink(signal)
    return signal

def action_escalate(task_id: Any, fail_count: int, sink: Optional[Callable[[Dict[str, Any]], Any]]=None, dry_run: bool=False) -> Dict[str, Any]:
    """Emit an escalate signal for a repeatedly failing task."""
    signal = {'signal': 'escalate', 'task_id': task_id, 'failure_count': fail_count}
    if not dry_run and sink is not None:
        sink(signal)
    return signal
RULES: Dict[str, Callable[..., Any]] = {'rate_limit': action_rate_limit_broadcast, 'critical_finding': action_critical_dispatch, 'bash_failure_x3': action_escalate}

def read_recent_events(n: int=WINDOW, path: Any=None) -> List[Dict[str, Any]]:
    """Return up to the last ``n`` parsed JSON objects from a JSONL file.

    Blank and malformed lines are skipped silently; a missing file yields
    an empty list.
    """
    if path is None:
        return []
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            raw_lines = handle.readlines()
    except (OSError, ValueError):
        return []
    events: List[Dict[str, Any]] = []
    for line in raw_lines:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            events.append(json.loads(stripped))
        except (ValueError, TypeError):
            continue
    if n is None:
        return events
    return events[-n:]

def load_rate_limit_state(path: Any=None) -> Dict[str, Any]:
    """Load the rate-limit state JSON; a missing/invalid file yields ``{}``."""
    if path is None:
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}

def write_overseer_inbox(signal: Dict[str, Any], dry_run: bool=False, sink: Optional[Callable[[Dict[str, Any]], Any]]=None) -> Optional[Dict[str, Any]]:
    """Route an overseer signal to the injected ``sink``.

    A dry run is a no-op even when a sink is supplied.
    """
    if dry_run:
        return None
    if sink is not None:
        sink(signal)
    return signal

def failure_count(task_id: Any, events: Sequence[Dict[str, Any]]) -> int:
    """Count ``bash_failure`` events recorded for ``task_id``."""
    if task_id is None:
        return 0
    total = 0
    for event in events:
        if not isinstance(event, dict):
            continue
        if event.get('type') == 'bash_failure' and event.get('task_id') == task_id:
            total += 1
    return total

def apply_rules(events: Sequence[Dict[str, Any]], rate_state: Optional[Dict[str, Any]], sink: Optional[Callable[[Dict[str, Any]], Any]]=None, ctrl_state: Optional[Dict[str, Any]]=None, dry_run: bool=False, now: Any=None) -> Dict[str, int]:
    """Evaluate the three guarded rules and emit signals via ``sink``.

    Returns a mapping of rule name -> number of times it fired (after
    cooldown / dedup guards).  Side effects are only emitted when
    ``dry_run`` is false; cross-run guard state in ``ctrl_state`` is only
    mutated when ``dry_run`` is false and a ``ctrl_state`` dict is given.
    """
    events = [e for e in events or [] if isinstance(e, dict)]
    rate_state = rate_state or {}
    ctrl = ctrl_state if ctrl_state is not None else {}
    persist = ctrl_state is not None and (not dry_run)
    reference = _coerce_now(events, now)
    fired: Dict[str, int] = {}
    triggered = bool(rate_state.get('is_limited'))
    if not triggered:
        for event in events:
            if 'rate limit' in _message(event).lower():
                triggered = True
                break
    if triggered:
        broadcast_at = _parse_iso(ctrl.get('rate_limit_broadcast_at'))
        cooling = False
        if broadcast_at is not None:
            try:
                elapsed = (reference - broadcast_at).total_seconds()
            except TypeError:
                elapsed = float(RATE_LIMIT_COOLDOWN_S)
            if elapsed < RATE_LIMIT_COOLDOWN_S:
                cooling = True
        if not cooling:
            fired['rate_limit'] = 1
            RULES['rate_limit'](sink=sink, dry_run=dry_run)
            if persist:
                ctrl['rate_limit_broadcast_at'] = reference.isoformat()
    dispatched = ctrl.get('critical_dispatched') or {}
    critical_fired = 0
    handled_tasks = set()
    for event in events:
        if _phase(event) != 'finding':
            continue
        if 'critical' not in _message(event).lower():
            continue
        task_id = event.get('task_id')
        if str(task_id) in dispatched or task_id in handled_tasks:
            continue
        handled_tasks.add(task_id)
        critical_fired += 1
        RULES['critical_finding'](task_id=task_id, sink=sink, dry_run=dry_run)
        if persist:
            ctrl.setdefault('critical_dispatched', {})[str(task_id)] = reference.isoformat()
    if critical_fired:
        fired['critical_finding'] = critical_fired
    escalated = ctrl.get('bash_escalated') or []
    bash_fired = 0
    ordered_tasks: List[Any] = []
    for event in events:
        if event.get('type') != 'bash_failure':
            continue
        task_id = event.get('task_id')
        if task_id not in ordered_tasks:
            ordered_tasks.append(task_id)
    for task_id in ordered_tasks:
        count = failure_count(task_id, events)
        if count < BASH_FAIL_THRESHOLD:
            continue
        if task_id in escalated:
            continue
        bash_fired += 1
        RULES['bash_failure_x3'](task_id, count, sink=sink, dry_run=dry_run)
        if persist:
            ctrl.setdefault('bash_escalated', []).append(task_id)
    if bash_fired:
        fired['bash_failure_x3'] = bash_fired
    return fired