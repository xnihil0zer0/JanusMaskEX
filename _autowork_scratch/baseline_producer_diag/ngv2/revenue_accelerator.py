"""Pure, deterministic ROI work planner for NobleGreedv2.

This module ranks and sequences candidate bounty work items by expected
dollars-per-hour and picks the single most valuable next action. It is a
clean-room re-expression of the durable capability from the legacy
``revenue_accelerator`` tool, with all of the impure I/O cruft removed:

* no sqlite / filesystem globbing
* no subprocess dispatch
* no network, clock, randomness, or external tools

Everything operates over plain dicts and a single stdlib dataclass. All data
dependencies are injected by the caller, so identical inputs always produce
byte-identical output ordering.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Tuple
__all__ = ['WorkItem', 'ACCEPTANCE_PROB', 'CONFIDENCE_MULT', 'TIME_COST', 'compute_next_action', 'rank_by_roi']
ACCEPTANCE_PROB: Dict[str, float] = {'live_tested': 0.7, 'ready_to_submit': 0.7, 'complete': 0.55, 'tested': 0.45, 'draft': 0.3, 'none': 0.2}
CONFIDENCE_MULT: Dict[str, float] = {'CONFIRMED': 1.0, 'HIGH': 0.8, 'MEDIUM': 0.5, 'LOW': 0.25}
TIME_COST: Dict[str, float] = {'submit': 0.2, 'write_report': 0.35, 'live_test': 0.4, 'write_poc': 0.75, 'audit_deeper': 1.5}

@dataclass
class WorkItem:
    """A single candidate piece of bounty work, ROI-scored for planning.

    The first eight fields describe the finding and are required; the
    remaining fields carry the planner's derived ROI metrics and default to
    neutral, zero-valued state so a ``WorkItem`` can be constructed before it
    has been scored.
    """
    finding_id: str
    repo: str
    title: str
    cwe: str
    severity: str
    confidence: str
    poc_status: str
    bounty_eligible: bool
    next_action: str = ''
    expected_value: float = 0.0
    time_cost_hours: float = 0.0
    dollar_per_hour: float = 0.0
    is_blocked: bool = False
    block_reason: str = ''

def compute_next_action(finding: Mapping[str, object], artifacts: Mapping[str, object]) -> Tuple[str, float]:
    """Decide the single next action for ``finding`` given present artifacts.

    Artifact presence is authoritative: the pipeline always advances PoC ->
    live test -> report -> submit, and a missing earlier artifact forces us
    back to producing it (e.g. no PoC means we must ``write_poc`` even if a
    stray report or live test already exists).

    Returns a ``(action, hours)`` pair where ``hours`` is the matching
    ``TIME_COST`` estimate.
    """
    if not artifacts.get('has_poc'):
        return ('write_poc', TIME_COST['write_poc'])
    if not artifacts.get('has_live_test'):
        return ('live_test', TIME_COST['live_test'])
    if not artifacts.get('has_report'):
        return ('write_report', TIME_COST['write_report'])
    return ('submit', TIME_COST['submit'])

def _rank_key(item: WorkItem) -> Tuple[bool, float, float, str]:
    """Stable sort key for ROI ranking.

    Ordering (ascending tuple sort yields the desired ranking):

    1. blocked items sort last (``False`` < ``True``);
    2. higher ``dollar_per_hour`` first (negated);
    3. tie-break on higher ``expected_value`` first (negated);
    4. final tie-break on ``finding_id`` ascending for full determinism.
    """
    return (item.is_blocked, -item.dollar_per_hour, -item.expected_value, item.finding_id)

def rank_by_roi(items: List[WorkItem]) -> List[WorkItem]:
    """Return a new list of ``items`` ranked by descending ROI.

    Pure and deterministic: the input list is neither mutated nor reordered,
    and identical inputs always produce identical output. Blocked items are
    demoted to the end regardless of their dollar-per-hour. An empty input
    yields an empty plan.
    """
    return sorted(items, key=_rank_key)