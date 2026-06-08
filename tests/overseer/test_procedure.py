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
    assert [p.name for p in proc.phases] == ['PREFLIGHT', 'STAGE', 'BUILD', 'VERIFY', 'RESTORE']


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
