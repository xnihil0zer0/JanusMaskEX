"""RED behavioral oracle for ``observe_symbol_execution.executed_with_live_root_ancestor``.

Pins the stack-ancestor truth table of a NEW query method
``executed_with_live_root_ancestor(name, live_root_files) -> bool`` on the
EXISTING ``observe_symbol_execution`` observer in ``harness/wire_up.py``.

This module authors NO production edit. It is RED on HEAD: every behavioral
case errors with ``AttributeError`` because ``executed_with_live_root_ancestor``
does not yet exist on the observer (it is added in TASK 2). The oracle imports
the REAL observer and the REAL ``LIVE_ROOTS`` constant directly (mirroring the
sibling oracle ``test_wire_up_runtime_observe.py``), never mocks/stubs the
observer, never hardcodes the live-root list, and drives the observer over real
``'call'`` events using hermetically-synthesized frames.

Frame synthesis (fully offline, side-effect free):

  * Live-root frames: tiny Python source written to a temp file whose basename
    is a LIVE_ROOTS basename (e.g. ``orchestrator.py``), loaded via
    ``importlib.util.spec_from_file_location`` + ``module_from_spec`` +
    ``spec.loader.exec_module`` and then called, so the executed frame's
    ``co_filename`` basename is the live-root basename (``_path_matches`` resolves
    a LIVE_ROOTS seed against such a frame by basename). ``exec``/``eval``/
    ``__import__`` are deliberately avoided (importlib spec-loading is the
    sanctioned path).
  * Non-live-root frames: plain top-level test-module functions (``mid``).

Cases C and E are the non-vacuity hinges: a flat ``live-root-seen-anywhere``
implementation silently passes A/B/D and an ``all-watched-names`` ancestry scan
silently passes A/B/C/D, so C and E are what force the per-name f_back-lineage
semantics.
"""
from __future__ import annotations
import importlib.util
import itertools
import os
from harness.wire_up import LIVE_ROOTS, observe_symbol_execution
_LIVE_ROOT_SOURCE = "def root(callback=None):\n    if callback is not None:\n        return callback()\n    return 'root-ran'\n"
_counter = itertools.count()

def _live_root_seed() -> str:
    """Return a REAL LIVE_ROOTS seed (rel-path) to synthesize a frame for.

    Derived from the imported ``LIVE_ROOTS`` (never hardcoded); prefers the
    ``orchestrator.py`` seed the feasibility probe used, else the first seed.
    """
    for seed in LIVE_ROOTS:
        if os.path.basename(seed) == 'orchestrator.py':
            return seed
    return LIVE_ROOTS[0]

def _load_live_root_callable(tmp_path):
    """Hermetically synthesize a live-root callable.

    Writes ``_LIVE_ROOT_SOURCE`` to a temp file whose basename is a LIVE_ROOTS
    basename, loads it via importlib spec-loading, and returns ``module.root``
    whose ``__code__.co_filename`` basename is that live-root basename.
    """
    seed = _live_root_seed()
    basename = os.path.basename(seed)
    n = next(_counter)
    sub = tmp_path / ('lr_%d' % n)
    sub.mkdir()
    src_file = sub / basename
    src_file.write_text(_LIVE_ROOT_SOURCE)
    spec = importlib.util.spec_from_file_location('hermetic_live_root_%d' % n, str(src_file))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.root

def tgt():
    """The watched target symbol (module-top-level, co_qualname == co_name)."""
    return 'tgt-ran'

def peer():
    """A second watched symbol used for the multi-name isolation case."""
    return 'peer-ran'

def mid():
    """A NON-live-root intermediate frame that invokes the watched target."""
    return tgt()

def test_case_a_deep_live_root_ancestor_true_and_immediate_caller_false(tmp_path):
    root = _load_live_root_callable(tmp_path)
    with observe_symbol_execution(['tgt']) as obs:
        root(mid)
    assert obs.executed('tgt') is True
    assert obs.executed_from_live_root('tgt', LIVE_ROOTS) is False
    assert obs.executed_with_live_root_ancestor('tgt', LIVE_ROOTS) is True

def test_case_b_direct_test_call_no_ancestor_false():
    with observe_symbol_execution(['tgt']) as obs:
        tgt()
    assert obs.executed('tgt') is True
    assert obs.executed_with_live_root_ancestor('tgt', LIVE_ROOTS) is False

def test_case_c_gaming_trap_live_root_returned_then_orphan_false(tmp_path):
    root = _load_live_root_callable(tmp_path)
    with observe_symbol_execution(['tgt']) as obs:
        root()
        mid()
    assert obs.executed('tgt') is True
    assert obs.executed_with_live_root_ancestor('tgt', LIVE_ROOTS) is False

def test_case_d_immediate_live_root_caller_true(tmp_path):
    root = _load_live_root_callable(tmp_path)
    with observe_symbol_execution(['tgt']) as obs:
        root(tgt)
    assert obs.executed('tgt') is True
    assert obs.executed_with_live_root_ancestor('tgt', LIVE_ROOTS) is True
    assert obs.executed_from_live_root('tgt', LIVE_ROOTS) is True

def test_case_e_multi_name_isolation_per_name_lookup_no_cross_name_leak(tmp_path):
    root = _load_live_root_callable(tmp_path)
    with observe_symbol_execution(['tgt', 'peer']) as obs:
        root(peer)
        mid()
    assert obs.executed('tgt') is True
    assert obs.executed('peer') is True
    assert obs.executed_with_live_root_ancestor('peer', LIVE_ROOTS) is True
    assert obs.executed_with_live_root_ancestor('tgt', LIVE_ROOTS) is False

def test_imports_real_observer_and_live_roots_without_mock_or_hardcode():
    import inspect
    import harness.wire_up as wu
    assert observe_symbol_execution is wu.observe_symbol_execution
    assert inspect.isclass(observe_symbol_execution)
    assert observe_symbol_execution.__module__ == 'harness.wire_up'
    assert 'mock' not in type(observe_symbol_execution).__module__.lower()
    assert LIVE_ROOTS is wu.LIVE_ROOTS
    assert isinstance(LIVE_ROOTS, list) and len(LIVE_ROOTS) > 0
    assert all((isinstance(s, str) and s.endswith('.py') for s in LIVE_ROOTS))
    assert any((os.path.basename(s) == 'orchestrator.py' for s in LIVE_ROOTS))

def test_hermetic_live_root_frame_basename_resolves_via_path_matches(tmp_path):
    seed = _live_root_seed()
    base = os.path.basename(seed)
    assert observe_symbol_execution._path_matches('/tmp/anything/' + base, seed) is True
    root = _load_live_root_callable(tmp_path)
    co_filename = root.__code__.co_filename
    assert os.path.basename(co_filename) == base
    assert observe_symbol_execution._path_matches(co_filename, seed) is True
    assert observe_symbol_execution._path_matches('/tmp/anything/not_a_root.py', seed) is False

def test_unwatched_or_never_executed_name_returns_false(tmp_path):
    root = _load_live_root_callable(tmp_path)
    with observe_symbol_execution(['tgt']) as obs:
        root(tgt)
    assert obs.executed_with_live_root_ancestor('not_watched', LIVE_ROOTS) is False
    with observe_symbol_execution(['never']) as obs2:
        pass
    assert obs2.executed_with_live_root_ancestor('never', LIVE_ROOTS) is False

def test_stack_ancestor_strictly_covers_immediate_caller_a_vs_d_contrast(tmp_path):
    root_a = _load_live_root_callable(tmp_path)
    with observe_symbol_execution(['tgt']) as obs_a:
        root_a(mid)
    a_ancestor = obs_a.executed_with_live_root_ancestor('tgt', LIVE_ROOTS)
    a_immediate = obs_a.executed_from_live_root('tgt', LIVE_ROOTS)
    root_d = _load_live_root_callable(tmp_path)
    with observe_symbol_execution(['tgt']) as obs_d:
        root_d(tgt)
    d_ancestor = obs_d.executed_with_live_root_ancestor('tgt', LIVE_ROOTS)
    d_immediate = obs_d.executed_from_live_root('tgt', LIVE_ROOTS)
    assert a_ancestor is True and a_immediate is False
    assert d_ancestor is True and d_immediate is True

def test_executed_from_live_root_depth1_view_unchanged(tmp_path):
    root = _load_live_root_callable(tmp_path)
    with observe_symbol_execution(['tgt']) as obs:
        root(tgt)
    assert obs.executed('tgt') is True
    assert obs.executed_from_live_root('tgt', LIVE_ROOTS) is True
    with observe_symbol_execution(['tgt']) as obs2:
        tgt()
    assert obs2.executed_from_live_root('tgt', LIVE_ROOTS) is False
    assert obs.executed_with_live_root_ancestor('tgt', LIVE_ROOTS) is True

def test_existing_executed_and_reached_observation_only_unchanged():
    with observe_symbol_execution(['tgt']) as obs:
        tgt()
    assert obs.executed('tgt') is True
    assert 'tgt' in obs.reached
    assert obs.executed('unwatched') is False
    caller = obs.reached_from('tgt')
    assert caller is not None
    assert os.path.basename(caller) == os.path.basename(__file__)
    assert obs.executed_with_live_root_ancestor('tgt', LIVE_ROOTS) is False

def test_verdict_deterministic_across_two_fresh_observers(tmp_path):
    verdicts = []
    for _ in range(2):
        root = _load_live_root_callable(tmp_path)
        with observe_symbol_execution(['tgt']) as obs:
            root(mid)
        verdicts.append(obs.executed_with_live_root_ancestor('tgt', LIVE_ROOTS))
    assert verdicts[0] is True
    assert verdicts[0] == verdicts[1]