"""Pure, deterministic operational-analytics engine for ngv2.

Distilled from the legacy NobleGreed ``ops_analytics`` CLI tool, stripped of
every impure dependency (sqlite, yaml, wall-clock, argparse, printing). What
remains is the durable analytical capability: pure functions over plain
``list[dict]`` / ``dict`` inputs that produce five analytics dataclasses.

There is no database, no yaml, no wall-clock, no network, and no randomness —
every input is supplied by the caller, so every output is reproducible. Only
the Python standard library is used.
"""
from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass, field
from statistics import mean
from typing import Dict, List, Optional
SEVERITY_ORDER: Dict[str, int] = {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3}
PAYOUT_MULTIPLIERS: Dict[str, float] = {'critical': 1.0, 'high': 0.5, 'medium': 0.08, 'low': 0.01}
_DEFAULT_MULTIPLIER = 0.05
_POC_DONE = ('complete', 'verified')

@dataclass
class WorkerStats:
    worker_type: str
    total: int = 0
    completed: int = 0
    failed: int = 0
    crashed: int = 0
    running: int = 0
    success_rate: float = 0.0
    avg_duration_min: float = 0.0
    findings_produced: int = 0
    findings_per_worker: float = 0.0

@dataclass
class RepoStats:
    repo: str
    findings_count: int = 0
    eligible: bool = False
    max_payout: int = 0
    total_potential: int = 0
    cwes: List[str] = field(default_factory=list)
    severities: Dict[str, int] = field(default_factory=dict)
    has_poc_count: int = 0
    has_report_count: int = 0

@dataclass
class PipelineStage:
    name: str
    count: int = 0
    pct: float = 0.0

@dataclass
class Bottleneck:
    area: str
    severity: str
    metric: str
    value: str
    recommendation: str

@dataclass
class Recommendation:
    priority: int
    action: str
    rationale: str
    expected_impact: str

def _to_float(value: object) -> Optional[float]:
    """Best-effort conversion to ``float``; returns ``None`` on failure."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

def _to_int(value: object, default: int=0) -> int:
    """Best-effort conversion to ``int``; returns ``default`` on failure."""
    if value is None or isinstance(value, bool):
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default

def analyze_workers(workers: List[dict], tasks: Optional[List[dict]]=None) -> Dict[str, WorkerStats]:
    """Roll up worker records grouped by ``worker_type``.

    Counts completed/failed/crashed/running by ``status``, computes a success
    rate over finished work and an average duration over positive durations.
    When ``tasks`` is supplied, enriches each group with findings totals.
    """
    grouped: Dict[str, List[dict]] = defaultdict(list)
    for worker in workers:
        grouped[worker.get('worker_type')].append(worker)
    stats: Dict[str, WorkerStats] = {}
    for worker_type, members in grouped.items():
        ws = WorkerStats(worker_type=worker_type, total=len(members))
        durations: List[float] = []
        for member in members:
            status = member.get('status')
            if status == 'completed':
                ws.completed += 1
            elif status == 'failed':
                ws.failed += 1
            elif status == 'crashed':
                ws.crashed += 1
            elif status == 'running':
                ws.running += 1
            dur = _to_float(member.get('duration_min'))
            if dur is not None and dur > 0:
                durations.append(dur)
        finished = ws.completed + ws.failed + ws.crashed
        if finished > 0:
            ws.success_rate = round(ws.completed / finished * 100, 1)
        if durations:
            ws.avg_duration_min = round(mean(durations), 1)
        stats[worker_type] = ws
    if tasks:
        produced: Dict[str, int] = defaultdict(int)
        for task in tasks:
            produced[task.get('worker_type')] += _to_int(task.get('findings_count'))
        for worker_type, ws in stats.items():
            ws.findings_produced = produced.get(worker_type, 0)
            if ws.completed > 0:
                ws.findings_per_worker = round(ws.findings_produced / ws.completed, 2)
    return stats

def analyze_repos(findings: List[dict], bounties: dict) -> List[RepoStats]:
    """Roll up findings grouped by lowercased repository name.

    Projects a potential payout per eligible repo, preferring observed payouts
    over a severity multiplier. The input ``findings`` list is never mutated.
    """
    grouped: Dict[str, List[dict]] = defaultdict(list)
    for finding in findings:
        repo = str(finding.get('repo') or '').strip().lower()
        if not repo:
            continue
        grouped[repo].append(finding)
    results: List[RepoStats] = []
    for repo, members in grouped.items():
        bounty = bounties.get(repo, {}) or {}
        eligible = bool(bounty.get('eligible'))
        max_payout = _to_int(bounty.get('max_paid', 0))
        observed = bounty.get('observed_payouts', {}) or {}
        rs = RepoStats(repo=repo, findings_count=len(members), eligible=eligible, max_payout=max_payout)
        cwes: set = set()
        total_potential = 0
        for finding in members:
            sev_upper = str(finding.get('severity') or 'UNKNOWN').upper()
            rs.severities[sev_upper] = rs.severities.get(sev_upper, 0) + 1
            cwe = str(finding.get('cwe') or '').strip()
            if cwe:
                cwes.add(cwe)
            if finding.get('poc_status') in _POC_DONE:
                rs.has_poc_count += 1
            if finding.get('bounty_eligible'):
                rs.has_report_count += 1
            if eligible:
                sev = sev_upper.lower()
                obs = observed.get(sev)
                if obs:
                    total_potential += _to_int(obs)
                else:
                    multiplier = PAYOUT_MULTIPLIERS.get(sev, _DEFAULT_MULTIPLIER)
                    total_potential += int(max_payout * multiplier)
        rs.cwes = sorted(cwes)
        rs.total_potential = total_potential
        results.append(rs)
    results.sort(key=lambda r: (-r.total_potential, -r.findings_count, r.repo))
    return results

def analyze_pipeline(progress: List[dict]) -> List[PipelineStage]:
    """Count non-empty pipeline phases and compute their share of the total."""
    counts: Dict[str, int] = defaultdict(int)
    for entry in progress:
        phase = str(entry.get('phase') or '').strip()
        if not phase:
            continue
        counts[phase] += 1
    total = sum(counts.values())
    if total < 1:
        return []
    stages = [PipelineStage(name=phase, count=count, pct=round(count / total * 100, 1)) for phase, count in counts.items()]
    stages.sort(key=lambda s: (-s.count, s.name))
    return stages

def identify_bottlenecks(worker_stats: Dict[str, WorkerStats], repo_stats: List[RepoStats], pipeline_stages: List[PipelineStage], state: dict, progress: List[dict], pending_usd: int=0) -> List[Bottleneck]:
    """Detect operational bottlenecks, sorted by severity (worst first)."""
    bottlenecks: List[Bottleneck] = []
    for ws in worker_stats.values():
        if ws.total >= 5 and ws.success_rate < 50:
            severity = 'CRITICAL' if ws.success_rate < 25 else 'HIGH'
            bottlenecks.append(Bottleneck(area='worker_reliability', severity=severity, metric=f'{ws.worker_type} success_rate', value=f'{ws.success_rate}%', recommendation=f"Investigate failing '{ws.worker_type}' workers; success rate is below 50%."))
    total_workers = sum((ws.total for ws in worker_stats.values()))
    total_crashed = sum((ws.crashed for ws in worker_stats.values()))
    crash_pct = total_crashed / total_workers * 100 if total_workers else 0
    if total_workers > 10 and crash_pct > 10:
        bottlenecks.append(Bottleneck(area='system_stability', severity='HIGH', metric='crash_pct', value=f'{round(crash_pct, 1)}%', recommendation='Stabilise the runtime; crash rate exceeds 10%.'))
    revenue_total = state.get('operation_goals', {}).get('revenue_total_usd', 0)
    if pending_usd > 0 and revenue_total == 0:
        bottlenecks.append(Bottleneck(area='revenue_pipeline', severity='CRITICAL', metric='pending_usd', value=f'${pending_usd}', recommendation='Convert pending findings into booked revenue.'))
    eligible = [r for r in repo_stats if r.eligible]
    ineligible = [r for r in repo_stats if not r.eligible]
    if len(ineligible) > len(eligible) * 2 and len(ineligible) > 5:
        bottlenecks.append(Bottleneck(area='target_selection', severity='MEDIUM', metric='ineligible_repos', value=str(len(ineligible)), recommendation='Refocus hunting on bounty-eligible repositories.'))
    if len(progress) > 50:
        missing = sum((1 for entry in progress if not entry.get('status')))
        if missing > len(progress) * 0.5:
            bottlenecks.append(Bottleneck(area='observability', severity='MEDIUM', metric='missing_status', value=str(missing), recommendation='Emit a status on every progress entry.'))
    bottlenecks.sort(key=lambda b: SEVERITY_ORDER.get(b.severity, 9))
    return bottlenecks

def generate_recommendations(worker_stats: Dict[str, WorkerStats], repo_stats: List[RepoStats], bottlenecks: List[Bottleneck], state: dict, pending_usd: int=0) -> List[Recommendation]:
    """Produce densely-prioritised recommendations in emission order."""
    recommendations: List[Recommendation] = []
    priority = 1

    def _emit(action: str, rationale: str, expected_impact: str) -> None:
        nonlocal priority
        recommendations.append(Recommendation(priority=priority, action=action, rationale=rationale, expected_impact=expected_impact))
        priority += 1
    if pending_usd > 0:
        _emit(action='Submit READY findings', rationale=f'${pending_usd} of payouts is pending submission.', expected_impact=f'Unlock up to ${pending_usd} in revenue.')
    top_repos = [r for r in repo_stats if r.eligible and r.total_potential > 0]
    top_repos.sort(key=lambda r: (-r.total_potential, r.repo))
    for repo in top_repos[:3]:
        _emit(action=f'Prioritise hunting on {repo.repo}', rationale=f'{repo.repo} has ${repo.total_potential} in projected payouts.', expected_impact=f'Capture up to ${repo.total_potential}.')
    total_workers = sum((ws.total for ws in worker_stats.values()))
    total_crashed = sum((ws.crashed for ws in worker_stats.values()))
    if total_workers and total_crashed / total_workers > 0.08:
        rate = round(total_crashed / total_workers * 100, 1)
        _emit(action='Reduce worker crash rate', rationale=f'{rate}% of workers are crashing.', expected_impact='Recover lost compute and improve throughput.')
    if any((b.area == 'observability' for b in bottlenecks)):
        _emit(action='Emit status on every progress entry', rationale='Observability bottleneck detected in progress data.', expected_impact='Restore visibility into pipeline health.')
    return recommendations

def compute_summary(workers: List[dict], findings: List[dict], tasks: List[dict], progress: List[dict], state: dict, pending_usd: int=0) -> dict:
    """Compute a compact, nested operational summary dict."""
    worker_counts = {'running': 0, 'completed': 0, 'failed': 0, 'crashed': 0}
    for worker in workers:
        status = worker.get('status')
        if status in worker_counts:
            worker_counts[status] += 1
    finished = worker_counts['completed'] + worker_counts['failed'] + worker_counts['crashed']
    success_rate_pct = round(worker_counts['completed'] / finished * 100, 1) if finished else 0
    revenue = state.get('operation_goals', {}).get('revenue_total_usd', 0)
    raw_seconds = state.get('time_tracking', {}).get('operation_total_s', 0) or 0
    total_op_hours = round(raw_seconds / 3600, 1)
    roi_per_hour = round(revenue / total_op_hours, 2) if total_op_hours else 0
    return {'system_phase': state.get('current_phase', 'unknown'), 'cycle': state.get('cycle_count', 0), 'phase_count': state.get('phase_count', 0), 'workers': {'total': len(workers), 'running': worker_counts['running'], 'completed': worker_counts['completed'], 'failed': worker_counts['failed'], 'crashed': worker_counts['crashed'], 'success_rate_pct': success_rate_pct}, 'findings': {'total': len(findings), 'bounty_eligible': sum((1 for f in findings if f.get('bounty_eligible')))}, 'financial': {'revenue_usd': revenue, 'pending_usd': pending_usd, 'roi_per_hour': roi_per_hour, 'total_op_hours': total_op_hours}, 'tasks_tracked': len(tasks), 'progress_entries': len(progress)}