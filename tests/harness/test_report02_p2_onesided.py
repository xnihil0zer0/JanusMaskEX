"""RED oracle for the one-sided fail-closed degrade ladder (shadow-mode, default-OFF).

Task: report02-p2-onesided-oracle.

This is a PAIRED RED oracle authored ahead of ``report02-p2-onesided-impl``.  It
pins the observable behaviour of the one-sided verification ladder and its
shadow-mode wiring into ``harness/diff_fuzzer.py``:

  * OFF byte-identity         -- flag False => byte-identical to HEAD's waiver skip,
                                 oracle never consulted.
  * ON shadow non-blocking    -- flag True => SAME one-sided scenario still returns
                                 ``equivalent is True`` (non-blocking) while shadow
                                 telemetry (verdict + tier) is logged at INFO.
  * Oracle verdict correctness -- ``_metamorphic_oracle`` / ``_golden_oracle`` return
                                 'verified' / 'rejected' as specified.
  * Fail-closed                -- empty golden and zero-input strategy each yield
                                 'unverified' mapping to ``equivalent is False``.
  * Seed determinism           -- same seed => identical inputs + verdict; a different
                                 seed => different inputs.
  * ``BYPASS_FUZZER_TYPES`` invariant -- the diff_fuzzer alias equals the canonical
                                 taxonomies frozenset.

Pinned calling conventions (the impl conforms to THIS oracle):

  * Verdicts are the plain strings ``'verified'`` / ``'rejected'`` / ``'unverified'``.
  * ``_metamorphic_oracle(fn, strategy, relations=(), *, count, seed) -> str`` draws
    ``count`` seeded values from ``strategy``, ALWAYS prepends a determinism relation
    (calls ``fn`` twice on the same value and compares), then checks every supplied
    relation.  A *relation* is a callable ``relation(fn, value) -> bool``.
  * ``_golden_oracle(fn, golden) -> str`` replays the captured ``{input: output}``
    mapping through ``fn``; an empty mapping is 'unverified' (nothing to compare).
  * ``_capture_golden(fn, strategy, *, count, seed) -> dict`` records a deterministic
    ``{input: output}`` golden from a reference implementation.
  * ``_one_sided_fuzz(fn, strategy, *, relations=(), golden=None, count, seed)`` runs
    the ladder and returns a result carrying a verdict + tier/telemetry whose
    ``equivalent`` is True iff the verdict is 'verified' (fail-closed otherwise).

It references ONLY ``harness.diff_fuzzer`` symbols (never the research seed file).
"""
from __future__ import annotations
import logging
import pytest
from hypothesis import strategies as st
import harness.diff_fuzzer as diff_fuzzer
LOGGER_NAME = 'janusmask.diff_fuzzer'
CODE_A = 'def target(x: int) -> int:\n    return x + 1\n'
CODE_B = 'def helper(y: int) -> int:\n    return y - 1\n'
try:
    _BYPASS_TYPES = sorted(diff_fuzzer.FUZZ_BYPASS_META_TYPES)
except Exception:
    _BYPASS_TYPES = []
BYPASS_META_TYPE = _BYPASS_TYPES[0] if _BYPASS_TYPES else 'test_authoring'
TASK_ONE_SIDED = {'task_id': 'one_sided_scenario', 'meta_task_type': BYPASS_META_TYPE, 'constraints': {'function_signature': 'def target(x: int) -> int'}}
CONFIG = {'fuzzing': {'function_level_inputs': 25, 'float_tolerance': 1e-09, 'seed': 42}, 'batch_execution': {'enabled': False}}

def _verdict_of(res: object) -> str | None:
    if isinstance(res, str):
        return res
    if hasattr(res, 'verdict'):
        return getattr(res, 'verdict')
    if isinstance(res, dict) and 'verdict' in res:
        return res['verdict']
    if isinstance(res, (tuple, list)) and res and isinstance(res[0], str):
        return res[0]
    return None

def _equivalent_of(res: object) -> bool:
    if isinstance(res, bool):
        return res
    if hasattr(res, 'equivalent'):
        return bool(getattr(res, 'equivalent'))
    if isinstance(res, dict) and 'equivalent' in res:
        return bool(res['equivalent'])
    verdict = _verdict_of(res)
    if verdict is not None:
        return verdict == 'verified'
    raise AssertionError(f'cannot derive `equivalent` from one-sided result {res!r}')

def _abs_fn(x: int) -> int:
    return abs(x)

def _add_one(x: int) -> int:
    return x + 1

def _list_sum(values: list[int]) -> int:
    return sum(values)

def _make_impure():
    """A non-deterministic fn: each call returns a different value."""
    counter = {'n': 0}

    def impure(x: int) -> int:
        counter['n'] += 1
        return counter['n']
    return impure
_IDEMPOTENCE = lambda fn, x: fn(fn(x)) == fn(x)
_ORDER_INVARIANCE = lambda fn, xs: fn(xs) == fn(list(reversed(xs)))

def test_off_byte_identity_one_side_waiver_returns_equivalent_true_with_skip(monkeypatch):
    monkeypatch.setattr(diff_fuzzer, '_onesided_oracle_enabled', lambda: False)
    res = diff_fuzzer.fuzz_from_task(CODE_A, CODE_B, TASK_ONE_SIDED, CONFIG)
    assert isinstance(res, diff_fuzzer.FuzzResult)
    assert res.equivalent is True
    assert res.skipped_reason is not None
    assert res.error is None
    assert 'one side only' in res.skipped_reason

def test_off_oracle_not_consulted_when_flag_false(monkeypatch):
    monkeypatch.setattr(diff_fuzzer, '_onesided_oracle_enabled', lambda: False)
    consulted = {'hit': False}

    def _spy(*args, **kwargs):
        consulted['hit'] = True
        raise AssertionError('one-sided oracle must NOT be consulted in OFF mode')
    monkeypatch.setattr(diff_fuzzer, '_one_sided_fuzz', _spy)
    res = diff_fuzzer.fuzz_from_task(CODE_A, CODE_B, TASK_ONE_SIDED, CONFIG)
    assert res.equivalent is True
    assert res.skipped_reason is not None
    assert consulted['hit'] is False

def test_on_shadow_still_returns_equivalent_true_non_blocking(monkeypatch):
    monkeypatch.setattr(diff_fuzzer, '_onesided_oracle_enabled', lambda: True)
    res = diff_fuzzer.fuzz_from_task(CODE_A, CODE_B, TASK_ONE_SIDED, CONFIG)
    assert isinstance(res, diff_fuzzer.FuzzResult)
    assert res.equivalent is True
    assert res.skipped_reason is not None

def test_on_shadow_logs_verdict_and_tier_via_caplog(monkeypatch, caplog):
    monkeypatch.setattr(diff_fuzzer, '_onesided_oracle_enabled', lambda: True)
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        res = diff_fuzzer.fuzz_from_task(CODE_A, CODE_B, TASK_ONE_SIDED, CONFIG)
    assert res.equivalent is True
    text = caplog.text.lower()
    assert 'verdict' in text
    assert 'tier' in text
    assert any((v in text for v in ('verified', 'rejected', 'unverified')))

def test_metamorphic_oracle_verified_for_faithful_idempotent_order_invariant():
    verdict_idem = diff_fuzzer._metamorphic_oracle(_abs_fn, st.integers(min_value=-1000, max_value=1000), relations=(_IDEMPOTENCE,), count=50, seed=123)
    assert verdict_idem == 'verified'
    verdict_order = diff_fuzzer._metamorphic_oracle(_list_sum, st.lists(st.integers(min_value=-1000, max_value=1000), max_size=8), relations=(_ORDER_INVARIANCE,), count=50, seed=123)
    assert verdict_order == 'verified'

def test_metamorphic_oracle_rejected_for_broken_idempotence_and_impure():
    verdict_broken = diff_fuzzer._metamorphic_oracle(_add_one, st.integers(min_value=-1000, max_value=1000), relations=(_IDEMPOTENCE,), count=50, seed=123)
    assert verdict_broken == 'rejected'
    verdict_impure = diff_fuzzer._metamorphic_oracle(_make_impure(), st.integers(min_value=-1000, max_value=1000), relations=(), count=50, seed=123)
    assert verdict_impure == 'rejected'

def test_golden_oracle_verified_on_match_rejected_on_drift():

    def reference(x: int) -> int:
        return x * 2

    def drifted(x: int) -> int:
        return x * 2 + 1
    strategy = st.integers(min_value=-100, max_value=100)
    golden = diff_fuzzer._capture_golden(reference, strategy, count=30, seed=7)
    assert golden, 'captured golden must be non-empty'
    assert diff_fuzzer._golden_oracle(reference, golden) == 'verified'
    assert diff_fuzzer._golden_oracle(drifted, golden) == 'rejected'

def test_fail_closed_empty_golden_and_zero_input_strategy_unverified_equivalent_false():

    def pure(x: int) -> int:
        return x
    assert diff_fuzzer._golden_oracle(pure, {}) == 'unverified'
    zero_verdict = diff_fuzzer._metamorphic_oracle(pure, st.integers(), relations=(), count=0, seed=1)
    assert zero_verdict == 'unverified'
    res_zero = diff_fuzzer._one_sided_fuzz(pure, st.integers(), count=0, seed=1)
    assert _verdict_of(res_zero) == 'unverified'
    assert _equivalent_of(res_zero) is False
    res_empty_golden = diff_fuzzer._one_sided_fuzz(pure, st.integers(), golden={}, count=0, seed=1)
    assert _verdict_of(res_empty_golden) == 'unverified'
    assert _equivalent_of(res_empty_golden) is False

def test_seed_determinism_same_seed_identical_inputs_and_verdict_diff_seed_differs():

    def square(x: int) -> int:
        return x * x
    strategy = st.integers(min_value=-1000000, max_value=1000000)
    golden_a = diff_fuzzer._capture_golden(square, strategy, count=25, seed=2024)
    golden_b = diff_fuzzer._capture_golden(square, strategy, count=25, seed=2024)
    golden_c = diff_fuzzer._capture_golden(square, strategy, count=25, seed=9999)
    assert golden_a == golden_b
    assert set(golden_a) != set(golden_c)
    verdict_a = diff_fuzzer._metamorphic_oracle(square, strategy, relations=(), count=25, seed=2024)
    verdict_b = diff_fuzzer._metamorphic_oracle(square, strategy, relations=(), count=25, seed=2024)
    assert verdict_a == verdict_b

def test_bypass_fuzzer_types_frozenset_equals_head_membership():
    from harness.planner import taxonomies
    alias = diff_fuzzer.FUZZ_BYPASS_META_TYPES
    assert isinstance(alias, frozenset)
    assert len(alias) > 0
    assert alias == taxonomies.BYPASS_FUZZER_TYPES

def test_absent_on_both_sides_branch_remains_documented_skip(monkeypatch):
    monkeypatch.setattr(diff_fuzzer, '_onesided_oracle_enabled', lambda: False)
    code_a = 'def helper(x: int) -> int:\n    return x\n'
    code_b = 'def other(y: int) -> int:\n    return y\n'
    task = {'task_id': 'both_absent_scenario', 'meta_task_type': BYPASS_META_TYPE, 'constraints': {'function_signature': 'def target(x: int) -> int'}}
    res = diff_fuzzer.fuzz_from_task(code_a, code_b, task, CONFIG)
    assert isinstance(res, diff_fuzzer.FuzzResult)
    assert res.equivalent is True
    assert res.skipped_reason is not None
    assert res.error is None