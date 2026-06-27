"""Deterministic may_confirm gate executor for NobleGreed phase transitions.

Maps a phase transition (from_phase, to_phase) to its applicable may_confirm
gates, calls each live gate function over an evidence dict, reads each gate's
top-level boolean ``may_confirm`` field, and returns a fixed-shape advance/block
decision so the four orphaned confirmation gates (poc_authenticity,
detonation_evidence, sink_presence, sink_reachability) are enforced between
stages.

Each transition gates the LEAVING phase's OWN just-produced evidence, which is
what is actually available when the conductor applies the gate:

  ("poc","detonate")      -> poc_authenticity            (poc_source exists)
  ("detonate","novelty")  -> detonation_evidence
                             AND sink_presence
                             AND sink_reachability        (detonation_report +
                                                           target source exist)
  any other transition    -> none (advance True)

The earlier graph gated ("verify","poc") on ``poc_source`` and ("poc","detonate")
on ``detonation_report`` -- i.e. it required the NEXT phase's output to LEAVE the
current one, deadlocking every automated forward run. ("verify","poc") is now
ungated (the PoC is written DURING the poc phase, then validated on the way out
at poc->detonate), and detonation evidence is validated on the way out of
detonate, not on the way in.

Pure and deterministic: stdlib + the four ngv2 gate imports only. No I/O, no
network, no subprocesses, no wall-clock, no randomness, no module-level side
effects. Fail-closed: a missing required evidence key blocks the transition
(the gate is not called) rather than raising.
"""
from typing import Callable, Dict, List, Tuple
from ngv2.poc_authenticity_gate import classify_poc_authenticity
from ngv2.detonation_evidence_gate import classify_detonation_evidence
from ngv2.sink_presence_gate import verify_sink_present
from ngv2.sink_reachability_gate import assess_sink_reachability
_GateSpec = Tuple[str, Tuple[str, ...], Callable[[dict], dict]]
_TRANSITION_GATES: Dict[Tuple[str, str], Tuple[_GateSpec, ...]] = {
    ('poc', 'detonate'): (
        ('poc_authenticity', ('poc_source', 'target_import_names'),
         lambda ev: classify_poc_authenticity(ev['poc_source'], ev['target_import_names'])),
    ),
    ('detonate', 'novelty'): (
        ('detonation_evidence', ('detonation_report',),
         lambda ev: classify_detonation_evidence(ev['detonation_report'])),
        ('sink_presence', ('target_source', 'expected_signature'),
         lambda ev: verify_sink_present(ev['target_source'], ev['expected_signature'])),
        ('sink_reachability', ('sink_name', 'call_sites'),
         lambda ev: assess_sink_reachability(ev['sink_name'], ev['call_sites'])),
    ),
}

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
    gates = _TRANSITION_GATES.get((from_phase, to_phase), ())
    blocked_by: List[str] = []
    results: Dict[str, dict] = {}
    for name, required_keys, caller in gates:
        if any((req_key not in evidence for req_key in required_keys)):
            blocked_by.append('{}:missing_evidence'.format(name))
            continue
        result = caller(evidence)
        results[name] = result
        if not bool(result['may_confirm']):
            blocked_by.append(name)
    deduped: List[str] = []
    seen = set()
    for entry in blocked_by:
        if entry not in seen:
            seen.add(entry)
            deduped.append(entry)
    return {'advance': deduped == [], 'blocked_by': deduped, 'results': results}
