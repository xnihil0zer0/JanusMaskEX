"""Deterministic phase->command-spec mapper for NobleGreed's bug-hunt state machine.

This module is PURE and stdlib-only: ``command_for_phase`` BUILDS the command
spec that the conductor uses to spawn a phase's agent-worker driver. It NEVER
spawns, forks, execs, subprocesses, reads/writes disk, touches the network, the
clock, or randomness, and it NEVER mutates the input ``session_ctx``.
"""
from typing import Dict
from typing import List
AGENT_PHASES = frozenset({'hunt', 'triage', 'verify', 'poc', 'detonate', 'novelty', 'report'})

def command_for_phase(phase: str, session_ctx: Dict) -> Dict:
    """Map a NobleGreed phase to the command spec for its agent worker.

    For an agent-driven phase with a valid context, returns a runnable spec::

        {"runnable": True, "phase": phase, "argv": [...],
         "output_path": str, "env": {...}}

    For a terminal/non-agent phase, an unknown phase, or a context missing
    ``session_id``/``output_dir``, fails closed::

        {"runnable": False, "phase": phase, "reason": str}

    The input ``session_ctx`` is never mutated (``env`` is built on a copy).
    When the context carries a ``db_path``, the worker env is given
    ``NGV2_SESSION_DB`` so the spawned ``python -m ngv2.workers.<phase>`` process
    can re-open the session DB and read the carried-forward findings / PoC.
    """
    if phase not in AGENT_PHASES:
        return {'runnable': False, 'phase': phase, 'reason': f'phase {phase!r} is not an agent-driven phase'}
    session_id = session_ctx.get('session_id')
    repo = session_ctx.get('repo')
    target_path = session_ctx.get('target_path')
    output_dir = session_ctx.get('output_dir')
    if not session_id:
        return {'runnable': False, 'phase': phase, 'reason': 'missing or empty session_id in session_ctx'}
    if not output_dir:
        return {'runnable': False, 'phase': phase, 'reason': 'missing or empty output_dir in session_ctx'}
    output_path = f'{output_dir}/{phase}.json'
    argv: List[str] = ['python', '-m', 'ngv2.workers.' + phase, '--session-id', session_id, '--repo', repo, '--target', target_path, '--out', output_path]
    env: Dict = dict(session_ctx.get('env') or {})
    env['NGV2_SESSION_ID'] = session_id
    db_path = session_ctx.get('db_path')
    if db_path:
        env['NGV2_SESSION_DB'] = db_path
    return {'runnable': True, 'phase': phase, 'argv': argv, 'output_path': output_path, 'env': env}