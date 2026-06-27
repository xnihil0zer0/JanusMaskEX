from typing import Dict, Any, List, Union

def expected_payout(bounty: Dict[str, Any], severity: str) -> Union[int, float]:
    var_0 = severity.strip().lower()
    var_1 = bounty.get('observed_payouts')
    if var_1 is not None:
        if var_0 in var_1:
            return var_1[var_0]
        for var_2, var_3 in var_1.items():
            if var_2.strip().lower() == var_0:
                return var_3
    var_4 = bounty.get('max_paid', 0)
    if var_4 is None:
        var_4 = 0
    if var_0 == 'critical':
        var_5 = 1.0
    elif var_0 == 'high':
        var_5 = 0.5
    elif var_0 == 'medium':
        var_5 = 0.08
    elif var_0 == 'low':
        var_5 = 0.01
    else:
        var_5 = 0.0
    return int(var_4 * var_5)

def _get_bounty_sort_key(bounty: Dict[str, Any], severity: str) -> tuple:
    var_0 = expected_payout(bounty, severity)
    var_1 = bounty.get('total_advisories', 0)
    var_4 = bounty.get('repo', '')
    if var_1 is None:
        var_1 = 0
    if var_4 is None:
        var_4 = ''
    return (-var_0, var_1, var_4)

def rank_targets(bounties: List[Dict[str, Any]], *, severity: str) -> List[Dict[str, Any]]:
    if not bounties:
        return []
    return sorted(bounties, key=lambda b: _get_bounty_sort_key(b, severity))