"""Deterministic target qualification gate for NobleGreedv2 (ngv2.target_qualify).

This is a pure, stdlib-only re-expression of the legacy
``services/qualify_target.py`` capability. The legacy gate decided whether a
hunt target was worth pursuing by reading bounty JSON, scanning the filesystem
for prior audits, and comparing ``datetime.now()`` against file mtimes. All of
that I/O was nondeterministic.

Here every external fact -- the bounty decision, the submission count, the audit
age, and the false-positive patterns -- arrives as an INJECTED data seam passed
in as an argument. The functions perform NO filesystem, clock, or network
operations: the same inputs always produce the same output. The surrounding
shell (whatever computes bounty records, counts submissions, reads audit mtimes
against a clock, or loads FP patterns) is responsible for resolving those seams
before calling in.
"""
from typing import Any, Dict, List, Optional, Tuple
SATURATION_THRESHOLD: int = 50
FRESHNESS_THRESHOLD_DAYS: int = 7
DECISIONS: Tuple[str, ...] = ('GO', 'SKIP', 'UNKNOWN')
QUALIFY_RESULT_FIELDS: Tuple[str, ...] = ('decision', 'target', 'target_type', 'purpose', 'bounty', 'saturation', 'freshness', 'fp_risk', 'reasoning')
_SKIPPED: str = 'SKIPPED'

def parse_target(target: Optional[str]) -> Tuple[str, str]:
    """Classify a candidate target string as a ``format`` or a ``repo``.

    ``FORMAT:GGUF`` style targets (case-insensitive ``format:`` prefix) are
    model-format targets whose value is normalized to lowercase. Everything
    else is treated as an ``owner/repo`` repository identifier, stripped of
    surrounding whitespace but otherwise left as-is.

    Returns a ``(target_type, normalized_value)`` tuple.
    """
    text = (target or '').strip()
    if text.lower().startswith('format:'):
        value = text.split(':', 1)[1].strip().lower()
        return ('format', value)
    return ('repo', text)

def check_bounty(target: str, cwe: str, severity: str, bounty: Optional[Dict[str, Any]]=None) -> Dict[str, Any]:
    """Mirror an injected bounty decision record into a gate sub-result.

    The bounty seam is whatever the GO/SKIP/UNKNOWN bounty gate produced for
    this target/CWE/severity. When no record is injected the gate cannot make a
    call, so the result is ``UNKNOWN``.
    """
    if not bounty:
        return {'expected': None, 'tier': None, 'status': 'UNKNOWN', 'reasoning': 'no bounty record'}
    status = bounty.get('decision', 'UNKNOWN')
    if status not in DECISIONS:
        status = 'UNKNOWN'
    return {'expected': bounty.get('expected_payout'), 'tier': bounty.get('tier'), 'status': status, 'reasoning': bounty.get('reasoning')}

def check_saturation(target: str, target_type: str, submissions: int=0) -> Dict[str, Any]:
    """Decide whether a target is over-submitted.

    ``submissions`` is the injected count of prior submissions for this target
    (the shell reads the bounties data structure). At or above
    ``SATURATION_THRESHOLD`` the target is saturated and SKIPs; otherwise GO.
    """
    try:
        count = int(submissions)
    except (TypeError, ValueError):
        count = 0
    status = 'SKIP' if count >= SATURATION_THRESHOLD else 'GO'
    return {'submissions': count, 'threshold': SATURATION_THRESHOLD, 'status': status}

def check_freshness(target: str, target_type: str, purpose: str, days_ago: Optional[float]=None, cap_newer: bool=False) -> Dict[str, Any]:
    """Decide whether a target was audited too recently to re-hunt.

    ``days_ago`` is the injected age (in days) of the most recent prior audit
    for this target, computed by the shell from a file mtime against an injected
    clock; ``None`` means there is no prior audit (or no active task matched the
    target search term). ``cap_newer`` is the injected flag indicating new
    capabilities are newer than the last audit mtime.

    Rules:
      * ``submit`` purpose always bypasses freshness -> GO.
      * No prior audit -> GO.
      * Audited at or beyond ``FRESHNESS_THRESHOLD_DAYS`` -> GO (stale enough).
      * ``retest`` purpose with newer capabilities bypasses freshness -> GO.
      * Otherwise, recently audited under the threshold -> SKIP.
    """
    threshold = FRESHNESS_THRESHOLD_DAYS
    if purpose == 'submit':
        return {'last_audited': days_ago is not None, 'days_ago': days_ago, 'threshold': threshold, 'status': 'GO', 'bypassed': 'submit'}
    if days_ago is None:
        return {'last_audited': None, 'days_ago': None, 'threshold': threshold, 'status': 'GO'}
    if days_ago >= threshold:
        return {'last_audited': True, 'days_ago': days_ago, 'threshold': threshold, 'status': 'GO'}
    if purpose == 'retest' and cap_newer:
        return {'last_audited': True, 'days_ago': days_ago, 'threshold': threshold, 'status': 'GO', 'bypassed': 'new_capabilities'}
    return {'last_audited': True, 'days_ago': days_ago, 'threshold': threshold, 'status': 'SKIP'}

def check_fp_risk(target: str, cwe: str, target_type: str, patterns: Optional[List[Dict[str, Any]]]=None) -> Dict[str, Any]:
    """Count how many injected false-positive patterns match this CWE.

    ``patterns`` is the injected list of known FP patterns (the shell reads the
    false-positive patterns store). Matching is by CWE, case-insensitive. This
    check is purely advisory -- it never SKIPs a target, only reports.
    """
    records = patterns or []
    cwe_norm = (cwe or '').strip().lower()
    matched = [record for record in records if str(record.get('cwe', '')).strip().lower() == cwe_norm]
    return {'matches': len(matched), 'patterns': matched, 'status': 'GO'}

def _skipped() -> Dict[str, Any]:
    """Sub-result placeholder for a gate that never ran."""
    return {'status': _SKIPPED}

def _build_result(decision: str, target: str, target_type: str, purpose: str, bounty: Dict[str, Any], saturation: Dict[str, Any], freshness: Dict[str, Any], fp_risk: Dict[str, Any], reasons: List[str]) -> Dict[str, Any]:
    """Assemble the final result dict in the frozen field order."""
    reasoning = '; '.join((reason for reason in reasons if reason)) or decision
    return {'decision': decision, 'target': target, 'target_type': target_type, 'purpose': purpose, 'bounty': bounty, 'saturation': saturation, 'freshness': freshness, 'fp_risk': fp_risk, 'reasoning': reasoning}

def qualify(target: str, cwe: str, severity: str, purpose: str, bounty: Optional[Dict[str, Any]]=None, submissions: int=0, days_ago: Optional[float]=None, fp_patterns: Optional[List[Dict[str, Any]]]=None, cap_newer: bool=False) -> Dict[str, Any]:
    """Run the full deterministic qualification gate for a candidate target.

    Each gate is consulted in order and short-circuits the rest: a non-GO bounty
    (SKIP/UNKNOWN), then saturation, then freshness. Downstream sub-results that
    never ran are marked ``SKIPPED``. Only when every gate passes does the target
    qualify with decision GO; the advisory ``fp_risk`` never blocks.

    All external facts are injected as plain data arguments, so this function is
    pure and performs no real I/O, clock, or network access.
    """
    target_type, normalized = parse_target(target)
    reasons: List[str] = []
    bounty_res = check_bounty(target, cwe, severity, bounty=bounty)
    if bounty_res['status'] != 'GO':
        decision = bounty_res['status']
        reasons.append('bounty {0}: {1}'.format(decision, bounty_res.get('reasoning')))
        return _build_result(decision, normalized, target_type, purpose, bounty_res, _skipped(), _skipped(), _skipped(), reasons)
    reasons.append('bounty GO (tier={0}, expected={1})'.format(bounty_res.get('tier'), bounty_res.get('expected')))
    saturation_res = check_saturation(normalized, target_type, submissions=submissions)
    if saturation_res['status'] == 'SKIP':
        reasons.append('saturated: {0} submissions >= {1}'.format(saturation_res['submissions'], saturation_res['threshold']))
        return _build_result('SKIP', normalized, target_type, purpose, bounty_res, saturation_res, _skipped(), _skipped(), reasons)
    reasons.append('not saturated ({0}/{1})'.format(saturation_res['submissions'], saturation_res['threshold']))
    freshness_res = check_freshness(normalized, target_type, purpose, days_ago=days_ago, cap_newer=cap_newer)
    if freshness_res['status'] == 'SKIP':
        reasons.append('recently audited ({0} days ago, threshold {1})'.format(freshness_res['days_ago'], freshness_res['threshold']))
        return _build_result('SKIP', normalized, target_type, purpose, bounty_res, saturation_res, freshness_res, _skipped(), reasons)
    reasons.append('fresh enough')
    fp_res = check_fp_risk(normalized, cwe, target_type, patterns=fp_patterns)
    if fp_res['matches']:
        reasons.append('fp risk: {0} matching pattern(s)'.format(fp_res['matches']))
    reasons.append('qualified for hunting')
    return _build_result('GO', normalized, target_type, purpose, bounty_res, saturation_res, freshness_res, fp_res, reasons)