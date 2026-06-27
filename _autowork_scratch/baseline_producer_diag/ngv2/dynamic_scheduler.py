"""Pure, stdlib-only ROI-driven cron-scheduling advisor.

This module turns evaluation metrics carried in a plain ``state`` dict into
per-chain ROI estimates and threshold-based firing-interval recommendations.

It performs NO filesystem / clock / network / subprocess / randomness access
and never mutates its input dicts. All ROI is derived from
``state['evaluation_metrics']``, ``state['time_tracking']`` and
``state['adversarial']`` read defensively, so an empty/partial state yields
all zeros without raising.
"""
from typing import Dict, Optional
MIN_INTERVAL: int = 3
MAX_INTERVAL: int = 30
DEFAULT_INTERVAL: int = 5
HIGH_ROI_THRESHOLD: float = 5.0
LOW_ROI_THRESHOLD: float = 0.5
PAUSE_THRESHOLD: float = 0.1
CHAINS: Dict[str, dict] = {'bug_hunt': {'metric_key': 'submittable_findings', 'default_interval': 5}, 'mff_hunt': {'metric_key': 'mff_findings', 'default_interval': 5}, 'adversarial': {'metric_key': 'rules_written', 'default_interval': 10}, 'mff_adversarial': {'metric_key': 'rules_written', 'default_interval': 10}}

def compute_chain_roi(state: dict) -> Dict[str, dict]:
    """Compute per-chain ROI estimates from a ``state`` dict.

    Reads all inputs defensively so empty/partial states yield all-zeros and
    never raises. Does not mutate ``state``.
    """
    if state is None:
        state = {}
    metrics = state.get('evaluation_metrics') or {}
    time_tracking = state.get('time_tracking') or {}
    adversarial = state.get('adversarial') or {}
    op_hours = time_tracking.get('operation_total_s', 0) / 3600.0
    submittable = metrics.get('submittable_findings', 0)
    mff = metrics.get('mff_findings', 0)
    rules = adversarial.get('rules_written', 0)
    bug_value = submittable * 500 * 0.5
    bug_hours = max(op_hours * 0.6, 0.1)
    bug_hunt = {'estimated_value': float(bug_value), 'hours': float(bug_hours), 'roi_per_hour': float(bug_value / bug_hours), 'findings': submittable}
    mff_value = mff * 2000 * 0.3
    mff_hours = max(op_hours * 0.3, 0.1)
    mff_hunt = {'estimated_value': float(mff_value), 'hours': float(mff_hours), 'roi_per_hour': float(mff_value / mff_hours), 'findings': mff}
    adv_value = rules * 100
    adv_hours = max(op_hours * 0.1, 0.1)
    adversarial_entry = {'estimated_value': float(adv_value), 'hours': float(adv_hours), 'roi_per_hour': float(adv_value / adv_hours), 'rules_written': rules}
    mff_adversarial_entry = dict(adversarial_entry)
    return {'bug_hunt': bug_hunt, 'mff_hunt': mff_hunt, 'adversarial': adversarial_entry, 'mff_adversarial': mff_adversarial_entry}

def recommend_schedule(state: Optional[dict]=None) -> Dict[str, dict]:
    """Recommend a firing interval and action per chain based on ROI.

    A ``None`` state defaults to an empty dict, so
    ``recommend_schedule() == recommend_schedule({})``. Pure and deterministic.
    """
    if state is None:
        state = {}
    roi = compute_chain_roi(state)
    recommendations: Dict[str, dict] = {}
    for chain in CHAINS:
        entry = roi[chain]
        roi_per_hour = entry['roi_per_hour']
        if roi_per_hour >= HIGH_ROI_THRESHOLD:
            interval = MIN_INTERVAL
            action = 'increase_frequency'
        elif roi_per_hour >= LOW_ROI_THRESHOLD:
            interval = CHAINS[chain]['default_interval']
            action = 'maintain'
        elif roi_per_hour >= PAUSE_THRESHOLD:
            interval = MAX_INTERVAL
            action = 'reduce_frequency'
        else:
            interval = MAX_INTERVAL
            action = 'consider_pause'
        reason = '{chain}: roi_per_hour={roi:.2f} -> {action} (interval={interval}m)'.format(chain=chain, roi=roi_per_hour, action=action, interval=interval)
        recommendations[chain] = {'interval_minutes': int(interval), 'action': action, 'reason': reason, 'roi': entry}
    return recommendations