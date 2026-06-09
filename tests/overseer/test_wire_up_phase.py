"""RED oracle for the WIRE_UP FSM phase (epic: wire_up_phase, leaf: wire-up-fsm-phase).

Contract: PROCEDURE_REGISTRY['dispatch'] gains a WIRE_UP phase bound to the 'wired'
gate, ordered BETWEEN the existing VERIFY and RESTORE phases, so that because RESTORE's
pass yields the terminal Complete (== DONE), DONE is UNREACHABLE while a build is
orphaned. The pure reducer `advance` is consumed unchanged: a failing wired gate at the
WIRE_UP phase must return Blocked (not advance to RESTORE).

This is a WIRING assertion on the FSM (registry order + reducer behaviour at the new
phase), not an isolated dataclass-construction test.
"""
from overseer.procedure import PROCEDURE_REGISTRY, advance, Blocked
from overseer.gates import GateResult


def _dispatch_phase_names():
    return [p.name for p in PROCEDURE_REGISTRY["dispatch"].phases]


def test_wire_up_phase_present_in_dispatch():
    assert "WIRE_UP" in _dispatch_phase_names()


def test_wire_up_ordered_between_verify_and_restore():
    names = _dispatch_phase_names()
    assert "VERIFY" in names and "RESTORE" in names
    assert names.index("VERIFY") < names.index("WIRE_UP") < names.index("RESTORE")


def test_wire_up_phase_binds_the_wired_gate():
    phase = next(p for p in PROCEDURE_REGISTRY["dispatch"].phases if p.name == "WIRE_UP")
    assert phase.gate == "wired"
    assert isinstance(phase.next_action, str) and phase.next_action.strip()


def test_orphan_at_wire_up_blocks_done():
    # A failing wired gate at WIRE_UP must Block, never advance toward RESTORE/Complete.
    proc = PROCEDURE_REGISTRY["dispatch"]
    decision = advance(proc, "WIRE_UP", GateResult(ok=False, reason="orphan", fix_hint="wire it"))
    assert isinstance(decision, Blocked)


def test_wired_at_wire_up_advances_to_restore():
    proc = PROCEDURE_REGISTRY["dispatch"]
    decision = advance(proc, "WIRE_UP", GateResult(ok=True, reason="", fix_hint=""))
    assert decision == "RESTORE"
