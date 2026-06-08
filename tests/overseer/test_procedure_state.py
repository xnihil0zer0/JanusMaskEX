"""RED oracle for overseer/procedure_state.py — durable per-conversation phase.

The procedure machine's state is READ from disk, never reconstructed: a phase
pointer plus the last recorded GateResult, keyed by conversation id under an
injected ``state_dir``, surviving a fresh load (the ``--resume``/restart case).
Conversations are isolated. An unknown conversation loads a fresh default state
rather than raising.
"""
import pytest

from overseer.procedure_state import ProcedureState, load_state, save_state
from overseer.gates import GateResult


def test_roundtrip_persists_the_phase(tmp_path):
    save_state('conv1', ProcedureState(phase='ORACLE', last_gate=None), state_dir=tmp_path)
    st = load_state('conv1', state_dir=tmp_path)
    assert st.phase == 'ORACLE'


def test_unknown_conversation_loads_a_fresh_default_state(tmp_path):
    st = load_state('never-seen', state_dir=tmp_path)
    assert isinstance(st, ProcedureState)  # a default, not a KeyError/None


def test_persists_the_last_gate_result(tmp_path):
    g = GateResult(ok=False, reason='r', fix_hint='f')
    save_state('c', ProcedureState(phase='BRIEF', last_gate=g), state_dir=tmp_path)
    st = load_state('c', state_dir=tmp_path)
    assert st.last_gate is not None
    assert st.last_gate.ok is False
    assert st.last_gate.reason == 'r'
    assert st.last_gate.fix_hint == 'f'


def test_state_is_durable_across_a_fresh_load(tmp_path):
    # simulates --resume / a daemon restart: a brand-new load sees the saved phase.
    save_state('c2', ProcedureState(phase='PLAN', last_gate=None), state_dir=tmp_path)
    assert load_state('c2', state_dir=tmp_path).phase == 'PLAN'


def test_conversations_are_isolated(tmp_path):
    save_state('a', ProcedureState(phase='SCOPE', last_gate=None), state_dir=tmp_path)
    save_state('b', ProcedureState(phase='COMMIT', last_gate=None), state_dir=tmp_path)
    assert load_state('a', state_dir=tmp_path).phase == 'SCOPE'
    assert load_state('b', state_dir=tmp_path).phase == 'COMMIT'


def test_save_overwrites_prior_state_for_same_conversation(tmp_path):
    save_state('c3', ProcedureState(phase='SCOPE', last_gate=None), state_dir=tmp_path)
    save_state('c3', ProcedureState(phase='ORACLE', last_gate=None), state_dir=tmp_path)
    assert load_state('c3', state_dir=tmp_path).phase == 'ORACLE'
