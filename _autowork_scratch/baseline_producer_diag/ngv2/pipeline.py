"""Deterministic, stdlib-only hunt->triage->poc->detonate->report->done orchestrator.

Drives a :class:`HuntStateMachine` through its phases over injected phase-handler
callables, detonating each poc through an injected runner via
:class:`DetonationChamber`, and returns a fixed-shape result dict. The module is
pure: no module-level state, no logging, no I/O, no randomness.
"""
from __future__ import annotations
from ngv2.detonation import DetonationChamber
from ngv2.state_machine import HuntStateMachine

def run_pipeline(handlers: dict, *, success_marker: str='VULNERABLE') -> dict:
    var_0 = HuntStateMachine()
    for var_1 in handlers['hunt']():
        var_0.add_finding(var_1)
    var_0.transition('triage')
    var_2 = handlers['triage'](list(var_0.state.findings))
    var_0.state.findings = list(var_2)
    var_0.transition('poc')
    var_3 = handlers['poc'](list(var_0.state.findings))
    var_0.transition('detonate')
    var_4 = DetonationChamber(success_marker=success_marker)
    var_5 = handlers.get('expected_fs_signature')
    var_6 = [var_4.detonate(var_7, handlers.get('target_spec'), handlers['runner'], expected_fs_signature=var_5) for var_7 in var_3]
    var_0.transition('report')
    var_8 = handlers['report'](var_0.state, var_6) if 'report' in handlers else None
    var_0.transition('done')
    return {'phase': var_0.state.phase, 'reports': [var_9.to_dict() for var_9 in var_6], 'report': var_8}