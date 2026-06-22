"""RED behavioral oracle for the differential self-clone / identical-candidate guard.

Pins the to-be-added self-clone guard onto the LIVE differential engine
(``harness.diff_fuzzer``): a candidate pair that is the SAME source on both
sides -- object-identical OR AST-equal -- must never score a passed differential,
while a genuinely distinct-but-equivalent pair must still run the real
differential (no over-blocking).

This oracle is RED against HEAD: there is no guard, an A-vs-A round returns
``equivalent=True``, and the helper ``_candidates_are_self_clone`` does not yet
exist. The helper is imported lazily (inside the tests) so that collection
reports a clear per-test failure rather than a whole-module collection error
before the paired implementation lands.

It exercises the live ``differential_fuzz`` behaviour directly and hermetically
with a small/fast fuzz budget; it does NOT assert against a frozen FuzzResult
literal and is NOT passable by special-casing a known input string.
"""
from __future__ import annotations
import pytest
from harness.diff_fuzzer import differential_fuzz, FuzzResult
FAST_CONFIG = {'fuzzing': {'function_level_inputs': 16, 'seed': 42}}
SELF_CLONE_SRC = 'def double(n: int) -> int:\n    return n * 2\n'
SELF_CLONE_SRC_COMMENTED = 'def double(n: int) -> int:\n    # behaviourally identical -- only this comment differs\n    return n * 2\n'
DISTINCT_A = 'def inc(n: int) -> int:\n    return n + 1\n'
DISTINCT_B = 'def inc(n: int) -> int:\n    return 1 + n\n'

def _import_self_clone_helper():
    """Lazily import the to-be-added top-level helper.

    Absent on HEAD: this raises ``ImportError`` and fails the calling test (RED)
    instead of breaking collection of the whole module.
    """
    from harness.diff_fuzzer import _candidates_are_self_clone
    return _candidates_are_self_clone

def test_same_source_object_refused_equivalent_false_with_error():
    code = SELF_CLONE_SRC
    result = differential_fuzz(code, code, 'double', FAST_CONFIG)
    assert isinstance(result, FuzzResult)
    assert result.equivalent is False
    assert isinstance(result.error, str) and result.error != ''

def test_ast_equal_clone_with_comment_also_refused():
    result = differential_fuzz(SELF_CLONE_SRC, SELF_CLONE_SRC_COMMENTED, 'double', FAST_CONFIG)
    assert isinstance(result, FuzzResult)
    assert result.equivalent is False

def test_distinct_equivalent_pair_not_refused_can_pass():
    result = differential_fuzz(DISTINCT_A, DISTINCT_B, 'inc', FAST_CONFIG)
    assert isinstance(result, FuzzResult)
    assert result.equivalent is True

def test_candidates_are_self_clone_helper_true_and_false_cases():
    _candidates_are_self_clone = _import_self_clone_helper()
    assert _candidates_are_self_clone(SELF_CLONE_SRC, SELF_CLONE_SRC) is True
    assert _candidates_are_self_clone(SELF_CLONE_SRC, SELF_CLONE_SRC_COMMENTED) is True
    assert _candidates_are_self_clone(DISTINCT_A, DISTINCT_B) is False

@pytest.mark.parametrize('src', [SELF_CLONE_SRC, DISTINCT_A, 'def square(x: int) -> int:\n    return x * x\n'])
def test_any_identical_or_ast_equal_pair_is_treated_as_self_clone(src):
    _candidates_are_self_clone = _import_self_clone_helper()
    assert _candidates_are_self_clone(src, src) is True
    reformatted = src.rstrip('\n') + '\n# trailing comment, AST-equal reformatting\n'
    assert _candidates_are_self_clone(src, reformatted) is True

def test_genuine_distinct_pair_still_runs_real_differential():
    result = differential_fuzz(DISTINCT_A, DISTINCT_B, 'inc', FAST_CONFIG)
    assert isinstance(result, FuzzResult)
    assert result.equivalent is True
    assert result.total_inputs > 0

def test_self_clone_never_reports_equivalent_true():
    identical = differential_fuzz(SELF_CLONE_SRC, SELF_CLONE_SRC, 'double', FAST_CONFIG)
    clone = differential_fuzz(SELF_CLONE_SRC, SELF_CLONE_SRC_COMMENTED, 'double', FAST_CONFIG)
    assert identical.equivalent is False
    assert clone.equivalent is False