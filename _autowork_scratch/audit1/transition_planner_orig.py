"""Pure, deterministic decision brain for the NobleGreed bug-hunt state machine.

``plan_next_action(session_state)`` reads a session_state dict and returns a
fixed-shape ``{action, target_phase, reason}`` dict telling the conductor what
to do next. It is side-effect-free: no I/O, no clock, no randomness, and it
never mutates the input dict. Identical inputs yield byte-identical output.
"""
from typing import Any, Dict, Optional
PHASE_ORDER = ('source', 'hunt', 'triage', 'verify', 'poc', 'detonate', 'novelty', 'report', 'awaiting_submission', 'submitted', 'done')

def _next_phase(phase: Optional[str]) -> Optional[str]:
    """Return the phase that follows ``phase`` in the linear order, or None."""
    if phase in PHASE_ORDER:
        idx = PHASE_ORDER.index(phase)
        if idx + 1 < len(PHASE_ORDER):
            return PHASE_ORDER[idx + 1]
    return None

def plan_next_action(session_state: dict) -> dict:
    """Pure, deterministic decision brain for the NobleGreed hunt state machine.

    Reads the current ``session_state`` dict and returns a fixed-shape
    ``{'action', 'target_phase', 'reason'}`` result. No I/O, no clock, no
    randomness, no mutation -- the same input always yields the same output.

    Precedence is fail-closed: ``blocked`` is checked first, then ``done``,
    then ``awaiting_submission``. Only after those do the linear worker phases
    (hunt -> triage -> verify -> poc -> detonate -> novelty -> report) get a
    chance to spawn their stage when the corresponding completion artifact is
    absent (count missing, ``None``, or ``0``).
    """
    state = session_state or {}
    phase = state.get('phase')

    def _count(field_name: str) -> int:
        """Fail-closed read of a completion-artifact count: missing/None -> 0."""
        value = state.get(field_name)
        if value is None:
            return 0
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    # Precedence 1: a blocked session reports blocked before anything else.
    if state.get('blocked'):
        return {'action': 'blocked', 'target_phase': None,
                'reason': 'session is blocked'}

    # Precedence 2: a finished pipeline is done.
    if phase == 'done':
        return {'action': 'done', 'target_phase': None,
                'reason': 'pipeline complete'}

    # Precedence 3: the submission gate parks for human approval.
    if phase == 'awaiting_submission':
        if state.get('approved'):
            return {'action': 'advance', 'target_phase': 'submitted',
                    'reason': 'submission approved; advance to submitted'}
        return {'action': 'park_for_approval', 'target_phase': None,
                'reason': 'awaiting human approval'}

    # Middle worker phases: (phase, completion-artifact count field, next phase).
    worker_phases = [
        ('hunt', 'findings', 'triage'),
        ('triage', 'triaged', 'verify'),
        ('verify', 'verified', 'poc'),
        ('poc', 'pocs', 'detonate'),
        ('detonate', 'reports', 'novelty'),
        ('novelty', 'novelties', 'report'),
        ('report', 'report_count', 'awaiting_submission'),
    ]
    for worker_phase, count_field, next_phase in worker_phases:
        if phase == worker_phase:
            if _count(count_field) <= 0:
                return {'action': 'spawn_stage', 'target_phase': worker_phase,
                        'reason': '%s artifacts absent; spawn %s stage'
                                  % (worker_phase, worker_phase)}
            return {'action': 'apply_gates', 'target_phase': next_phase,
                    'reason': '%s artifacts present; apply gates to %s'
                              % (worker_phase, next_phase)}

    # Anything else (e.g. source, submitted): advance without a known target.
    return {'action': 'advance', 'target_phase': None,
            'reason': 'no spawn condition for phase %r' % (phase,)}
