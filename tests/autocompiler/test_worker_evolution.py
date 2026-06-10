"""RED oracle — authoritative contract for the ac-wire-evolution leaf
(harness/orchestrator_worker.py post-fuzz region).

Contract: a NEW module-level helper ``_maybe_run_evolution(state_dir, task_id,
fuzz_result, agent_a_code, agent_b_code) -> None`` in
``harness/orchestrator_worker.py`` plus a single additive call on the
NON-equivalent fuzz path inside ``main`` (cross-attempt MEMORY — the
population records the near-miss; it never overrides the verifier, so the
single-shot accept/reject behavior stays byte-identical). Behavior:

- Resolves the flag AT CALL TIME via ``from autocompiler.flags import
  ac_enabled`` inside the body. OFF (the live default) => returns None and
  touches NOTHING (no dir created), even when the autocompiler package is
  broken.
- ON (``ac_enabled('population')``): seeds/extends a
  ``autocompiler.population.PopulationDB`` under
  ``<state_dir>/autocompiler/<task_id>`` with BOTH candidates (ids
  ``agent_a`` / ``agent_b``, ``code`` = the agent sources, non-empty
  ``fitness`` dict derived from the fuzz outcome), runs ONE
  ``autocompiler.loop.step(db, seams)`` transition over injected neutral
  seams, persists via ``db.save()``, and returns None.
- ALWAYS returns None (Phase C records memory; it never emits a winner).
- TOTAL: any internal error (raising step, unwritable state_dir) is swallowed.
"""
import inspect
import re
from types import SimpleNamespace

import pytest

import harness.orchestrator_worker as worker_mod
from harness.orchestrator_worker import _maybe_run_evolution

_FUZZ_NEAR_MISS = SimpleNamespace(equivalent=False, error=None, failures=[SimpleNamespace(
    input_repr='(1,)', output_a='1', output_b='2', exception_a=None, exception_b=None)])


def test_helper_wired_into_main_nonequivalent_path():
    module_src = inspect.getsource(worker_mod)
    # def + at least one call site
    assert len(re.findall(r'_maybe_run_evolution\(', module_src)) >= 2
    main_src = inspect.getsource(worker_mod.main)
    assert '_maybe_run_evolution(' in main_src


def test_flag_off_touches_nothing(tmp_path, monkeypatch):
    # Live default config: population flag OFF. Even a broken loop.step must
    # never be reached.
    import autocompiler.loop as loop_mod

    def _boom(*a, **k):
        raise RuntimeError('step must not run when OFF')
    monkeypatch.setattr(loop_mod, 'step', _boom)
    out = _maybe_run_evolution(tmp_path, 'tevo-off', _FUZZ_NEAR_MISS, 'def a(): pass', 'def b(): pass')
    assert out is None
    assert not (tmp_path / 'autocompiler').exists()


def test_flag_on_seeds_population_and_steps(tmp_path, monkeypatch):
    import autocompiler.flags as flags_mod
    import autocompiler.loop as loop_mod
    monkeypatch.setattr(flags_mod, 'ac_enabled', lambda key, *a, **k: key == 'population')
    calls = []
    real_step = loop_mod.step

    def spy_step(db, seams):
        calls.append((db, seams))
        return real_step(db, seams)
    monkeypatch.setattr(loop_mod, 'step', spy_step)

    out = _maybe_run_evolution(tmp_path, 'tevo-on', _FUZZ_NEAR_MISS,
                               'def a():\n    return 1\n', 'def b():\n    return 2\n')
    assert out is None
    assert len(calls) == 1

    from autocompiler.population import PopulationDB
    db = PopulationDB.load(tmp_path / 'autocompiler' / 'tevo-on')
    ids = {c.id for c in db.candidates()}
    assert {'agent_a', 'agent_b'}.issubset(ids)
    by_id = {c.id: c for c in db.candidates()}
    assert by_id['agent_a'].code == 'def a():\n    return 1\n'
    assert by_id['agent_b'].code == 'def b():\n    return 2\n'
    assert isinstance(by_id['agent_a'].fitness, dict) and by_id['agent_a'].fitness


def test_always_returns_none_and_total(tmp_path, monkeypatch):
    # Edge cases: ON with a raising step => swallowed; result is still None.
    import autocompiler.flags as flags_mod
    import autocompiler.loop as loop_mod
    monkeypatch.setattr(flags_mod, 'ac_enabled', lambda key, *a, **k: True)

    def _boom(*a, **k):
        raise RuntimeError('step exploded')
    monkeypatch.setattr(loop_mod, 'step', _boom)
    assert _maybe_run_evolution(tmp_path, 'tevo-boom', _FUZZ_NEAR_MISS, 'a', 'b') is None

    def _boom_flag(*a, **k):
        raise RuntimeError('flag exploded')
    monkeypatch.setattr(flags_mod, 'ac_enabled', _boom_flag)
    assert _maybe_run_evolution(tmp_path, 'tevo-boom2', _FUZZ_NEAR_MISS, 'a', 'b') is None
