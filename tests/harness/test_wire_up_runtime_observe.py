"""PHASE 1 RED oracle -- prove RUNTIME observation of a top-level symbol executed
FROM a LIVE_ROOT (and REJECT dead / static-reference / test-manufactured-caller
symbols).

This file is RED on HEAD: ``observe_symbol_execution`` and ``new_top_level_callables``
do not yet exist in ``harness.wire_up`` (they are added in TASK 2), so the top-level
``from harness.wire_up import ...`` raises ImportError and every test errors at
collection -- exactly the intended failing state for a test-first (RED) oracle.

Scope note: WIRING this runtime-reachability primitive into the accept chokepoint is
PHASE 2 *integration* work (brief_hooks_wire_up_runtime_reachability_gate.md). NO
integration test is authored or required here -- the literal word ``integration`` is
recorded to excuse that requirement. This oracle proves only the runtime-OBSERVATION
feasibility claim via ``sys.settrace`` (NOT any static call-graph / name-reference
reachability -- that static approach is explicitly rejected).

Hermetic / fully offline: no real ``state/``, no network, no process spawn. Every
spawn collaborator is mocked at its SOURCE module; the single watched PASS symbol
(``_save_final_output``) is left UNMOCKED so its real body executes and is observed
through a genuine production call edge. Expectations are derived from the synthetic
AST source and the observed execution -- no frozen literal / pasted impl.
"""
from __future__ import annotations
import sys
import threading
import pytest
from unittest.mock import patch
from harness.wire_up import LIVE_ROOTS, new_top_level_callables, observe_symbol_execution
import harness.orchestrator as orch
from harness.paths import _target_is_self

def never_reached_probe() -> str:
    """A top-level symbol nothing on the driven entrypoint calls."""
    return 'never_reached_probe-ran'

def dead_caller() -> str:
    """Body literally contains a ``never_reached_probe()`` call site, but
    ``dead_caller`` itself is never invoked on the driven entrypoint -- proving a
    STATIC reference is not RUNTIME execution."""
    return never_reached_probe()

def gamed_target() -> str:
    """Reached only via a test-module immediate caller (the anti-gaming probe)."""
    return 'gamed_target-ran'

def worker_only_symbol() -> str:
    """Reached exclusively on a worker thread (threading.settrace probe)."""
    return 'worker_only_symbol-ran'

def bare_probe() -> str:
    """Reached via a direct test call -- executed True, but NOT a wiring proof."""
    return 'bare_probe-ran'

def _await_calls_gamed(*_a, **_k) -> str:
    """``await_decision`` stand-in: the LIVE_ROOT (run_pipeline) calls THIS
    test-module frame, which then calls ``gamed_target`` -- so gamed_target's
    IMMEDIATE caller is a test frame while the live root sits only HIGHER on the
    stack. A loose any-frame-on-stack rule would wrongly accept it."""
    gamed_target()
    return 'accept'

def _non_live_root_caller(probe) -> None:
    """A non-live-root (test-module) immediate caller for a watched probe."""
    probe()

class _StopLoop(Exception):
    """Sentinel to break run_pipeline's ``while True`` after one task WITHOUT
    relying on StopIteration (which 3.13 re-wraps when it escapes a generator)."""

@pytest.fixture
def pipeline_config() -> dict:
    return {'synthesis': {'timeout_seconds': 30, 'max_ast_retries': 3, 'antigravity_mode': False, 'use_retry_module': False, 'active_agents': ['claude', 'gemini']}, 'fuzzing': {'float_tolerance': 1e-09, 'seed': 42}, 'sandbox': {'memory_limit_mb': 256, 'cpu_time_limit_seconds': 5, 'network': False}, 'decomposition': {'max_depth': 3, 'max_subtasks': 5}, 'agents': {'claude': {'command': 'claude', 'args': ['-p']}, 'gemini': {'command': 'gemini', 'args': ['-p']}}, 'agent_sandbox': {'bwrap': False}}

@pytest.fixture
def pipeline_state_dir(tmp_path):
    for sub in ('tasks', 'tasks/processed', 'sessions'):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    orch.init_state(tmp_path)
    return tmp_path

def _self_task() -> dict:
    return {'task_id': 'wire_up_runtime_observe_task', 'specification': 'drive one bypass iteration', 'constraints': {'deterministic': True}, 'meta_task_type': 'validation', 'verification_command': 'pytest tests/test_dummy.py', 'files_touched': [], 'dependencies': []}

def _drive_run_pipeline(config, state_dir, task, *, await_side_effect=None):
    """Drive exactly one bypass-branch iteration of run_pipeline spawn-free.

    Mirrors the patch-collaborators-at-source-module pattern from
    tests/adversarial/test_flag2_embedded_fuzz.py (_drive_run_pipeline). Every
    spawn collaborator is mocked at its source module; the watched PASS symbol
    (_save_final_output) is deliberately LEFT UNMOCKED so its real body runs.
    ``time.sleep`` raises _StopLoop to terminate the loop after the single task.
    """
    call_count = [0]

    def mock_get_next_task(_sd):
        call_count[0] += 1
        return task if call_count[0] == 1 else None
    if await_side_effect is None:

        def await_side_effect(*_a, **_k):
            return 'accept'
    with patch('harness.orchestrator.run_both_agents', return_value=('def f(): pass', 'def g(): pass')), patch('harness.orchestrator._validate_submission', return_value=(True, [])), patch('harness.orchestrator.get_next_task', side_effect=mock_get_next_task), patch('harness.orchestrator._auto_commit_accepted', return_value=True), patch('harness.orchestrator.smoke_import', return_value=None), patch('harness.orchestrator.run_embedded_tests', return_value=None), patch('harness.orchestrator.run_narrow_fuzz', return_value=None), patch('harness.orchestrator.control_gate.await_decision', side_effect=await_side_effect), patch('harness.orchestrator.time.sleep', side_effect=_StopLoop):
        try:
            orch.run_pipeline(config, state_dir)
        except _StopLoop:
            pass

def test_live_root_symbol_observed_executed_from_live_root_passes(pipeline_config, pipeline_state_dir):
    """A deep production symbol reached through a real production call edge from a
    registered LIVE_ROOT (run_pipeline @ harness/orchestrator.py) is observed AND
    its IMMEDIATE caller is verified to live in a LIVE_ROOT file. The symbol is left
    UNMOCKED, is NOT called directly, and is NOT wrapped-and-delegated."""
    assert _target_is_self(None) is True
    sym = '_save_final_output'
    with observe_symbol_execution([sym]) as obs:
        _drive_run_pipeline(pipeline_config, pipeline_state_dir, _self_task())
    assert obs.executed(sym) is True
    assert obs.executed_from_live_root(sym, LIVE_ROOTS) is True
    assert sym in obs.reached
    rf = obs.reached_from(sym)
    assert rf is not None and any((rf.endswith(r) for r in LIVE_ROOTS))

def test_gamed_target_via_test_caller_rejected_by_provenance(pipeline_config, pipeline_state_dir):
    """gamed_target is reached with a TEST-module frame as its IMMEDIATE caller
    while the live root sits only HIGHER on the stack: executed is True but
    executed_from_live_root is False -- the strict immediate-caller rule REJECTS
    what a loose any-frame-on-stack rule would have accepted."""
    with observe_symbol_execution(['gamed_target']) as obs:
        _drive_run_pipeline(pipeline_config, pipeline_state_dir, _self_task(), await_side_effect=_await_calls_gamed)
    assert obs.executed('gamed_target') is True
    assert obs.executed_from_live_root('gamed_target', LIVE_ROOTS) is False
    rf = obs.reached_from('gamed_target')
    assert rf is None or not any((rf.endswith(r) for r in LIVE_ROOTS))

def test_dead_symbol_observed_not_executed(pipeline_config, pipeline_state_dir):
    """On the SAME driven iteration the tracer DID observe a real production
    execution (_save_final_output), yet a top-level probe nothing called is
    correctly NOT observed -- so executed (and executed_from_live_root) are False."""
    with observe_symbol_execution(['_save_final_output', 'never_reached_probe']) as obs:
        _drive_run_pipeline(pipeline_config, pipeline_state_dir, _self_task())
    assert obs.executed('_save_final_output') is True
    assert obs.executed('never_reached_probe') is False
    assert obs.executed_from_live_root('never_reached_probe', LIVE_ROOTS) is False

def test_static_reference_in_dead_code_not_executed(pipeline_config, pipeline_state_dir):
    """dead_caller() literally contains a never_reached_probe() call site, but
    dead_caller is never invoked on the driven entrypoint -- EXECUTION is observed,
    not static reference."""
    assert 'never_reached_probe' in dead_caller.__code__.co_names
    with observe_symbol_execution(['_save_final_output', 'never_reached_probe']) as obs:
        _drive_run_pipeline(pipeline_config, pipeline_state_dir, _self_task())
    assert obs.executed('_save_final_output') is True
    assert obs.executed('never_reached_probe') is False

def test_enumerator_finds_new_callables_incl_if_try_with_nested():
    parent = 'import os\ndef already():\n    return 0\n'
    child = 'import os\ndef already():\n    return 0\ndef brand_new():\n    return 1\nasync def brand_new_async():\n    return 2\nlam = lambda x: x\ntry:\n    def from_try():\n        return 3\nexcept Exception:\n    pass\nif True:\n    def from_if():\n        return 4\nwith open(os.devnull) as _fh:\n    def from_with():\n        return 5\n'
    res = new_top_level_callables(parent, child)
    for name in ('brand_new', 'brand_new_async', 'lam', 'from_try', 'from_if', 'from_with'):
        assert name in res, f'{name!r} should be enumerated as new; got {res!r}'
    assert 'already' not in res
    nested = 'def outer():\n    def inner():\n        return 1\n    return inner\n'
    assert 'inner' not in new_top_level_callables(None, nested)

def test_enumerator_no_false_positive_on_preexisting_symbol():
    parent = 'def old_uncalled():\n    return 0\n'
    child = 'def old_uncalled():\n    return 0\ndef fresh_one():\n    return 1\n'
    res = new_top_level_callables(parent, child)
    assert 'old_uncalled' not in res
    assert 'fresh_one' in res

def test_enumerator_unparseable_child_returns_empty_sorted_list():
    res = new_top_level_callables('def a(): pass\n', 'def broken(:\n    pass\n')
    assert res == []
    assert isinstance(res, list)
    assert res == sorted(res)

def test_observer_clobbers_then_restores_exact_prior_tracer():

    def _prior(frame, event, arg):
        return _prior
    outer = sys.gettrace()
    sys.settrace(_prior)
    try:
        assert sys.gettrace() is _prior
        with observe_symbol_execution(['bare_probe']) as obs:
            assert sys.gettrace() is not _prior
            bare_probe()
        assert sys.gettrace() is _prior
        assert obs.executed('bare_probe') is True
    finally:
        sys.settrace(outer)

def test_oracle_runs_offline_and_is_deterministic():
    parent = 'def already(): pass\n'
    child = 'def already(): pass\ndef brand_new(): pass\n'
    r1 = new_top_level_callables(parent, child)
    r2 = new_top_level_callables(parent, child)
    assert r1 == r2
    assert 'brand_new' in r1 and 'already' not in r1
    seen = []
    for _ in range(2):
        with observe_symbol_execution(['bare_probe']) as obs:
            bare_probe()
        seen.append(obs.executed('bare_probe'))
    assert seen == [True, True]

def test_worker_thread_symbol_observed_threading_settrace():

    def _worker():
        worker_only_symbol()
    with observe_symbol_execution(['worker_only_symbol']) as obs:
        t = threading.Thread(target=_worker)
        t.start()
        t.join()
    assert obs.executed('worker_only_symbol') is True

def test_new_top_level_callables_result_is_sorted_and_unique():
    parent = 'x = 1\n'
    child = 'def zeta(): pass\ndef alpha(): pass\nmid = lambda y: y\ndef alpha(): pass\n'
    res = new_top_level_callables(parent, child)
    assert isinstance(res, list)
    assert res == sorted(res)
    assert len(res) == len(set(res))
    assert set(res) == {'alpha', 'mid', 'zeta'}
    assert 'solo' in new_top_level_callables(None, 'def solo(): pass\n')

def test_bare_executed_is_observation_only_not_a_wiring_proof():
    with observe_symbol_execution(['bare_probe']) as obs:
        bare_probe()
    assert obs.executed('bare_probe') is True
    assert obs.executed_from_live_root('bare_probe', LIVE_ROOTS) is False

def test_executed_from_live_root_false_when_immediate_caller_not_live_root():
    with observe_symbol_execution(['bare_probe']) as obs:
        _non_live_root_caller(bare_probe)
    assert obs.executed('bare_probe') is True
    rf = obs.reached_from('bare_probe')
    assert rf is not None
    assert not any((rf.endswith(r) for r in LIVE_ROOTS))
    assert obs.executed_from_live_root('bare_probe', LIVE_ROOTS) is False