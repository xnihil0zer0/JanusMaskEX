"""Pure submission-readiness gate for NobleGreed v2 (ngv2).

This module implements ``readiness()``: a total, deterministic, side-effect-free
gate that admits a finding package to a human reviewer (``report ->
awaiting_submission``) only when *every* grounding precondition holds. When any
precondition fails it returns ``ready=False`` and names exactly the single
failing artifact, resolved through a fixed precedence order.

The gate *consumes* already-computed upstream signals (confidence, novelty,
bounty qualification, the live-test report, and the report-completeness score);
it never computes any of them itself, performs no approval/submission, and wires
no lifecycle FSM transition. It imports only the Python standard library and
ngv2 modules (``ngv2.contracts`` for ``VERDICTS`` and
``ngv2_submission_package_builder`` for ``readiness_score``).
"""
from __future__ import annotations
from typing import Any, Dict, Optional
try:
    from ngv2.contracts import VERDICTS as _VERDICTS
except Exception:
    _VERDICTS = ('confirmed', 'refuted', 'inconclusive')
try:
    from ngv2_submission_package_builder import readiness_score as _readiness_score
except Exception:
    try:
        from ngv2.submission_package_builder import readiness_score as _readiness_score
    except Exception:
        _readiness_score = None
MISSING_CONFIDENCE = 'confidence'
MISSING_LIVE_TEST = 'live_test'
MISSING_NOVELTY = 'novelty'
MISSING_BOUNTY_ELIGIBILITY = 'bounty_eligibility'
MISSING_REPORT_PACKAGE = 'report_package'
PRECEDENCE = (MISSING_CONFIDENCE, MISSING_LIVE_TEST, MISSING_NOVELTY, MISSING_BOUNTY_ELIGIBILITY, MISSING_REPORT_PACKAGE)
ELIGIBLE_CONFIDENCE = frozenset({'CONFIRMED', 'HIGH'})
_CONFIRMED_VERDICT = 'confirmed'
_REQUIRED_NOVELTY = 'NOVEL'
_GO_DECISION = 'GO'
_REQUIRED_READINESS_SCORE = 3

def _attr_or_item(obj: Any, name: str, default: Any=None) -> Any:
    """Read ``name`` from ``obj`` as an attribute or mapping item, total/safe."""
    if obj is None:
        return default
    try:
        if hasattr(obj, name):
            return getattr(obj, name)
    except Exception:
        pass
    try:
        if isinstance(obj, dict):
            return obj.get(name, default)
        getter = getattr(obj, 'get', None)
        if callable(getter):
            return getter(name, default)
    except Exception:
        pass
    return default

def _confidence_ok(confidence: Any) -> bool:
    """True iff confidence is exactly one of the eligible upper-case levels."""
    return isinstance(confidence, str) and confidence in ELIGIBLE_CONFIDENCE

def _live_test_ok(live_report: Any) -> bool:
    """True iff a live report exists, is live-tested, and verdict is 'confirmed'."""
    if live_report is None:
        return False
    live_tested = _attr_or_item(live_report, 'live_tested', False)
    if not bool(live_tested):
        return False
    verdict = _attr_or_item(live_report, 'verdict', None)
    if not isinstance(verdict, str):
        return False
    try:
        in_vocab = verdict in _VERDICTS
    except Exception:
        in_vocab = False
    return in_vocab and verdict == _CONFIRMED_VERDICT

def _novelty_ok(novelty: Any) -> bool:
    """True iff novelty is exactly 'NOVEL'."""
    return isinstance(novelty, str) and novelty == _REQUIRED_NOVELTY

def _bounty_ok(bounty: Any) -> bool:
    """True iff bounty indicates a GO decision with a non-null target_spec."""
    if not isinstance(bounty, dict):
        return False
    decision = bounty.get('decision')
    if decision != _GO_DECISION:
        return False
    return bounty.get('target_spec') is not None

def readiness_score(package: Any) -> int:
    """Legacy 0-3 submission-readiness score over a package dict.

    One point per artifact group present and truthy: the rendered
    submission package/report content, the PoC reference, and the
    live-test evidence. Total and deterministic: returns 0 for non-dict
    input; never raises.
    """
    if not isinstance(package, dict):
        return 0
    groups = (('submission_pkg', 'report', 'report_markdown', 'package_markdown', 'markdown', 'title'), ('poc', 'poc_file', 'poc_reference'), ('live_test', 'live_test_evidence', 'live_report'))
    score = 0
    for keys in groups:
        if any((bool(package.get(key)) for key in keys)):
            score += 1
    return score
def _report_package_ok(package: Any) -> bool:
    """True iff the effective readiness score of ``package`` is exactly 3; never raises."""
    scorer = _readiness_score if callable(_readiness_score) else readiness_score
    try:
        score = scorer(package)
    except Exception:
        return False
    return score == _REQUIRED_READINESS_SCORE

def readiness(finding: Any, poc: Any, live_report: Any, novelty: str, bounty: dict, package: dict, confidence: str) -> Dict[str, Optional[str]]:
    """Decide whether a finding package is ready for human submission.

    Returns ``{"ready": True, "missing": None}`` iff all five preconditions hold:
    eligible confidence, a live-tested PoC with a confirmed verdict, NOVEL
    novelty, a bounty-eligible target, and a report-completeness score of 3.

    Otherwise returns ``{"ready": False, "missing": <artifact>}`` naming exactly
    the first failing artifact in the fixed precedence order. The function is
    pure, total, and deterministic: it never raises on malformed/missing inputs.
    """
    if not _confidence_ok(confidence):
        return {'ready': False, 'missing': MISSING_CONFIDENCE}
    if not _live_test_ok(live_report):
        return {'ready': False, 'missing': MISSING_LIVE_TEST}
    if not _novelty_ok(novelty):
        return {'ready': False, 'missing': MISSING_NOVELTY}
    if not _bounty_ok(bounty):
        return {'ready': False, 'missing': MISSING_BOUNTY_ELIGIBILITY}
    if not _report_package_ok(package):
        return {'ready': False, 'missing': MISSING_REPORT_PACKAGE}
    return {'ready': True, 'missing': None}