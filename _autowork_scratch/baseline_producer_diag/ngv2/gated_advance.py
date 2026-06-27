"""Gated FSM advance coordinator for NobleGreed v2.

This module exposes :func:`advance_with_gates`, which assembles a gate
evidence payload, runs the four NobleGreed validation gates through an
injected ``run_gates`` callable, and performs the FSM transition through an
injected ``advance`` callable *only* when every required gate passes.

The module is intentionally dependency-free (stdlib + typing only). Every
external seam -- the database handle, the gate runner, the transition
function and the evidence builder -- is supplied as an injected parameter,
so the module never imports or touches ``session_api`` / ``gate_executor``
/ a live database at runtime.

Failure is always closed: if evidence assembly raises, if the gate runner
raises, if any gate is missing or fails, or if the transition itself raises,
``advance`` either is not called or its failure is surfaced -- never
silently swallowed, never retried.
"""
from typing import Any, Callable, Optional
__all__ = ['advance_with_gates', 'REQUIRED_GATES']
REQUIRED_GATES = ('poc_authenticity', 'sink_presence', 'sink_reachability', 'detonation_evidence')

def _gate_passed(gate_result: Any) -> bool:
    """Return whether a single gate's result represents a pass.

    Accepts either a plain boolean or a mapping carrying a pass flag under a
    common field name (``passed`` / ``pass`` / ``ok`` / ``passing``). Anything
    that cannot be positively interpreted as a pass is treated as a failure
    (fail-closed).
    """
    if isinstance(gate_result, bool):
        return gate_result
    if isinstance(gate_result, dict):
        for field_name in ('passed', 'pass', 'ok', 'passing'):
            if field_name in gate_result:
                return bool(gate_result[field_name])
        return False
    return False

def _gate_reason(gate_result: Any) -> Optional[str]:
    """Best-effort extraction of a human-readable reason from a gate result."""
    if isinstance(gate_result, dict):
        for field_name in ('reason', 'message', 'detail', 'error'):
            value = gate_result.get(field_name)
            if value is not None:
                return str(value)
    return None

def advance_with_gates(session_id: str, db: Any, run_gates: Callable, advance: Callable, build_evidence: Callable) -> dict:
    """Coordinate the four validation gates and advance the FSM if they pass.

    Parameters
    ----------
    session_id:
        Identifier of the session whose FSM may advance.
    db:
        Opaque, injected database handle. Never opened or inspected here.
    run_gates:
        Injected callable invoked as ``run_gates(evidence, REQUIRED_GATES)``;
        expected to return a mapping of gate id -> per-gate result.
    advance:
        Injected callable invoked as ``advance(session_id, db)`` exactly once,
        and only when all four required gates pass.
    build_evidence:
        Injected callable invoked as ``build_evidence(session_id, db)`` to
        assemble the evidence payload that feeds the gates, before any gate
        runs.

    Returns
    -------
    dict
        ``{"advanced": bool, "gates": <run_gates result>,
        "transition": <advance result or None>,
        "blocked_reason": <str or None>}``.
    """
    result: dict = {'advanced': False, 'gates': None, 'transition': None, 'blocked_reason': None}
    try:
        evidence = build_evidence(session_id, db)
    except Exception as exc:
        result['blocked_reason'] = 'build_evidence raised: {0!r}'.format(exc)
        return result
    try:
        gate_results = run_gates(evidence, REQUIRED_GATES)
    except Exception as exc:
        result['blocked_reason'] = 'run_gates raised: {0!r}'.format(exc)
        return result
    result['gates'] = gate_results
    if not isinstance(gate_results, dict):
        result['blocked_reason'] = 'run_gates returned a non-mapping result; failing closed'
        return result
    failing = []
    for gate_id in REQUIRED_GATES:
        if gate_id not in gate_results:
            failing.append('{0}: missing'.format(gate_id))
            continue
        gate_result = gate_results[gate_id]
        if not _gate_passed(gate_result):
            reason = _gate_reason(gate_result)
            if reason:
                failing.append('{0}: {1}'.format(gate_id, reason))
            else:
                failing.append('{0}: failed'.format(gate_id))
    if failing:
        result['blocked_reason'] = '; '.join(failing)
        return result
    try:
        transition = advance(session_id, db)
    except Exception as exc:
        result['blocked_reason'] = 'advance raised: {0!r}'.format(exc)
        return result
    result['advanced'] = True
    result['transition'] = transition
    return result