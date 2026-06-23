"""RED behavioural oracle for harness.wire_up.validate_exemption.

This is a STANDALONE, HERMETIC unit oracle (NOT an integration test -- it does
NOT wire validate_exemption into _run_wire_up_gate or any orchestrator gate; the
word *integration* is explicitly out of scope here). It pins the adversarial
verdict table of the not-yet-existent ``validate_exemption`` against the REAL
static-reachability floor ``symbol_reachable_from_live_root``.

It is RED on HEAD: the top-level ``from harness.wire_up import validate_exemption``
raises ImportError at collection because validate_exemption / ExemptionVerdict do
not exist yet.

The non-negotiable invariants proven here:

  * ANTI-CATCH-ALL: honoring a symbol on its category *declaration alone*, while
    ignoring the floor, is a REJECT. No taxonomy category may grant honored=True
    for a floor-fail (true orphan) symbol (Cases 1 and 5).
  * staged_sibling only DEFERS (honored=False, requires_recheck=True) and NEVER
    grants suppression at this gate -- blanket-honoring staged_sibling is a
    REJECT (Cases 3 and 5).
  * honored TRACKS the real floor: stubbing the floor flips honored on both legs
    (Case 7). A hardcoded-fixture or reachability-reimplementing impl would not
    flip and is a REJECT.

The oracle imports the REAL symbols and drives them over the REAL on-disk repo
tree; it does NOT mock validate_exemption, does NOT re-implement the floor, and
does NOT hardcode the live-root list.
"""
from __future__ import annotations
from pathlib import Path
import pytest
import harness.wire_up
from harness.wire_up import LIVE_ROOTS, symbol_reachable_from_live_root, validate_exemption
REPO_ROOT = Path(harness.wire_up.__file__).resolve().parent.parent
FLOOR_PASS = [('harness/state_reconciler.py', 'detect_and_heal_stalls'), ('harness/sandbox.py', '_jailed_popen'), ('harness/orchestrator.py', '_restrict_sidecar_to_declared')]
FLOOR_FAIL = [('harness/diff_fuzzer.py', '_one_sided_fuzz'), ('harness/diff_fuzzer.py', '_capture_golden'), ('harness/agy_pool.py', 'assert_pool_invariant'), ('harness/agy_pool.py', 'effective_pool_size')]
ALL_CATEGORIES = ['pure_helper', 'config_reader', 'data_only', 'staged_sibling', '', 'wired', '__catch_all__', None]

def _floor(module_rel: str, symbol: str) -> bool:
    """Drive the REAL static-reachability floor (roots threaded from LIVE_ROOTS)."""
    return symbol_reachable_from_live_root(REPO_ROOT, module_rel, symbol, roots=LIVE_ROOTS)

def _exempt(category, module_rel: str, symbol: str):
    """Drive the REAL validate_exemption (roots threaded from LIVE_ROOTS).

    Note the interface arg order is (category, symbol, module_rel, repo_root);
    this helper keeps the (module_rel, symbol) convention used by the fixtures.
    """
    return validate_exemption(category, symbol, module_rel, REPO_ROOT, roots=LIVE_ROOTS)

def _assert_never_both_true(v) -> None:
    """honored and requires_recheck must NEVER both be True in any verdict."""
    assert not (v.honored and v.requires_recheck), f'honored and requires_recheck must never both be True: {v!r}'

def test_red_imports_and_repo_root_resolved_from_module_file():
    assert callable(validate_exemption)
    assert callable(symbol_reachable_from_live_root)
    assert isinstance(LIVE_ROOTS, list) and LIVE_ROOTS, 'LIVE_ROOTS must be a non-empty list'
    expected = Path(harness.wire_up.__file__).resolve().parent.parent
    assert REPO_ROOT == expected
    assert (REPO_ROOT / 'harness' / 'wire_up.py').is_file()

def test_sanity_guard_floor_pass_fixtures_true():
    for module_rel, symbol in FLOOR_PASS:
        assert _floor(module_rel, symbol) is True, f'FLOOR_PASS fixture drifted to unreachable: {module_rel}::{symbol}'

def test_sanity_guard_floor_fail_fixtures_false():
    for module_rel, symbol in FLOOR_FAIL:
        assert _floor(module_rel, symbol) is False, f'FLOOR_FAIL fixture drifted to reachable: {module_rel}::{symbol}'

def test_case1_orphan_pure_helper_not_honored():
    module_rel, symbol = ('harness/diff_fuzzer.py', '_one_sided_fuzz')
    assert _floor(module_rel, symbol) is False
    v = _exempt('pure_helper', module_rel, symbol)
    assert v.honored is False
    assert v.requires_recheck is False
    _assert_never_both_true(v)

def test_case1_orphan_config_reader_not_honored():
    module_rel, symbol = ('harness/diff_fuzzer.py', '_capture_golden')
    assert _floor(module_rel, symbol) is False
    v = _exempt('config_reader', module_rel, symbol)
    assert v.honored is False
    assert v.requires_recheck is False
    _assert_never_both_true(v)

def test_case1_orphan_data_only_not_honored():
    module_rel, symbol = ('harness/agy_pool.py', 'assert_pool_invariant')
    assert _floor(module_rel, symbol) is False
    v = _exempt('data_only', module_rel, symbol)
    assert v.honored is False
    assert v.requires_recheck is False
    _assert_never_both_true(v)

def test_case2_reachable_pure_helper_honored():
    module_rel, symbol = ('harness/state_reconciler.py', 'detect_and_heal_stalls')
    assert _floor(module_rel, symbol) is True
    v = _exempt('pure_helper', module_rel, symbol)
    assert v.honored is True
    assert v.requires_recheck is False
    _assert_never_both_true(v)

def test_case2_reachable_config_reader_honored():
    module_rel, symbol = ('harness/sandbox.py', '_jailed_popen')
    assert _floor(module_rel, symbol) is True
    v = _exempt('config_reader', module_rel, symbol)
    assert v.honored is True
    assert v.requires_recheck is False
    _assert_never_both_true(v)

def test_case2_reachable_data_only_honored():
    module_rel, symbol = ('harness/orchestrator.py', '_restrict_sidecar_to_declared')
    assert _floor(module_rel, symbol) is True
    v = _exempt('data_only', module_rel, symbol)
    assert v.honored is True
    assert v.requires_recheck is False
    _assert_never_both_true(v)

def test_case3_staged_sibling_floor_pass_defers_not_grants():
    module_rel, symbol = ('harness/state_reconciler.py', 'detect_and_heal_stalls')
    assert _floor(module_rel, symbol) is True
    v = _exempt('staged_sibling', module_rel, symbol)
    assert v.honored is False
    assert v.requires_recheck is True
    _assert_never_both_true(v)

def test_case3_staged_sibling_floor_fail_defers_not_grants():
    module_rel, symbol = ('harness/agy_pool.py', 'assert_pool_invariant')
    assert _floor(module_rel, symbol) is False
    v = _exempt('staged_sibling', module_rel, symbol)
    assert v.honored is False
    assert v.requires_recheck is True
    _assert_never_both_true(v)

def test_case4_empty_none_wired_catchall_category_rejected():
    module_rel, symbol = ('harness/state_reconciler.py', 'detect_and_heal_stalls')
    assert _floor(module_rel, symbol) is True
    for bad in ('', None, 'wired', '__catch_all__'):
        v = _exempt(bad, module_rel, symbol)
        assert v.honored is False, f'bad category {bad!r} must not be honored'
        assert v.requires_recheck is False, f'bad category {bad!r} must not request recheck'
        _assert_never_both_true(v)

def test_case5_anti_catch_all_no_category_suppresses_true_orphan():
    module_rel, symbol = ('harness/agy_pool.py', 'assert_pool_invariant')
    assert _floor(module_rel, symbol) is False
    for cat in ALL_CATEGORIES:
        v = _exempt(cat, module_rel, symbol)
        assert v.honored is False, f'category {cat!r} must NOT honor a true orphan'
        _assert_never_both_true(v)
        if cat == 'staged_sibling':
            assert v.requires_recheck is True
        else:
            assert v.requires_recheck is False

def test_case6_determinism_identical_verdict_floor_pass_and_floor_fail():
    pass_mod, pass_sym = ('harness/state_reconciler.py', 'detect_and_heal_stalls')
    fail_mod, fail_sym = ('harness/agy_pool.py', 'effective_pool_size')
    assert _floor(pass_mod, pass_sym) is True
    assert _floor(fail_mod, fail_sym) is False
    v1 = _exempt('pure_helper', pass_mod, pass_sym)
    v2 = _exempt('pure_helper', pass_mod, pass_sym)
    assert v1 == v2
    assert v1.honored is True
    w1 = _exempt('pure_helper', fail_mod, fail_sym)
    w2 = _exempt('pure_helper', fail_mod, fail_sym)
    assert w1 == w2
    assert w1.honored is False

def test_case7_composition_stub_true_flips_honored_on_for_orphan(monkeypatch):
    monkeypatch.setattr(harness.wire_up, 'symbol_reachable_from_live_root', lambda *a, **k: True)
    v = validate_exemption('pure_helper', 'effective_pool_size', 'harness/agy_pool.py', REPO_ROOT, roots=LIVE_ROOTS)
    assert v.honored is True
    assert v.requires_recheck is False
    _assert_never_both_true(v)

def test_case7_composition_stub_false_flips_honored_off_for_reachable(monkeypatch):
    monkeypatch.setattr(harness.wire_up, 'symbol_reachable_from_live_root', lambda *a, **k: False)
    v = validate_exemption('pure_helper', 'detect_and_heal_stalls', 'harness/state_reconciler.py', REPO_ROOT, roots=LIVE_ROOTS)
    assert v.honored is False
    assert v.requires_recheck is False
    _assert_never_both_true(v)

def test_verdict_fields_accessed_by_attribute_not_dict():
    v = _exempt('pure_helper', 'harness/state_reconciler.py', 'detect_and_heal_stalls')
    assert hasattr(v, 'honored') and hasattr(v, 'requires_recheck') and hasattr(v, 'reason')
    assert isinstance(v.honored, bool)
    assert isinstance(v.requires_recheck, bool)
    assert isinstance(v.reason, str)
    assert isinstance(v, tuple)
    with pytest.raises(TypeError):
        _ = v['honored']

def test_live_roots_imported_not_hardcoded_and_roots_threaded():
    assert LIVE_ROOTS is harness.wire_up.LIVE_ROOTS
    assert isinstance(LIVE_ROOTS, list) and LIVE_ROOTS
    module_rel, symbol = ('harness/state_reconciler.py', 'detect_and_heal_stalls')
    honored_with_roots = validate_exemption('pure_helper', symbol, module_rel, REPO_ROOT, roots=LIVE_ROOTS)
    assert honored_with_roots.honored is True
    honored_no_roots = validate_exemption('pure_helper', symbol, module_rel, REPO_ROOT, roots=[])
    assert honored_no_roots.honored is False
    assert honored_no_roots.requires_recheck is False
    _assert_never_both_true(honored_no_roots)