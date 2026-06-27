"""Deterministic may_confirm gate executor for NobleGreed phase transitions.

Maps a phase transition (from_phase, to_phase) to its applicable may_confirm
gates, calls each live gate function over an evidence dict, reads each gate's
top-level boolean ``may_confirm`` field, and returns a fixed-shape advance/block
decision so the four orphaned confirmation gates (poc_authenticity,
detonation_evidence, sink_presence, sink_reachability) are enforced between
stages.

Pure and deterministic: stdlib + the four ngv2 gate imports only. No I/O, no
network, no subprocesses, no wall-clock, no randomness, no module-level side
effects. Fail-closed: a missing required evidence key blocks the transition
(the gate is not called) rather than raising.
"""
from typing import Callable
from typing import Dict
from typing import List
from typing import Tuple
from ngv2.poc_authenticity_gate import classify_poc_authenticity
from ngv2.detonation_evidence_gate import classify_detonation_evidence
from ngv2.sink_presence_gate import verify_sink_present
from ngv2.sink_reachability_gate import assess_sink_reachability
_GateSpec = Tuple[str, Tuple[str, ...], Callable[[dict], dict]]

class TypedTerminal:
    EMPTY_HUNT = 'empty_hunt'
    NO_TEMPLATE = 'no_template'
    REFUTED = 'refuted'
    MISSING_EVIDENCE = 'missing_evidence'
    SERVICE_NO_BIND = 'service_no_bind'
    NO_SOURCE = 'no_source'
    NO_FINDINGS = 'no_findings'
    NO_TRIAGE = 'no_triage'
    NO_VERIFY = 'no_verify'
    NO_NOVELTY = 'no_novelty'
    NO_REPORT = 'no_report'
    NO_APPROVAL = 'no_approval'
    NO_SUBMISSION = 'no_submission'
_TRANSITION_GATES: Dict[Tuple[str, str], Tuple[_GateSpec, ...]] = {('source', 'hunt'): (('source_ready', ('source_ready',), lambda ev: {'may_confirm': bool(ev.get('source_ready')), 'terminal': TypedTerminal.NO_SOURCE}),), ('hunt', 'triage'): (('findings', ('findings',), lambda ev: {'may_confirm': bool(ev.get('findings')), 'terminal': TypedTerminal.NO_FINDINGS}),), ('triage', 'verify'): (('triage_result', ('triage_result',), lambda ev: {'may_confirm': bool(ev.get('triage_result')), 'terminal': TypedTerminal.NO_TRIAGE}),), ('verify', 'poc'): (('verify_result', ('verify_result',), lambda ev: {'may_confirm': bool(ev.get('verify_result')), 'terminal': TypedTerminal.NO_VERIFY}),), ('poc', 'detonate'): (('poc_authenticity', ('poc_source', 'target_import_names'), lambda ev: classify_poc_authenticity(ev['poc_source'], ev['target_import_names'])),), ('detonate', 'novelty'): (('detonation_evidence', ('detonation_report',), lambda ev: classify_detonation_evidence(ev['detonation_report'])), ('sink_presence', ('target_source', 'expected_signature'), lambda ev: verify_sink_present(ev['target_source'], ev['expected_signature'])), ('sink_reachability', ('sink_name', 'call_sites'), lambda ev: assess_sink_reachability(ev['sink_name'], ev['call_sites']))), ('novelty', 'report'): (('novelty_result', ('novelty_result',), lambda ev: {'may_confirm': bool(ev.get('novelty_result')), 'terminal': TypedTerminal.NO_NOVELTY}),), ('report', 'awaiting_submission'): (('report_artifact', ('report_artifact',), lambda ev: {'may_confirm': bool(ev.get('report_artifact')), 'terminal': TypedTerminal.NO_REPORT}),), ('awaiting_submission', 'submitted'): (('approval', ('approval',), lambda ev: {'may_confirm': bool(ev.get('approval')), 'terminal': TypedTerminal.NO_APPROVAL}),), ('submitted', 'done'): (('submission_result', ('submission_result',), lambda ev: {'may_confirm': bool(ev.get('submission_result')), 'terminal': TypedTerminal.NO_SUBMISSION}),)}

def run_gates(from_phase: str, to_phase: str, evidence: dict) -> dict:
    """Run the may_confirm gates applicable to a ``from_phase -> to_phase`` move.

    Returns a fixed three-key dict::

        {"advance": bool, "blocked_by": list[str], "results": dict[str, dict]}

    ``advance`` is True iff every applicable gate was actually called (no
    required evidence missing) and every called gate returned
    ``may_confirm == True``. A transition with no applicable gate advances with
    empty ``blocked_by`` and empty ``results``.

    Fail-closed: a missing required evidence key means the gate is skipped,
    ``"<gate_name>:missing_evidence"`` is recorded in ``blocked_by``,
    ``advance`` is False, and no ``KeyError`` escapes.
    """
    is_consecutive = False
    if from_phase in PHASE_ORDER and to_phase in PHASE_ORDER:
        from_idx = PHASE_ORDER.index(from_phase)
        to_idx = PHASE_ORDER.index(to_phase)
        if to_idx == from_idx + 1:
            is_consecutive = True
    gates = _TRANSITION_GATES.get((from_phase, to_phase), ())
    if is_consecutive:
        if 'structural' in evidence:
            structural_gate = ('structural', ('structural',), lambda ev: {'may_confirm': ev.get('structural') is True})
            gates = gates + (structural_gate,)
        if 'pre_existing' in evidence:
            pre_existing_gate = ('pre_existing', ('pre_existing',), lambda ev: {'may_confirm': ev.get('pre_existing') is True})
            gates = gates + (pre_existing_gate,)
    blocked_by: List[str] = []
    results: Dict[str, Any] = {}
    for name, req_fields, caller in gates:
        if any((field_name not in evidence for field_name in req_fields)):
            if name not in ('structural', 'pre_existing') and evidence.get('structural') is True and (evidence.get('pre_existing') is True):
                continue
            blocked_by.append('{}:missing_evidence'.format(name))
            continue
        result = caller(evidence)
        if name in ('structural', 'pre_existing'):
            results[name] = result if isinstance(result, bool) else bool(result.get('may_confirm'))
        else:
            results[name] = result
        val = result.get('may_confirm') if isinstance(result, dict) else result
        if not bool(val):
            blocked_by.append(name)
    deduped: List[str] = []
    seen = set()
    for entry in blocked_by:
        if entry not in seen:
            seen.add(entry)
            deduped.append(entry)
    return {'advance': deduped == [], 'blocked_by': deduped, 'results': results}
'Deterministic may_confirm gate executor for NobleGreed phase transitions.\n\nMaps a phase transition (from_phase, to_phase) to its applicable may_confirm\ngates, calls each live gate function over an evidence dict, reads each gate\'s\ntop-level boolean ``may_confirm`` field, and returns a fixed-shape advance/block\ndecision so the four orphaned confirmation gates (poc_authenticity,\ndetonation_evidence, sink_presence, sink_reachability) are enforced between\nstages.\n\nEach transition gates the LEAVING phase\'s OWN just-produced evidence, which is\nwhat is actually available when the conductor applies the gate:\n\n  ("poc","detonate")      -> poc_authenticity            (poc_source exists)\n  ("detonate","novelty")  -> detonation_evidence\n                             AND sink_presence\n                             AND sink_reachability        (detonation_report +\n                                                           target source exist)\n  any other transition    -> none (advance True)\n\nThe earlier graph gated ("verify","poc") on ``poc_source`` and ("poc","detonate")\non ``detonation_report`` -- i.e. it required the NEXT phase\'s output to LEAVE the\ncurrent one, deadlocking every automated forward run. ("verify","poc") is now\nungated (the PoC is written DURING the poc phase, then validated on the way out\nat poc->detonate), and detonation evidence is validated on the way out of\ndetonate, not on the way in.\n\nPure and deterministic: stdlib + the four ngv2 gate imports only. No I/O, no\nnetwork, no subprocesses, no wall-clock, no randomness, no module-level side\neffects. Fail-closed: a missing required evidence key blocks the transition\n(the gate is not called) rather than raising.\n'
import re
from typing import Any

def no_template_terminal(cwe: Any) -> str:
    s = str(cwe).strip()
    if s.upper().startswith('CWE-'):
        num = s[4:].strip()
    elif s.upper().startswith('CWE'):
        num = s[3:].strip()
    else:
        num = s
    return f'no_template:CWE-{num}'
from ngv2.fsm_evidence import PHASE_ORDER