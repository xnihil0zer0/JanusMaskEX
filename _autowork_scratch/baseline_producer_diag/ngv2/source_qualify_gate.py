"""Pure GO/SKIP/UNKNOWN qualification gate.

Ported from legacy bounty_gate.py + qualify_target.py into a single pure,
total, deterministic, side-effect-free module. Imports stdlib only; performs
no network, subprocess, LLM, wall-clock, randomness, or filesystem access and
holds no module-level mutable state.
"""
from typing import Any, Dict, Optional
REQUIRED_FIELDS = ('expected_payout', 'open_submissions', 'days_since_audit', 'fp_risk')

def qualify(target: Dict[str, Any], oracle_result: Dict[str, Any], *, saturation_cap: int=50, freshness_min: int=7) -> Dict[str, Any]:
    """Decide whether a target qualifies for engagement.

    Returns a dict with keys ``decision`` ('GO' | 'SKIP' | 'UNKNOWN'),
    ``reason`` (str), and ``target_spec`` (dict | None).
    """
    for field_name in REQUIRED_FIELDS:
        if field_name not in oracle_result:
            return {'decision': 'UNKNOWN', 'reason': 'missing key: {0}'.format(field_name), 'target_spec': None}
    expected_payout = oracle_result['expected_payout']
    open_submissions = oracle_result['open_submissions']
    days_since_audit = oracle_result['days_since_audit']
    fp_risk = oracle_result['fp_risk']
    if not expected_payout > 0:
        return {'decision': 'SKIP', 'reason': 'expected_payout <= 0', 'target_spec': None}
    if not open_submissions < saturation_cap:
        return {'decision': 'SKIP', 'reason': 'open_submissions >= saturation_cap ({0})'.format(saturation_cap), 'target_spec': None}
    if not days_since_audit >= freshness_min:
        return {'decision': 'SKIP', 'reason': 'days_since_audit < freshness_min ({0})'.format(freshness_min), 'target_spec': None}
    if fp_risk is not False:
        return {'decision': 'SKIP', 'reason': 'fp_risk match', 'target_spec': None}
    return {'decision': 'GO', 'reason': 'qualified', 'target_spec': {'repo': target['repo'], 'package': target['package'], 'expected_payout': expected_payout}}