"""Bounded conductor loop driven entirely by an injected seam.

This module provides :func:`run_until_terminal`, a deterministic, side-effect
free loop that repeatedly invokes a conductor-step callable supplied via the
``seams`` mapping until a terminal step is observed or a step cap is reached.

No subprocess, network, or model work is performed here -- the only behaviour
is to invoke the callable found at ``seams['run_conductor_step']``.
"""
from typing import Any, Dict, List, Mapping, Optional
TERMINAL_STEPS = frozenset({'done', 'parked', 'blocked'})

def run_until_terminal(session_id: Any, seams: Mapping[str, Any], max_steps: int) -> Dict[str, Any]:
    """Drive the injected conductor-step callable to a terminal step or a cap.

    On each iteration the conductor-step callable is resolved from
    ``seams['run_conductor_step']`` and invoked with ``(session_id, seams)``.
    Each returned step dict is appended to the trace in invocation order. The
    loop stops as soon as the returned step's ``'step'`` value is in
    :data:`TERMINAL_STEPS`, or once ``max_steps`` iterations have run.

    Args:
        session_id: Opaque session identifier passed through to the seam.
        seams: Mapping holding the injected ``'run_conductor_step'`` callable.
        max_steps: Maximum number of iterations to perform.

    Returns:
        A dict ``{'steps': list, 'final_step': last-step-or-None}`` where
        ``steps`` are the returned step dicts in invocation order and
        ``final_step`` is the last returned step (or ``None`` if none ran).
    """
    steps: List[Any] = []
    final_step: Optional[Any] = None
    while len(steps) < max_steps:
        run_conductor_step = seams['run_conductor_step']
        step = run_conductor_step(session_id, seams)
        steps.append(step)
        final_step = step
        if step.get('step') in TERMINAL_STEPS:
            break
    return {'steps': steps, 'final_step': final_step}