"""ngv2.portfolio_intel — pure portfolio intelligence over an injected data seam.

The legacy NobleGreed ``portfolio_intel`` tool read SQLite DBs, a YAML ledger,
JSON bounty files, and rendered rich terminal tables.  This NGv2 module keeps
only the *durable* capability: turning portfolio data (findings + workers +
revenue) into strategic-analytics dicts (revenue funnel, CWE heatmap, repo ROI,
worker efficiency, hunting recommendations).

All file / db / yaml / rich I/O is removed and replaced by an INJECTED DATA
SEAM: :func:`load_portfolio` consumes a plain ``dict`` (the seam) and returns a
:class:`PortfolioData`; the five renderers are PURE functions returning
JSON-serializable dicts.  No clock, no network, no randomness, no printing —
identical inputs always produce identical outputs.
"""
from __future__ import annotations
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
__all__ = ['Finding', 'WorkerRecord', 'PortfolioData', 'load_portfolio', 'render_funnel', 'render_cwe_heatmap', 'render_repos', 'render_workers', 'render_recommendations']

def _to_float(value: Any) -> float:
    """Coerce *value* to a finite float, returning 0.0 for None / NaN / junk."""
    if value is None:
        return 0.0
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        result = float(value)
        return 0.0 if math.isnan(result) or math.isinf(result) else result
    try:
        result = float(str(value).strip())
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if math.isnan(result) or math.isinf(result) else result

def _to_int(value: Any, default: int=0) -> int:
    """Coerce *value* to an int, returning *default* for None / junk."""
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default

def _to_bool(value: Any) -> bool:
    """Coerce *value* to a bool, understanding common truthy strings/ints."""
    if isinstance(value, str):
        return value.strip().lower() in {'1', 'true', 'yes', 'y', 't'}
    return bool(value)

def _to_str(value: Any, default: str='') -> str:
    return default if value is None else str(value)

def _parse_ts(value: Any) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp string; return None on failure (no clock)."""
    if not value:
        return None
    text = str(value).strip()
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    try:
        return datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None

@dataclass
class Finding:
    """A single security finding within the portfolio."""
    id: int = 0
    task_id: int = 0
    repo: str = ''
    cwe: str = ''
    severity: str = ''
    confidence: str = ''
    title: str = ''
    created_at: str = ''
    has_poc: bool = False
    has_live_test: bool = False
    has_submission: bool = False
    bounty_eligible: bool = False
    estimated_payout: float = 0.0

@dataclass
class WorkerRecord:
    """A single hunting/worker process record."""
    id: int = 0
    worker_type: str = ''
    pid: int = 0
    start_time: str = ''
    last_seen: str = ''
    status: str = ''
    exit_code: int = 0
    model: str = ''
    duration_minutes: float = 0.0

@dataclass
class PortfolioData:
    """The fully-coerced portfolio seam consumed by the pure renderers."""
    findings: List[Finding] = field(default_factory=list)
    workers: List[WorkerRecord] = field(default_factory=list)
    total_pending: float = 0.0
    total_confirmed: float = 0.0
    poc_files: int = 0
    test_files: int = 0
    submission_files: int = 0

def _build_finding(raw: Dict[str, Any]) -> Finding:
    return Finding(id=_to_int(raw.get('id')), task_id=_to_int(raw.get('task_id')), repo=_to_str(raw.get('repo')), cwe=_to_str(raw.get('cwe')), severity=_to_str(raw.get('severity')).upper(), confidence=_to_str(raw.get('confidence')).upper(), title=_to_str(raw.get('title')), created_at=_to_str(raw.get('created_at')), has_poc=_to_bool(raw.get('has_poc')), has_live_test=_to_bool(raw.get('has_live_test')), has_submission=_to_bool(raw.get('has_submission')), bounty_eligible=_to_bool(raw.get('bounty_eligible')), estimated_payout=_to_float(raw.get('estimated_payout')))

def _build_worker(raw: Dict[str, Any]) -> WorkerRecord:
    return WorkerRecord(id=_to_int(raw.get('id')), worker_type=_to_str(raw.get('worker_type')), pid=_to_int(raw.get('pid')), start_time=_to_str(raw.get('start_time')), last_seen=_to_str(raw.get('last_seen')), status=_to_str(raw.get('status')).lower(), exit_code=_to_int(raw.get('exit_code')), model=_to_str(raw.get('model')), duration_minutes=_to_float(raw.get('duration_minutes')))

def load_portfolio(source: Optional[dict]=None) -> PortfolioData:
    """Build a :class:`PortfolioData` from the injected *source* dict.

    ``source=None`` returns a default, empty instance — no I/O is performed.
    Finding severity/confidence are uppercased, worker status is lowercased,
    and all missing/None numeric fields are coerced to safe defaults.
    """
    if source is None:
        return PortfolioData()
    raw_findings = source.get('findings') or []
    raw_workers = source.get('workers') or []
    findings = [_build_finding(item) for item in raw_findings if isinstance(item, dict)]
    workers = [_build_worker(item) for item in raw_workers if isinstance(item, dict)]
    return PortfolioData(findings=findings, workers=workers, total_pending=_to_float(source.get('pending_usd')), total_confirmed=_to_float(source.get('confirmed_usd')), poc_files=_to_int(source.get('poc_files')), test_files=_to_int(source.get('test_files')), submission_files=_to_int(source.get('submission_files')))

def render_funnel(portfolio: PortfolioData) -> dict:
    """Aggregate the revenue funnel across all findings."""
    findings = portfolio.findings
    return {'total_findings': len(findings), 'with_poc': sum((1 for f in findings if f.has_poc)), 'with_test': sum((1 for f in findings if f.has_live_test)), 'with_submission': sum((1 for f in findings if f.has_submission)), 'bounty_eligible': sum((1 for f in findings if f.bounty_eligible)), 'total_estimated_value': sum((_to_float(f.estimated_payout) for f in findings)), 'pending_usd': portfolio.total_pending, 'confirmed_usd': portfolio.total_confirmed}

def render_cwe_heatmap(portfolio: PortfolioData) -> dict:
    """Group finding counts by CWE; empty/None/missing CWEs bucket to UNKNOWN."""
    counts: Counter = Counter()
    for f in portfolio.findings:
        cwe = (f.cwe or '').strip()
        counts[cwe if cwe else 'UNKNOWN'] += 1
    ordered = dict(sorted(counts.items(), key=lambda kv: -kv[1]))
    top_cwe = next(iter(ordered), None)
    return {'cwe_counts': ordered, 'top_cwe': top_cwe, 'unique_cwes': len(ordered)}

def render_repos(portfolio: PortfolioData) -> dict:
    """Track per-repository value and identify the top repo by payout."""
    payouts: Dict[str, float] = defaultdict(float)
    counts: Dict[str, int] = defaultdict(int)
    for f in portfolio.findings:
        repo = f.repo or ''
        payouts[repo] += _to_float(f.estimated_payout)
        counts[repo] += 1
    repos_with_value = sum((1 for repo in payouts if payouts[repo] > 0))
    top_repo: Optional[str] = None
    if payouts:
        top_repo = max(payouts, key=lambda r: (payouts[r], counts[r]))
    return {'total_repos': len(payouts), 'repos_with_value': repos_with_value, 'top_repo': top_repo}

def render_workers(portfolio: PortfolioData) -> dict:
    """Aggregate worker efficiency metrics; empty -> {'total_workers': 0}."""
    workers = portfolio.workers
    total = len(workers)
    if total == 0:
        return {'total_workers': 0}
    completed = sum((1 for w in workers if w.status == 'completed'))
    crashed = sum((1 for w in workers if w.status in {'crashed', 'failed'}))
    compute_minutes = sum((_to_float(w.duration_minutes) for w in workers if w.status == 'completed' and _to_float(w.duration_minutes) > 0.5))
    findings_count = len(portfolio.findings)
    recent = 0
    seen = [ts for ts in (_parse_ts(w.last_seen) for w in workers) if ts is not None]
    if seen:
        reference = max(seen)
        window = reference - timedelta(hours=24)
        recent = sum((1 for ts in seen if ts >= window))
    return {'total_workers': total, 'success_rate': round(completed / total * 100, 2), 'crash_rate': round(crashed / total * 100, 2), 'total_compute_hours': round(compute_minutes / 60, 1), 'findings_per_worker': round(findings_count / total, 2), 'recent_workers_24h': recent}

def render_recommendations(portfolio: PortfolioData) -> dict:
    """Generate prioritized strategic recommendations from the portfolio."""
    recommendations: List[Dict[str, Any]] = []
    ready_to_submit = [f for f in portfolio.findings if f.has_poc and f.has_live_test and f.bounty_eligible and (not f.has_submission)]
    if ready_to_submit:
        recommendations.append({'priority': 'P0', 'category': 'REVENUE', 'message': f'{len(ready_to_submit)} validated, bounty-eligible finding(s) have a PoC and live test but no submission — submit now.', 'count': len(ready_to_submit)})
    if portfolio.total_pending > 0 and portfolio.total_confirmed == 0:
        recommendations.append({'priority': 'P0', 'category': 'REVENUE', 'message': f'${portfolio.total_pending:.0f} pending with $0 confirmed — chase confirmations to realize revenue.', 'count': 1})
    needs_test = [f for f in portfolio.findings if f.bounty_eligible and f.has_poc and (not f.has_live_test)]
    if needs_test:
        recommendations.append({'priority': 'P1', 'category': 'QUALITY', 'message': f'{len(needs_test)} bounty-eligible finding(s) with a PoC lack a live test — add live verification to unlock submission.', 'count': len(needs_test)})
    recommendations.sort(key=lambda r: r['priority'])
    return {'recommendations': recommendations, 'total_recommendations': len(recommendations), 'p0_count': sum((1 for r in recommendations if r['priority'] == 'P0')), 'p1_count': sum((1 for r in recommendations if r['priority'] == 'P1'))}