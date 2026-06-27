"""Deterministic submission-readiness scorer for ngv2.

Given a finding and the presence of three artifacts (submission package, PoC,
live test), compute a 0-3 readiness score, a deterministic next-action string,
and a ``submission_rank``. The scorer is pure: artifact presence is supplied
through an injected ``resolver(kind, finding) -> Optional[str]`` seam, so no
filesystem, clock, or randomness is ever touched.
"""
from __future__ import annotations
from dataclasses import dataclass, field, fields, replace
from typing import Any, Callable, Dict, List, Optional, Tuple
Resolver = Callable[[str, 'FindingScore'], Optional[str]]

@dataclass
class ArtifactCheck:
    """Result of probing for a single artifact."""
    exists: bool
    path: Optional[str] = None
    note: str = ''

@dataclass
class FindingScore:
    """A ledger finding enriched with submission-readiness scoring."""
    id: str
    task_id: int
    finding_id: int
    amount_usd: float
    cwe: str
    severity: str
    repo: str
    status: str
    description: str
    submission_pkg: ArtifactCheck = field(default_factory=lambda: ArtifactCheck(False))
    poc_file: ArtifactCheck = field(default_factory=lambda: ArtifactCheck(False))
    live_test: ArtifactCheck = field(default_factory=lambda: ArtifactCheck(False))
    readiness_score: int = 0
    next_action: str = ''
    submission_rank: int = 0
READINESS_FIELDS: Tuple[str, ...] = tuple((f.name for f in fields(FindingScore)))
NEXT_ACTIONS: Dict[str, str] = {'SUBMIT': 'Submit now: package, PoC and live test are all present.', 'NEED_PKG': 'Build the submission package before submitting.', 'NEED_POC': 'Write the PoC before submitting.', 'NEED_TEST': 'Run the live test before submitting.', 'NEED_ALL': 'Prepare package, PoC and live test before submitting.'}

def make_mock_artifact_resolver(mapping: Dict[Any, str]) -> Resolver:
    """Build a deterministic resolver from an in-memory mapping.

    Keys may be a bare artifact ``kind`` (e.g. ``"poc"``) or a
    ``(kind, str(finding_id))`` tuple for finding-specific overrides. The
    tuple form takes precedence when present.
    """

    def resolver(kind: str, finding: 'FindingScore') -> Optional[str]:
        fid = str(getattr(finding, 'finding_id', ''))
        specific = (kind, fid)
        if specific in mapping:
            return mapping[specific]
        if kind in mapping:
            return mapping[kind]
        return None
    return resolver

def _check(kind: str, finding: FindingScore, resolver: Optional[Resolver], missing_note: str) -> ArtifactCheck:
    path = resolver(kind, finding) if resolver is not None else None
    if path:
        return ArtifactCheck(True, path)
    return ArtifactCheck(False, None, missing_note)

def check_submission_pkg(finding: FindingScore, resolver: Optional[Resolver]) -> ArtifactCheck:
    return _check('submission_pkg', finding, resolver, 'submission package not found')

def check_poc(finding: FindingScore, resolver: Optional[Resolver]) -> ArtifactCheck:
    return _check('poc', finding, resolver, 'PoC file not found')

def check_live_test(finding: FindingScore, resolver: Optional[Resolver]) -> ArtifactCheck:
    return _check('live_test', finding, resolver, 'live test not found')

def _next_action(score: int, pkg: ArtifactCheck, poc: ArtifactCheck, test: ArtifactCheck) -> str:
    if score == 3:
        return NEXT_ACTIONS['SUBMIT']
    if score == 0:
        return NEXT_ACTIONS['NEED_ALL']
    if not pkg.exists:
        return NEXT_ACTIONS['NEED_PKG']
    if not poc.exists:
        return NEXT_ACTIONS['NEED_POC']
    return NEXT_ACTIONS['NEED_TEST']

def score_finding(finding: FindingScore, resolver: Optional[Resolver]) -> FindingScore:
    """Return a new ``FindingScore`` with artifact checks and scoring filled in.

    The input ``finding`` is left untouched; scoring is a pure function of the
    finding and the injected resolver.
    """
    pkg = check_submission_pkg(finding, resolver)
    poc = check_poc(finding, resolver)
    test = check_live_test(finding, resolver)
    score = int(pkg.exists) + int(poc.exists) + int(test.exists)
    action = _next_action(score, pkg, poc, test)
    rank = int((10000 - finding.amount_usd) * 10 + (3 - score))
    return replace(finding, submission_pkg=pkg, poc_file=poc, live_test=test, readiness_score=score, next_action=action, submission_rank=rank)

def _to_int(value: Any) -> int:
    try:
        if value is None or value == '':
            return 0
        return int(value)
    except (TypeError, ValueError):
        return 0

def _to_float(value: Any) -> float:
    try:
        if value is None or value == '':
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0

def load_ledger(entries: Any) -> List[FindingScore]:
    """Coerce raw ledger rows into ``FindingScore`` objects.

    Non-dict rows and rows whose status is not ``"ready_to_submit"`` are
    skipped. The ``repo`` field falls back to a legacy ``format`` column.
    """
    out: List[FindingScore] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get('status') != 'ready_to_submit':
            continue
        repo = entry.get('repo') or entry.get('format') or ''
        out.append(FindingScore(id=entry.get('id', ''), task_id=_to_int(entry.get('task_id')), finding_id=_to_int(entry.get('finding_id')), amount_usd=_to_float(entry.get('amount_usd')), cwe=entry.get('cwe', ''), severity=entry.get('severity', ''), repo=repo, status=entry.get('status', ''), description=entry.get('description', '')))
    return out