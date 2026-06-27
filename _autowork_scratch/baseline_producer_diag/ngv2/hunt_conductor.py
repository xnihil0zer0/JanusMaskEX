"""Deterministic CONDUCTOR STEP for the NobleGreed bug-hunt FSM.

``run_conductor_step`` performs exactly ONE step of the hunt FSM: it loads the
session state via an injected seam, asks the injected transition planner what to
do next, and dispatches on the planned action over the other injected seams.

Every effect flows through callables supplied in the ``seams`` dict, so this
module spawns no real process, opens no DB, and imports no heavy module. It is
pure, total, and deterministic -- the same inputs always produce the same
output.
"""
from typing import Any, Dict

def run_conductor_step(session_id: Any, seams: Dict[str, Any]) -> Dict[str, Any]:
    """Perform exactly one deterministic step of the hunt FSM over ``seams``.

    Reads the session state, consults the injected planner, and dispatches on
    the returned action. Returns a fixed-shape result dict per action.
    """
    state = seams['load_state'](session_id)
    action_dict = seams['plan'](state)
    action = action_dict['action']
    if action == 'spawn_stage':
        ctx = seams.get('ctx')
        phase = state['phase']
        cmd = seams['command_for_phase'](phase, ctx)
        out = seams['spawn'](cmd)
        arts = seams['harvest'](phase, out)
        seams['persist'](session_id, phase, arts)
        return {'step': 'spawned', 'phase': phase, 'n_artifacts': len(arts)}
    if action == 'apply_gates':
        target_phase = action_dict['target_phase']
        evidence = seams['build_evidence'](state)
        g = seams['run_gates'](state['phase'], target_phase, evidence)
        if g['advance']:
            seams['advance'](session_id)
            return {'step': 'advanced', 'to': target_phase}
        return {'step': 'blocked', 'blocked_by': g['blocked_by']}
    if action == 'park_for_approval':
        return {'step': 'parked'}
    if action == 'advance':
        seams['advance'](session_id, state.get('approval'))
        return {'step': 'advanced', 'to': action_dict.get('target_phase')}
    if action == 'done':
        return {'step': 'done'}
    if action == 'blocked':
        return {'step': 'blocked', 'blocked_by': action_dict.get('reason')}
    return {'step': 'blocked', 'blocked_by': action}