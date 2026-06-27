"""Merged demand source for the selection ranker's bounty/demand term.

The live huntr public RSC feed zeroes ``disclosure.amount``, so bounty records
built by ``ngv2.sourcing.huntr_refresh`` carry all-zero ``observed_payouts``
and the ranker's demand term goes INERT on live data. This module merges THREE
demand sources, in priority order, into one effective expected payout:

1. LIVE override -- a positive live-feed payout for the severity band wins
   verbatim (no discount: it is an observed real payout).
2. HAND-MINED    -- the per-repo ``observed_payouts`` from the frozen
   data/ngv2/huntr_repo_bounties.json ground truth, discounted by a coarse
   program-health multiplier parsed from ``pool_note`` (reuses
   :func:`ngv2.bounty_corpus_stats._program_health_from_note`; 'at_risk'
   programs are halved).
3. CVSS-proxy    -- ``max_paid`` scaled by the snapshot's documented
   CVSS-severity pricing fractions (Critical=100%, High=50%, Medium=8%,
   Low=1%), with the same health discount.

Every failure path (missing/None/non-numeric/zero fields, malformed records,
unknown severity) degrades to ``0`` -- the public functions NEVER raise on
snapshot-shaped input. Pure: standard library + ngv2 only. No network, clock,
disk, randomness, or mutation of the input records.
"""
from __future__ import annotations
from typing import Any, Mapping, Optional
from ngv2.bounty_corpus_stats import _program_health_from_note
__all__ = ['merge_expected_payout', 'merged_bounty']
_SEVERITY_FRACTION: dict = {'critical': 1.0, 'high': 0.5, 'medium': 0.08, 'low': 0.01}
_HEALTH_MULTIPLIER: dict = {'healthy': 1.0, 'unknown': 1.0, 'at_risk': 0.5}

def _positive_number(value: Any) -> Optional[float]:
    """Coerce a strictly-positive int/float to float; anything else is None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if value > 0 else None

def _band_payout(record: Any, severity: str) -> Optional[float]:
    """The record's positive observed payout for *severity*, else None."""
    if not isinstance(record, Mapping):
        return None
    payouts = record.get('observed_payouts')
    if not isinstance(payouts, Mapping):
        return None
    return _positive_number(payouts.get(severity))

def _cvss_proxy(record: Any, severity: str) -> Optional[float]:
    """CVSS-severity-proxy payout: max_paid x documented severity fraction."""
    if not isinstance(record, Mapping):
        return None
    max_paid = _positive_number(record.get('max_paid'))
    fraction = _SEVERITY_FRACTION.get(severity)
    if max_paid is None or fraction is None:
        return None
    return max_paid * fraction

def merge_expected_payout(live_record: Any, mined_record: Any, severity: str='critical') -> int:
    """Effective expected payout merging live, hand-mined, and proxy demand.

    Priority: positive live-feed band payout (verbatim) > hand-mined band
    payout (health-discounted) > CVSS-proxy on ``max_paid`` (mined record
    first, then live; health-discounted) > 0. Returns a non-negative int and
    never raises on malformed input.
    """
    sev = str(severity).strip().lower()
    live = _band_payout(live_record, sev)
    if live is not None:
        return int(live)
    pool_note = mined_record.get('pool_note') if isinstance(mined_record, Mapping) else None
    health = _program_health_from_note(pool_note)
    multiplier = _HEALTH_MULTIPLIER.get(health, 1.0)
    mined = _band_payout(mined_record, sev)
    if mined is not None:
        return int(mined * multiplier)
    proxy = _cvss_proxy(mined_record, sev)
    if proxy is None:
        proxy = _cvss_proxy(live_record, sev)
    if proxy is not None:
        return int(proxy * multiplier)
    return 0

def merged_bounty(live_record: Any, mined_record: Any, severity: str='critical') -> dict:
    """A bounty mapping consumable by ``selection_ranker._coerce_payout``."""
    return {'expected_payout': merge_expected_payout(live_record, mined_record, severity)}