"""Pure materializer for the ``oracle_result`` dict consumed by qualify.

This module assembles the four-field ``oracle_result`` mapping that
``ngv2.source_qualify_gate.qualify`` reads, deriving the economic payout from
``ngv2.bounty_gate.gate`` and taking every other external fact (saturation
count, audit age, false-positive patterns) as an injected argument.  The
function is therefore total, deterministic, and hermetic: it performs no
network, subprocess, wall-clock, filesystem, or randomness access.
"""
from __future__ import annotations
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union
from ngv2.bounty_gate import gate
ORACLE_RESULT_FIELDS = ('expected_payout', 'open_submissions', 'days_since_audit', 'fp_risk')
NEVER_AUDITED_DAYS = 10 ** 6

def _expected_payout(repo: str, cwe: str, severity: str, bounties: Optional[Mapping[str, Any]]) -> int:
    """Delegate to ``bounty_gate.gate`` and coerce payout to a non-negative int."""
    decision = gate(repo, cwe, severity, bounties=bounties)
    value = decision.get('expected_payout')
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    result = int(value)
    return result if result > 0 else 0

def _days_since_audit(last_audit_days: Optional[Any]) -> Union[int, float]:
    """Coerce the injected audit age: invalid -> NEVER_AUDITED_DAYS, negative -> 0.0."""
    if last_audit_days is None:
        return NEVER_AUDITED_DAYS
    try:
        value = float(last_audit_days)
    except (TypeError, ValueError):
        return NEVER_AUDITED_DAYS
    if value < 0:
        return 0.0
    return value

def _fp_risk(cwe: str, fp_patterns: Optional[Sequence[Mapping[str, Any]]]) -> Union[bool, List[Mapping[str, Any]]]:
    """Return the matched fp records (case-insensitive on CWE) or literal False."""
    if not fp_patterns:
        return False
    target = str(cwe).strip().lower()
    matched = [record for record in fp_patterns if str(record.get('cwe', '')).strip().lower() == target]
    return matched if matched else False

def materialize_oracle_result(repo: str, cwe: str, severity: str, *, bounties: Optional[Mapping[str, Any]]=None, submissions: int=0, last_audit_days: Optional[Any]=None, fp_patterns: Optional[Sequence[Mapping[str, Any]]]=None) -> Dict[str, Any]:
    """Assemble the four-field oracle_result dict consumed by qualify."""
    try:
        open_submissions = int(submissions)
    except (TypeError, ValueError):
        open_submissions = 0
    if open_submissions < 0:
        open_submissions = 0
    return {'expected_payout': _expected_payout(repo, cwe, severity, bounties), 'open_submissions': open_submissions, 'days_since_audit': _days_since_audit(last_audit_days), 'fp_risk': _fp_risk(cwe, fp_patterns)}