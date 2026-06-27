"""Detection orchestrator for ngv2.

Pure, stdlib-only, deterministic module that drives ``run_pre_analysis``
and converts its merged report buckets into :class:`Finding` objects per
the frozen contract.  All non-determinism (clock, scanner seams) is
injected through explicit parameters so identical inputs always produce
identical output.
"""
from typing import Callable, Optional
from ngv2.pre_analysis import run_pre_analysis
from ngv2.grounding import normalize_severity
from ngv2.contracts import Finding, SEVERITIES

def _normalize_severity(raw: object) -> str:
    """Map a raw severity onto the contract's severity vocabulary.

    Delegates to :func:`ngv2.grounding.normalize_severity` and falls back
    to ``"low"`` for any result not in :data:`ngv2.contracts.SEVERITIES`.
    """
    normalized = normalize_severity(raw)
    if normalized not in SEVERITIES:
        return 'low'
    return normalized

def analyze(repo_path: str, *, semgrep_finder: Optional[Callable[[str], list[dict]]]=None, pattern_finder: Optional[Callable[[str], list[dict]]]=None, now_fn: Optional[Callable[[], str]]=None) -> list[Finding]:
    """Run pre-analysis and convert merged buckets into ``Finding`` objects.

    Buckets are consumed in a fixed order (cross-validated -> semgrep-only ->
    scanner-only), preserving run_pre_analysis's within-bucket order, each
    enumerated to yield a stable, deterministic list. ``category`` is taken
    from the bucket's real rule identifier (cross-validated: ``semgrep_rule_id``;
    semgrep: ``rule_id``; scanner: ``id``) and ``title`` from the human-readable
    ``message`` (or scanner ``description``).
    """
    report = run_pre_analysis(repo_path, semgrep_finder=semgrep_finder, pattern_finder=pattern_finder, now_fn=now_fn)
    buckets = (('xval', 'cross_validated'), ('semgrep', 'semgrep_only'), ('scanner', 'scanner_only'))
    findings: list[Finding] = []
    for src, bucket_name in buckets:
        for i, d in enumerate(report.get(bucket_name, []) or []):
            category = str(d.get('semgrep_rule_id') or d.get('rule_id') or d.get('id') or d.get('analyzer_pattern') or 'unknown')
            title = str(d.get('message') or d.get('description') or category)
            evidence = ['{0}:{1}'.format(d.get('file', ''), d.get('line', ''))]
            finding = Finding(id='{0}-{1}'.format(src, i), target=repo_path, category=category, severity=_normalize_severity(d.get('severity')), title=title, description=title, evidence=evidence)
            findings.append(finding)
    return findings