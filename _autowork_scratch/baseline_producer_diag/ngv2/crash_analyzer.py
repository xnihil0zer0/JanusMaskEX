"""ngv2.crash_analyzer — deterministic, stdlib-only worker-failure diagnostics.

This module ingests plain dict worker records (via an *injected* zero-arg
``source`` callable) and produces:

  * failure overviews (:func:`analyze_overview`),
  * root-cause pattern clusters (:func:`analyze_patterns`), and
  * rate-limit / failure cascade detections (:func:`detect_cascades`).

The real data source (a SQLite ``worker_registry`` plus a ``worker_progress``
JSONL stream) lives at NGv2 runtime.  To keep this module deterministic and
unit-testable, :func:`load_workers` takes the data source as a seam: a
zero-arg callable returning plain ``dict`` rows.  :func:`make_mock_source`
builds such a callable from an in-memory list of rows.

No wall-clock, network, randomness, or real database access happens here; any
"current time" used by the optional ``since_hours`` filter is supplied as an
explicit ``now_fn`` parameter so the same inputs always yield the same output.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Sequence
FAST_FAIL_THRESHOLD: int = 120
MID_FAIL_THRESHOLD: int = 600
CASCADE_MIN_FAILURES: int = 3
CASCADE_WINDOW_S: int = 300
_SEVERITY_CRITICAL = 0.3
_SEVERITY_HIGH = 0.15
_SEVERITY_MEDIUM = 0.05
_FAILED_STATUSES = ('failed', 'crashed')
ERROR_PATTERNS: Dict[str, List[str]] = dict([('rate_limit', ['rate limit', 'rate_limit', '429', 'too many requests', 'throttl', 'quota exceeded']), ('oom_memory', ['out of memory', 'oom', 'signal 9', 'killed', 'memoryerror', 'cannot allocate', 'oomkilled']), ('mcp_error', ['mcp', 'tool call failed', 'tool error']), ('git_error', ['merge conflict', 'git error', 'fatal: ', 'rebase', 'git pull', 'git push', 'detached head']), ('auth_error', ['unauthorized', 'forbidden', '401', '403', 'permission denied', 'authentication', 'credential']), ('network_error', ['connection refused', 'connection reset', 'network', 'timed out', 'timeout', 'dns', 'unreachable', 'socket']), ('import_error', ['importerror', 'modulenotfounderror', 'no module named', 'import error']), ('scope_creep', ['scope creep', 'scope_creep', 'out of scope', 'exceeded scope'])])

@dataclass
class WorkerRecord:
    """A single worker's lifecycle/diagnostic record."""
    id: int
    worker_type: str
    status: str
    start_time: str
    last_seen: str
    exit_code: Optional[int] = None
    model: Optional[str] = None
    task_type: Optional[str] = None
    task_target: Optional[str] = None
    duration_s: float = 0.0
    progress_messages: List[str] = field(default_factory=list)
    last_progress: Optional[str] = None
    failure_category: str = 'unknown'
    duration_bucket: str = 'unknown'

@dataclass
class CascadeEvent:
    """A burst of failures clustered tightly in time."""
    start_time: str
    end_time: str
    duration_s: float
    worker_count: int
    worker_types: List[str]
    worker_ids: List[int]
    avg_lifetime_s: float

@dataclass
class FailurePattern:
    """A cluster of failures sharing a root-cause category."""
    category: str
    count: int
    pct_of_failures: float
    worker_types: Dict[str, int]
    avg_duration_s: float
    exit_codes: Dict[str, int]
    example_messages: List[str]
    severity: str

@dataclass
class Remediation:
    """A suggested operator action."""
    priority: int
    category: str
    severity: str
    description: str
    impact: str
    fix: str
    affected_count: int

def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp into an aware ``datetime`` (or ``None``)."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt

def _duration_seconds(start: Optional[str], last: Optional[str]) -> float:
    """Elapsed seconds between two ISO timestamps (0.0 if not computable)."""
    a = _parse_ts(start)
    b = _parse_ts(last)
    if a is None or b is None:
        return 0.0
    return (b - a).total_seconds()

def _duration_bucket(duration_s: float) -> str:
    """Bucket a duration into fast / mid / slow failure bands."""
    if duration_s < FAST_FAIL_THRESHOLD:
        return 'fast_fail_<2m'
    if duration_s < MID_FAIL_THRESHOLD:
        return 'mid_fail_2-10m'
    return 'slow_fail_>10m'

def classify_failure(messages: Sequence[str]) -> str:
    """Return the failure category matching ``messages``, else ``"unknown"``.

    Each message is matched case-insensitively against :data:`ERROR_PATTERNS`;
    categories are tried in insertion order and the first match wins.
    """
    if not messages:
        return 'unknown'
    haystack = ' \n'.join((m for m in messages if m)).lower()
    if not haystack:
        return 'unknown'
    for category, patterns in ERROR_PATTERNS.items():
        for pattern in patterns:
            if pattern in haystack:
                return category
    return 'unknown'

def make_mock_source(rows: Sequence[dict]) -> Callable[[], List[dict]]:
    """Build a zero-arg ``source`` callable returning a copy of ``rows``."""
    snapshot = [dict(r) for r in rows]

    def _source() -> List[dict]:
        return [dict(r) for r in snapshot]
    return _source

def load_workers(source: Optional[Callable[[], Sequence[dict]]], worker_type: Optional[str]=None, status_filter: Optional[Sequence[str]]=None, since_hours: Optional[float]=None, now_fn: Optional[Callable[[], datetime]]=None) -> List[WorkerRecord]:
    """Load and normalise worker rows from the injected ``source``.

    Rows are mapped to :class:`WorkerRecord` objects with computed durations
    and buckets, optionally filtered by ``worker_type`` / ``status_filter`` /
    ``since_hours`` (the latter requires ``now_fn``), and returned sorted by
    ``id`` descending.  ``source is None`` yields an empty list.
    """
    if source is None:
        return []
    rows = source() or []
    allowed_status = set(status_filter) if status_filter is not None else None
    cutoff: Optional[datetime] = None
    if since_hours is not None and now_fn is not None:
        from datetime import timedelta
        cutoff = now_fn() - timedelta(hours=since_hours)
    workers: List[WorkerRecord] = []
    for row in rows:
        wtype = row.get('worker_type')
        if worker_type is not None and wtype != worker_type:
            continue
        status = row.get('status')
        if allowed_status is not None and status not in allowed_status:
            continue
        start_time = row.get('start_time')
        last_seen = row.get('last_seen') or start_time
        if cutoff is not None:
            seen = _parse_ts(last_seen)
            if seen is not None and seen < cutoff:
                continue
        messages = list(row.get('progress_messages') or [])
        last_progress = row.get('last_progress')
        if last_progress is None and messages:
            last_progress = messages[-1]
        duration_s = _duration_seconds(start_time, last_seen)
        record = WorkerRecord(id=row.get('id'), worker_type=wtype, status=status, start_time=start_time, last_seen=last_seen, exit_code=row.get('exit_code'), model=row.get('model'), task_type=row.get('task_type'), task_target=row.get('task_target'), duration_s=duration_s, progress_messages=messages, last_progress=last_progress, failure_category=classify_failure(messages), duration_bucket=_duration_bucket(duration_s))
        workers.append(record)
    workers.sort(key=lambda w: (w.id is None, w.id), reverse=True)
    return workers

def analyze_overview(workers: Sequence[WorkerRecord]) -> Dict[str, object]:
    """Summarise overall and per-type worker outcomes."""
    total = len(workers)
    completed = sum((1 for w in workers if w.status == 'completed'))
    failed = sum((1 for w in workers if w.status == 'failed'))
    crashed = sum((1 for w in workers if w.status == 'crashed'))
    running = sum((1 for w in workers if w.status == 'running'))
    failure_rate = (failed + crashed) / total if total else 0
    type_rates: Dict[str, Dict[str, float]] = {}
    type_totals: Dict[str, int] = {}
    type_completed: Dict[str, int] = {}
    type_failed: Dict[str, int] = {}
    for w in workers:
        type_totals[w.worker_type] = type_totals.get(w.worker_type, 0) + 1
        if w.status == 'completed':
            type_completed[w.worker_type] = type_completed.get(w.worker_type, 0) + 1
        if w.status in _FAILED_STATUSES:
            type_failed[w.worker_type] = type_failed.get(w.worker_type, 0) + 1
    for wtype, count in type_totals.items():
        type_rates[wtype] = {'total': count, 'success_rate': type_completed.get(wtype, 0) / count if count else 0, 'failure_rate': type_failed.get(wtype, 0) / count if count else 0}
    duration_buckets: Dict[str, int] = {}
    for w in workers:
        duration_buckets[w.duration_bucket] = duration_buckets.get(w.duration_bucket, 0) + 1
    exit_codes: Dict[str, int] = {}
    for w in workers:
        if w.status in _FAILED_STATUSES and w.exit_code is not None:
            label = str(w.exit_code)
            exit_codes[label] = exit_codes.get(label, 0) + 1
    model_stats: Dict[str, Dict[str, float]] = {}
    model_total: Dict[str, int] = {}
    model_failed: Dict[str, int] = {}
    for w in workers:
        ident = w.model if w.model is not None else 'unknown'
        model_total[ident] = model_total.get(ident, 0) + 1
        if w.status in _FAILED_STATUSES:
            model_failed[ident] = model_failed.get(ident, 0) + 1
    for ident, count in model_total.items():
        model_stats[ident] = {'total': count, 'failed': model_failed.get(ident, 0), 'failure_rate': model_failed.get(ident, 0) / count if count else 0}
    return {'total_workers': total, 'completed': completed, 'failed': failed, 'crashed': crashed, 'running': running, 'failure_rate': failure_rate, 'type_rates': type_rates, 'duration_buckets': duration_buckets, 'exit_codes': exit_codes, 'model_stats': model_stats}

def _severity_for_pct(pct: float) -> str:
    """Map a fraction-of-failures to a severity label."""
    if pct > _SEVERITY_CRITICAL:
        return 'critical'
    if pct > _SEVERITY_HIGH:
        return 'high'
    if pct > _SEVERITY_MEDIUM:
        return 'medium'
    return 'low'

def analyze_patterns(workers: Sequence[WorkerRecord]) -> List[FailurePattern]:
    """Cluster failures by ``failure_category`` into :class:`FailurePattern`s."""
    failures = [w for w in workers if w.status in _FAILED_STATUSES]
    total_failures = len(failures)
    if total_failures == 0:
        return []
    grouped: Dict[str, List[WorkerRecord]] = {}
    for w in failures:
        grouped.setdefault(w.failure_category, []).append(w)
    patterns: List[FailurePattern] = []
    for category, group in grouped.items():
        count = len(group)
        pct = count / total_failures
        worker_types: Dict[str, int] = {}
        exit_codes: Dict[str, int] = {}
        example_messages: List[str] = []
        total_duration = 0.0
        for w in group:
            worker_types[w.worker_type] = worker_types.get(w.worker_type, 0) + 1
            if w.exit_code is not None:
                label = str(w.exit_code)
                exit_codes[label] = exit_codes.get(label, 0) + 1
            total_duration += w.duration_s
            if w.last_progress and len(example_messages) < 3:
                example_messages.append(w.last_progress)
        patterns.append(FailurePattern(category=category, count=count, pct_of_failures=pct, worker_types=worker_types, avg_duration_s=total_duration / count if count else 0.0, exit_codes=exit_codes, example_messages=example_messages, severity=_severity_for_pct(pct)))
    patterns.sort(key=lambda p: (-p.count, p.category))
    return patterns

def detect_cascades(workers: Sequence[WorkerRecord]) -> List[CascadeEvent]:
    """Detect bursts of failures clustered within :data:`CASCADE_WINDOW_S`."""
    failures = [w for w in workers if w.status in _FAILED_STATUSES]
    ordered = sorted((w for w in failures if _parse_ts(w.start_time) is not None), key=lambda w: _parse_ts(w.start_time))
    cascades: List[CascadeEvent] = []
    cluster: List[WorkerRecord] = []
    cluster_start: Optional[datetime] = None

    def _flush(group: List[WorkerRecord]) -> None:
        if len(group) < CASCADE_MIN_FAILURES:
            return
        first = _parse_ts(group[0].start_time)
        last = _parse_ts(group[-1].start_time)
        span = (last - first).total_seconds() if first and last else 0.0
        types: List[str] = []
        for w in group:
            if w.worker_type not in types:
                types.append(w.worker_type)
        avg_lifetime = sum((w.duration_s for w in group)) / len(group)
        cascades.append(CascadeEvent(start_time=group[0].start_time, end_time=group[-1].start_time, duration_s=span, worker_count=len(group), worker_types=types, worker_ids=[w.id for w in group], avg_lifetime_s=avg_lifetime))
    for w in ordered:
        ts = _parse_ts(w.start_time)
        if cluster_start is None:
            cluster = [w]
            cluster_start = ts
            continue
        if (ts - cluster_start).total_seconds() <= CASCADE_WINDOW_S:
            cluster.append(w)
        else:
            _flush(cluster)
            cluster = [w]
            cluster_start = ts
    if cluster:
        _flush(cluster)
    return cascades