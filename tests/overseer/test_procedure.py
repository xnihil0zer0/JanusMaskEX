"""RED oracle for overseer/procedure.py — the per-mode phase reducer.

PROCEDURE_REGISTRY maps the four procedure-bearing modes to an ordered list of
phases; each phase binds a gate NAME (a string resolved against overseer.gates)
plus a single human-readable next-action string. ``advance(procedure, phase,
gate_result)`` is the PURE reducer: a failed gate yields ``Blocked(reason,
fix_hint)``; a passing gate yields the next phase name; a passing gate on the
LAST phase yields the ``Complete`` singleton. No I/O, no spawn — pure data + logic.
"""
import pytest

from overseer.procedure import (
    Phase,
    Procedure,
    PROCEDURE_REGISTRY,
    advance,
    Blocked,
    Complete,
)
from overseer.gates import GateResult


def _passed():
    return GateResult(ok=True, reason='', fix_hint='')


def _failed():
    return GateResult(ok=False, reason='gate said no', fix_hint='do the thing')


# --- registry shape -----------------------------------------------------------

def test_registry_has_the_four_procedure_modes():
    for mode in ('brief-author', 'oracle-author', 'dispatch', 'push'):
        assert mode in PROCEDURE_REGISTRY


def test_brief_author_phase_order_matches_the_recipe():
    proc = PROCEDURE_REGISTRY['brief-author']
    assert [p.name for p in proc.phases] == ['SCOPE', 'ORACLE', 'COMMIT', 'BRIEF', 'PLAN']


def test_dispatch_phase_order_matches_the_recipe():
    proc = PROCEDURE_REGISTRY['dispatch']
    # WIRE_UP inserted between VERIFY and RESTORE (wire_up_phase epic) so DONE
    # (the terminal Complete reached after RESTORE) is unreachable while orphaned.
    assert [p.name for p in proc.phases] == ['PREFLIGHT', 'STAGE', 'BUILD', 'VERIFY', 'WIRE_UP', 'RESTORE']


def test_push_phase_order_matches_the_recipe():
    proc = PROCEDURE_REGISTRY['push']
    assert [p.name for p in proc.phases] == ['SWEEP', 'ZERO_REG', 'POSTURE', 'PUSH']


def test_every_phase_binds_a_gate_name_and_a_next_action():
    for proc in PROCEDURE_REGISTRY.values():
        for ph in proc.phases:
            assert isinstance(ph.gate, str) and ph.gate
            assert isinstance(ph.next_action, str) and ph.next_action


# --- the reducer --------------------------------------------------------------

def test_advance_blocks_on_a_failed_gate():
    proc = PROCEDURE_REGISTRY['brief-author']
    d = advance(proc, 'SCOPE', _failed())
    assert isinstance(d, Blocked)
    assert d.reason == 'gate said no'
    assert d.fix_hint == 'do the thing'


def test_advance_returns_next_phase_on_pass():
    proc = PROCEDURE_REGISTRY['brief-author']
    assert advance(proc, 'SCOPE', _passed()) == 'ORACLE'
    assert advance(proc, 'ORACLE', _passed()) == 'COMMIT'


def test_advance_completes_after_the_last_phase():
    proc = PROCEDURE_REGISTRY['brief-author']
    assert advance(proc, 'PLAN', _passed()) is Complete


def test_advance_on_failed_last_phase_still_blocks_not_completes():
    proc = PROCEDURE_REGISTRY['brief-author']
    assert isinstance(advance(proc, 'PLAN', _failed()), Blocked)


# --- follow-up: pipeline-overseer (daemon-supervisor) procedure ---------------
# The daemon-supervisor mode (already in the mode registry) gains a procedure so
# overseeing the pipeline is itself a hard-blocked, guided sequence; it inherits
# the sequence-lock + per-turn guidance for free via the enforcement layer.

def test_registry_includes_daemon_supervisor_pipeline_overseer():
    assert 'daemon-supervisor' in PROCEDURE_REGISTRY


def test_daemon_supervisor_phase_order():
    proc = PROCEDURE_REGISTRY['daemon-supervisor']
    assert [p.name for p in proc.phases] == ['OBSERVE', 'HEALTH', 'RECONCILE', 'REPORT']


def test_daemon_supervisor_advances_and_completes():
    proc = PROCEDURE_REGISTRY['daemon-supervisor']
    assert advance(proc, 'OBSERVE', _passed()) == 'HEALTH'
    assert advance(proc, 'REPORT', _passed()) is Complete
    assert isinstance(advance(proc, 'HEALTH', _failed()), Blocked)


# --- follow-up: red-oracle-author procedure (RED-first) ----------------------
# oracle-author is refined to an explicitly RED-first sequence whose RED phase
# binds the oracle_is_red gate — you cannot leave RED until the oracle fails.

def test_oracle_author_is_red_first():
    proc = PROCEDURE_REGISTRY['oracle-author']
    assert [p.name for p in proc.phases] == ['SCOPE', 'DRAFT', 'RED', 'COMMIT']


def test_oracle_author_red_phase_binds_the_oracle_is_red_gate():
    proc = PROCEDURE_REGISTRY['oracle-author']
    red = [p for p in proc.phases if p.name == 'RED'][0]
    assert 'red' in red.gate.lower()  # the RED phase's gate is oracle_is_red


def test_oracle_author_advances_through_red_to_commit():
    proc = PROCEDURE_REGISTRY['oracle-author']
    assert advance(proc, 'DRAFT', _passed()) == 'RED'
    assert advance(proc, 'RED', _passed()) == 'COMMIT'
    assert advance(proc, 'COMMIT', _passed()) is Complete
