"""Pure, deterministic parser for NobleGreed execution-log entries.

This module turns raw execution-log entries (plain ``dict`` objects) into
structured RLCF training signals:

* :func:`infer_outcome` -- pass / fail / unknown classification,
* :func:`infer_hypothesis_category` -- VISTA hypothesis bucketing,
* :func:`infer_failure_mode` -- a short failure-mode label,
* :func:`build_trace_text` -- a deterministic human-readable trace string,
* :func:`group_into_sessions` -- session/run grouping of an entry sequence.

It is intentionally *pure*: standard-library only, no file/network I/O, no
randomness, no real-clock reads, and no persistent mutable module state. It
imports nothing from sibling Epic-4 leaves (e.g. ``rl_debate_weights``).
"""
from __future__ import annotations
from typing import Any, Dict, FrozenSet, List, Mapping, Optional, Sequence, Tuple
__all__ = ['infer_outcome', 'infer_hypothesis_category', 'infer_failure_mode', 'build_trace_text', 'group_into_sessions', 'PASS_EVENTS', 'FAIL_EVENTS', 'PASS_STATUSES', 'FAIL_STATUSES', 'FAILURE_TO_HYPOTHESIS']
PASS_EVENTS: FrozenSet[str] = frozenset({'complete', 'loop_complete', 'iteration_complete', 'handoff', 'task_complete', 'phase_complete', 'submission_queued'})
FAIL_EVENTS: FrozenSet[str] = frozenset({'worker_failed', 'worker_failure', 'worker_silent_exit', 'assertion_failed', 'error', 'crash'})
PASS_STATUSES: FrozenSet[str] = frozenset({'complete', 'ready_to_submit', 'submitted'})
FAIL_STATUSES: FrozenSet[str] = frozenset({'failed', 'error', 'blocked', 'crashed'})
FAILURE_TO_HYPOTHESIS: Dict[str, List[str]] = {'context_management': ['context', 'context_overflow', 'token limit', 'compaction', 'out of memory', 'oom', 'silent_exit'], 'tool_usage': ['tool', 'command not found', 'invalid tool', 'missing argument', 'subprocess', 'shell'], 'gate_skip': ['gate', 'skip', 'bypass', 'audit skipped', 'no review'], 'silent_exit': ['no output', 'exited without output', 'no heartbeat', 'silently exited', 'empty response', 'exit code 0'], 'timeout': ['timeout', 'timed out', 'deadline exceeded', 'exceeded time', 'hung', 'stalled'], 'respawn_loop': ['respawn', 'restart loop', 'watchdog respawn', 'reincarnat'], 'queue_corruption': ['queue', 'corrupt', 'duplicate submission', 'submission lost', 'db locked'], 'logging_gap': ['no logs', 'logging gap', 'missing log', 'log truncated', 'no trace']}
ERROR_SIGNATURES: Tuple[str, ...] = ('traceback', 'error', 'exception', 'raise', 'fatal', 'panic', 'segfault')
_TEXT_FIELDS: Tuple[str, ...] = ('error', 'message', 'traceback')

def _normalize(value: Any) -> str:
    """Return ``value`` as a stripped, lowercased string ("" when falsy)."""
    if value is None:
        return ''
    return str(value).strip().lower()

def _has_error_signature(text: str) -> bool:
    """True when *text* contains any known error signature (case-insensitive)."""
    lowered = text.lower()
    return any((sig in lowered for sig in ERROR_SIGNATURES))

def _hypothesis_blob(entry: Mapping[str, Any]) -> str:
    """Build the lowercase text blob consulted for hypothesis matching."""
    parts: List[str] = []
    for field_name in ('event', 'error', 'message', 'traceback'):
        value = entry.get(field_name)
        if value:
            parts.append(str(value))
    failure_mode = infer_failure_mode(entry)
    if failure_mode:
        parts.append(failure_mode)
    return ' '.join(parts).lower()

def _format_entry_line(entry: Mapping[str, Any]) -> str:
    """Render a single log entry into one deterministic trace line."""
    parts: List[str] = []
    timestamp = entry.get('timestamp')
    if timestamp:
        parts.append(str(timestamp)[:19])
    component = entry.get('component')
    if component:
        parts.append('[{0}]'.format(component))
    event = entry.get('event')
    if event:
        parts.append(str(event))
    phase = entry.get('phase')
    if phase:
        parts.append('phase={0}'.format(phase))
    status = entry.get('status')
    if status and _normalize(status) not in ('', 'unknown'):
        parts.append('status={0}'.format(status))
    message = entry.get('message')
    if message:
        parts.append(str(message))
    error = entry.get('error')
    if error:
        parts.append('ERROR: {0}'.format(error))
    return ' '.join(parts)

def _session_key(entry: Mapping[str, Any]) -> str:
    """Derive the session/run identity key for an entry."""
    parts: List[str] = []
    component = entry.get('component')
    if component:
        parts.append(str(component))
    task_id = entry.get('task_id')
    if task_id:
        parts.append(str(task_id))
    if parts:
        return '_'.join(parts)
    worker_type = entry.get('worker_type')
    if worker_type:
        return str(worker_type)
    return 'unknown'

def infer_outcome(entry: Mapping[str, Any]) -> str:
    """Classify a single log *entry* as ``"pass"``, ``"fail"`` or ``"unknown"``.

    Precedence:

    1. An explicit ``status`` (normalized) found in :data:`PASS_STATUSES` /
       :data:`FAIL_STATUSES` wins over everything else.
    2. Otherwise an ``event`` in :data:`PASS_EVENTS` / :data:`FAIL_EVENTS`.
    3. Otherwise ``phase == "submit"`` with a truthy ``task_id`` is a pass.
    4. Otherwise an error signature in the free-text fields is a fail.
    5. Otherwise ``"unknown"``.
    """
    status = _normalize(entry.get('status'))
    if status:
        if status in PASS_STATUSES:
            return 'pass'
        if status in FAIL_STATUSES:
            return 'fail'
    event = _normalize(entry.get('event'))
    if event:
        if event in PASS_EVENTS:
            return 'pass'
        if event in FAIL_EVENTS:
            return 'fail'
    if _normalize(entry.get('phase')) == 'submit' and entry.get('task_id'):
        return 'pass'
    for field_name in _TEXT_FIELDS:
        value = entry.get(field_name)
        if value and _has_error_signature(str(value)):
            return 'fail'
    return 'unknown'

def infer_failure_mode(entry: Mapping[str, Any]) -> Optional[str]:
    """Return a short failure-mode label for *entry*, or ``None`` when none.

    * A ``event`` in :data:`FAIL_EVENTS` with a truthy ``error`` yields
      ``"<event>: <error[:100]>"``.
    * A ``event`` in :data:`FAIL_EVENTS` without an error yields the bare event.
    * Otherwise a truthy ``error`` yields ``str(error)[:150]``.
    * Otherwise ``None`` (the non-failing sentinel).
    """
    event = entry.get('event')
    error = entry.get('error')
    if _normalize(event) in FAIL_EVENTS:
        if error:
            return '{0}: {1}'.format(event, str(error)[:100])
        return str(event)
    if error:
        return str(error)[:150]
    return None

def infer_hypothesis_category(entry: Mapping[str, Any]) -> str:
    """Return the VISTA hypothesis category for *entry*.

    Driven by the inferred failure mode plus the entry's free-text fields:
    the first category in :data:`FAILURE_TO_HYPOTHESIS` with a matching
    signature wins. Returns ``"unknown"`` when nothing matches.
    """
    blob = _hypothesis_blob(entry)
    if blob:
        for category, signatures in FAILURE_TO_HYPOTHESIS.items():
            for signature in signatures:
                if signature in blob:
                    return category
    return 'unknown'

def build_trace_text(entries: Sequence[Mapping[str, Any]], max_lines: Optional[int]=None) -> str:
    """Render *entries* into a deterministic, human-readable trace string.

    Each entry becomes at most one line; empty entries contribute nothing.
    Timestamps are truncated to seconds (first 19 characters); ``status`` is
    suppressed when empty or ``"unknown"``; errors are rendered ``ERROR: ...``.
    When *max_lines* is given, at most that many non-empty lines are produced.
    """
    lines: List[str] = []
    for entry in entries:
        line = _format_entry_line(entry)
        if line:
            lines.append(line)
            if max_lines is not None and len(lines) >= max_lines:
                break
    return '\n'.join(lines)

def group_into_sessions(entries: Sequence[Mapping[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Group *entries* into sessions keyed by ``component``/``task_id``.

    The session key is ``"<component>_<task_id>"`` when both are present,
    falling back to ``component``, then ``worker_type``, then ``"unknown"``.
    Entries within each session are sorted ascending by ``timestamp``. The
    input sequence and its dicts are never mutated.
    """
    sessions: Dict[str, List[Dict[str, Any]]] = {}
    for entry in entries:
        key = _session_key(entry)
        sessions.setdefault(key, []).append(dict(entry))
    for grouped in sessions.values():
        grouped.sort(key=lambda item: str(item.get('timestamp') or ''))
    return sessions