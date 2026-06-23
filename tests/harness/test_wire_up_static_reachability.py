"""RED behavioral oracle for ``harness.wire_up.symbol_reachable_from_live_root``.

This is a test-first oracle for the not-yet-existent pure primitive::

    symbol_reachable_from_live_root(repo_root, module_rel, symbol,
                                    *, roots=LIVE_ROOTS) -> bool

On HEAD the symbol is ABSENT, so the top-level ``from harness.wire_up import
symbol_reachable_from_live_root`` below raises ``ImportError`` and the whole
module errors at collection -- the intended RED state (not a soft skip). TASK 2
adds the primitive and turns this green.

The oracle imports the REAL function (and ``LIVE_ROOTS``) from
``harness.wire_up``, resolves the REAL repo root deterministically from the
module's ``__file__``, and drives the primitive against the REAL repo tree:
the 3 ground-truth statically-reachable subjects must read ``True`` and the 4
ground-truth genuine orphans must read ``False``. Nothing is mocked --
``discover_modules`` / ``_resolved_graph`` and the reachability computation run
for real, and no verdict is pre-computed from a private helper or frozen map.
"""
from __future__ import annotations
from pathlib import Path
import harness.wire_up
from harness.wire_up import LIVE_ROOTS, symbol_reachable_from_live_root
REPO_ROOT = Path(harness.wire_up.__file__).resolve().parent.parent
REACHABLE = [('harness/orchestrator.py', '_restrict_sidecar_to_declared'), ('harness/sandbox.py', '_jailed_popen'), ('harness/state_reconciler.py', 'detect_and_heal_stalls')]
ORPHANS = [('harness/diff_fuzzer.py', '_one_sided_fuzz'), ('harness/diff_fuzzer.py', '_capture_golden'), ('harness/agy_pool.py', 'assert_pool_invariant'), ('harness/agy_pool.py', 'effective_pool_size')]

def test_reachable_restrict_sidecar_to_declared_true():
    """Depth-1 callable inside a LIVE_ROOT file is symbol-reachable."""
    assert symbol_reachable_from_live_root(REPO_ROOT, 'harness/orchestrator.py', '_restrict_sidecar_to_declared') is True

def test_reachable_jailed_popen_via_method_body_true():
    """Referenced only inside the Sandbox.execute METHOD -> forces method-body
    scanning; a primitive skipping class/method bodies would miss it."""
    assert symbol_reachable_from_live_root(REPO_ROOT, 'harness/sandbox.py', '_jailed_popen') is True

def test_reachable_detect_and_heal_stalls_transitive_true():
    """Reached transitively cross-module via reap_orphaned_workdirs from the
    autowork_daemon LIVE_ROOT (multi-hop module + cross-module symbol)."""
    assert symbol_reachable_from_live_root(REPO_ROOT, 'harness/state_reconciler.py', 'detect_and_heal_stalls') is True

def test_orphan_one_sided_fuzz_false():
    """Genuine orphan symbol in a module-reachable host -> not symbol-reachable."""
    assert symbol_reachable_from_live_root(REPO_ROOT, 'harness/diff_fuzzer.py', '_one_sided_fuzz') is False

def test_orphan_capture_golden_false():
    """Genuine orphan symbol in a module-reachable host -> not symbol-reachable."""
    assert symbol_reachable_from_live_root(REPO_ROOT, 'harness/diff_fuzzer.py', '_capture_golden') is False

def test_orphan_assert_pool_invariant_false():
    """Genuine orphan symbol in a module-reachable host -> not symbol-reachable."""
    assert symbol_reachable_from_live_root(REPO_ROOT, 'harness/agy_pool.py', 'assert_pool_invariant') is False

def test_orphan_effective_pool_size_false():
    """Genuine orphan symbol in a module-reachable host -> not symbol-reachable."""
    assert symbol_reachable_from_live_root(REPO_ROOT, 'harness/agy_pool.py', 'effective_pool_size') is False

def test_live_roots_imported_not_hardcoded():
    """LIVE_ROOTS is the imported live-root seed, not a re-hardcoded list."""
    assert LIVE_ROOTS is harness.wire_up.LIVE_ROOTS
    assert LIVE_ROOTS, 'LIVE_ROOTS must be a non-empty live-root seed list'
    assert 'harness/orchestrator.py' in LIVE_ROOTS
    assert 'harness/autowork_daemon.py' in LIVE_ROOTS

def test_repo_root_resolved_deterministically_from_module_file():
    """Repo root comes from the module __file__, is CWD-independent, and roots a
    real tree where all 7 ground-truth subject files exist."""
    assert REPO_ROOT == Path(harness.wire_up.__file__).resolve().parent.parent
    assert (REPO_ROOT / 'harness' / 'wire_up.py').is_file()
    for module_rel, _symbol in REACHABLE + ORPHANS:
        assert (REPO_ROOT / module_rel).is_file(), f'missing real source: {module_rel}'

def test_primitive_verdicts_deterministic_over_real_tree():
    """Pure & deterministic: repeated calls agree, and the partition is exactly
    the ground truth (all REACHABLE True, all ORPHANS False)."""
    for module_rel, symbol in REACHABLE + ORPHANS:
        first = symbol_reachable_from_live_root(REPO_ROOT, module_rel, symbol)
        again = symbol_reachable_from_live_root(REPO_ROOT, module_rel, symbol)
        assert first == again
    assert all((symbol_reachable_from_live_root(REPO_ROOT, m, s) is True for m, s in REACHABLE))
    assert all((symbol_reachable_from_live_root(REPO_ROOT, m, s) is False for m, s in ORPHANS))

def test_orphan_hosts_are_module_reachable_so_module_level_shortcut_would_fail():
    """Non-vacuity hinge: the orphan HOST modules are module-reachable, yet the
    orphan SYMBOLS are unreachable -- so a module-level shortcut would wrongly
    pass these. This is what proves the primitive is SYMBOL-level."""
    from harness.wire_up import check_wired
    for host in {module_rel for module_rel, _ in ORPHANS}:
        assert check_wired(REPO_ROOT, host).wired is True, f'{host} must be module-reachable for the symbol-vs-module hinge'
    for module_rel, symbol in ORPHANS:
        assert symbol_reachable_from_live_root(REPO_ROOT, module_rel, symbol) is False

def test_reachability_not_mocked_drives_real_resolved_graph_and_discover():
    """The verdicts are produced by the REAL function over the REAL tree: the
    graph/discovery helpers are genuine functions (not stubs) and the primitive
    DISCRIMINATES reachable from orphan, which a constant/mocked verdict could
    never do."""
    import inspect
    from harness.rebuild import discover as _discover
    assert inspect.isfunction(_discover.discover_modules)
    assert inspect.isfunction(harness.wire_up._resolved_graph)
    verdicts = {(m, s): symbol_reachable_from_live_root(REPO_ROOT, m, s) for m, s in REACHABLE + ORPHANS}
    assert {verdicts[k] for k in REACHABLE} == {True}
    assert {verdicts[k] for k in ORPHANS} == {False}