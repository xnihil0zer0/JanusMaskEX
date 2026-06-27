"""Phase 7.2a: apply a huntr SubmissionVerdict to the false-positive store.

A rejected/duplicate verdict is an FP teaching signal: it grows the FP-pattern
knowledge base by exactly one entry via ``ngv2.fp_patterns.add_fp_pattern``.
This module is a pure consumer of that store -- it never re-implements it and
never touches a clock, the network, or randomness; the ``now`` timestamp is the
only deterministic seam and is passed straight through to ``add_fp_pattern``.
"""
from __future__ import annotations
from typing import Any, Dict, Optional
from ngv2.fp_patterns import add_fp_pattern
from ngv2.submission_verdict import SubmissionVerdict

def _verdict_state(verdict: Any) -> str:
    """Normalize a verdict's state to a lowercased, stripped string.

    Accepts a SubmissionVerdict (uses ``.state``), a dict (uses the ``state``
    key), or any duck-typed object (uses ``getattr(verdict, 'state', '')``).
    """
    if isinstance(verdict, SubmissionVerdict):
        return str(verdict.state).strip().lower()
    if isinstance(verdict, dict):
        return str(verdict.get('state', '')).strip().lower()
    return str(getattr(verdict, 'state', '')).strip().lower()

def is_fp_signal(verdict: Any) -> bool:
    """True iff the verdict state is a rejection ('rejected' or 'duplicate')."""
    return _verdict_state(verdict) in ('rejected', 'duplicate')

def apply_reject_verdict(verdict: Any, finding: Dict[str, Any], fp_file: Any, now: Optional[str]=None) -> Optional[dict]:
    """Grow the FP store by one when ``verdict`` is a rejection, else no-op.

    On a reject/duplicate verdict, append exactly one FP pattern derived from
    ``finding`` via ``add_fp_pattern`` and return the new entry. On any
    non-rejection, return None and leave the store untouched.
    """
    if not is_fp_signal(verdict):
        return None
    state = _verdict_state(verdict)
    reason = 'huntr verdict: %s' % state
    if isinstance(verdict, SubmissionVerdict) and verdict.reason:
        reason = '%s — %s' % (reason, verdict.reason)
    return add_fp_pattern(finding, reason=reason, source='huntr_verdict', fp_file=fp_file, now=now)