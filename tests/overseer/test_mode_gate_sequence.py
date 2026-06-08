"""RED oracle for the mode-switch SEQUENCE LOCK in overseer.mode_gate.can_switch.

While a conversation's active procedure phase is non-terminal, ``can_switch`` must
refuse EVERY target except ``observe`` (the always-available abort) and the
current mode (no-op): you cannot leave a procedure-bearing mode mid-sequence.
Once the phase reaches COMPLETE (the ``procedure.Complete`` sentinel or the
``'COMPLETE'`` string), the existing lattice rules resume unchanged. With no
active phase the function is behaviour-identical to before (every assertion in
test_mode_gate.py still holds).
"""
import pytest

from overseer.mode_gate import can_switch
from overseer.procedure import Complete


def test_no_active_phase_preserves_the_lattice():
    # observe -> brief-author is a normal R->W move (brief-author is default-available W)
    assert can_switch('observe', 'brief-author', set()) is True
    assert can_switch('observe', 'brief-author', set(), active_phase=None) is True


def test_midsequence_blocks_other_modes():
    assert can_switch('brief-author', 'dispatch', set(), active_phase='ORACLE') is False
    # even a move DOWN the lattice is blocked while a sequence is in flight
    assert can_switch('brief-author', 'analyze', set(), active_phase='ORACLE') is False


def test_midsequence_allows_observe_abort():
    assert can_switch('brief-author', 'observe', set(), active_phase='ORACLE') is True


def test_midsequence_allows_noop_to_current_mode():
    assert can_switch('brief-author', 'brief-author', set(), active_phase='ORACLE') is True


def test_midsequence_still_blocks_unlock_gated_tier_s():
    assert can_switch('brief-author', 'push', set(), active_phase='ORACLE') is False


def test_complete_string_resumes_the_lattice():
    # dispatch is a default-available W peer of brief-author -> allowed once COMPLETE
    assert can_switch('brief-author', 'dispatch', set(), active_phase='COMPLETE') is True


def test_complete_sentinel_resumes_the_lattice():
    assert can_switch('brief-author', 'dispatch', set(), active_phase=Complete) is True
