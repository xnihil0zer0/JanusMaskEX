"""RED oracle — authoritative contract for the ac-wire-evolution leaf
(harness/diff_fuzzer.py::fuzz_from_task population-memory hook).

Contract: a NEW module-level helper ``_record_population_safe(code_a, code_b,
task, result, state_dir=None) -> None`` in ``harness/diff_fuzzer.py``, invoked
once at the END of ``fuzz_from_task`` on its final result (cross-attempt
MEMORY at the seam where near-misses are born — every fuzz round, including
cross-examination re-fuzzes, flows through here). It NEVER overrides the
verifier: it always returns None and the caller's accept/reject flow is
untouched. (The call site is deliberately NOT ``orchestrator_worker.main`` —
symbol-patching ``main`` is the documented AST-truncation hazard.) Behavior:

- Resolves the flag AT CALL TIME via ``from autocompiler.flags import
  ac_enabled`` inside the body (the bridge precedent). OFF (the live default)
  => returns None and touches NOTHING, even when the autocompiler package is
  broken.
- Records ONLY a usable near-miss: ``result.equivalent`` falsy AND
  ``result.error`` falsy AND the task carries a non-empty str ``task_id``.
  Equivalent/error results return None without touching disk.
- ON: seeds/extends ``autocompiler.population.PopulationDB`` under
  ``<state_dir>/autocompiler/<task_id>`` with BOTH candidates (ids
  ``agent_a``/``agent_b``, ``code`` = the sources, non-empty ``fitness``
  dict), runs ONE ``autocompiler.loop.step(db, seams)`` transition over
  injected neutral seams, persists via ``db.save()``.
- ``state_dir=None`` resolves the repo-standard ``<repo_root>/state``.
- TOTAL: any internal error (raising step, unwritable dir) is swallowed.
"""
import inspect
from types import SimpleNamespace

import pytest

import harness.diff_fuzzer as fuzzer_mod
from harness.diff_fuzzer import _record_population_safe, fuzz_from_task

_NEAR_MISS = SimpleNamespace(equivalent=False, error=None, failures=[SimpleNamespace(
    input_args=[1], input_kwargs={}, result_a=None, result_b=None, reason='diverged')])


def _task(tid='tevo'):
    return {'task_id': tid, 'constraints': {}}


def test_helper_wired_into_fuzz_from_task_tail():
    src = inspect.getsource(fuzz_from_task)
    assert '_record_population_safe(' in src, \
        'fuzz_from_task must record its final result into the population memory'
    assert hasattr(fuzzer_mod, '_record_population_safe')


def test_flag_off_touches_nothing(tmp_path, monkeypatch):
    # Live default config: population flag OFF. Even a broken loop.step must
    # never be reached.
    import autocompiler.loop as loop_mod

    def _boom(*a, **k):
        raise RuntimeError('step must not run when OFF')
    monkeypatch.setattr(loop_mod, 'step', _boom)
    out = _record_population_safe('def a(): pass', 'def b(): pass',
                                  _task('tevo-off'), _NEAR_MISS, state_dir=tmp_path)
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

    out = _record_population_safe('def a():\n    return 1\n', 'def b():\n    return 2\n',
                                  _task('tevo-on'), _NEAR_MISS, state_dir=tmp_path)
    assert out is None
    assert len(calls) == 1

    from autocompiler.population import PopulationDB
    db = PopulationDB.load(tmp_path / 'autocompiler' / 'tevo-on')
    by_id = {c.id: c for c in db.candidates()}
    assert {'agent_a', 'agent_b'}.issubset(by_id)
    assert by_id['agent_a'].code == 'def a():\n    return 1\n'
    assert by_id['agent_b'].code == 'def b():\n    return 2\n'
    assert isinstance(by_id['agent_a'].fitness, dict) and by_id['agent_a'].fitness


def test_equivalent_or_error_results_not_recorded(tmp_path, monkeypatch):
    # Edge case: only a usable near-miss becomes memory.
    import autocompiler.flags as flags_mod
    monkeypatch.setattr(flags_mod, 'ac_enabled', lambda key, *a, **k: True)
    ok = SimpleNamespace(equivalent=True, error=None, failures=[])
    err = SimpleNamespace(equivalent=False, error='strategy failed', failures=[])
    _record_population_safe('a', 'b', _task('tevo-eq'), ok, state_dir=tmp_path)
    _record_population_safe('a', 'b', _task('tevo-err'), err, state_dir=tmp_path)
    _record_population_safe('a', 'b', {'no_task_id': True}, _NEAR_MISS, state_dir=tmp_path)
    assert not (tmp_path / 'autocompiler').exists()


def test_always_none_and_total(tmp_path, monkeypatch):
    # Edge cases: raising step / raising flag reader are swallowed.
    import autocompiler.flags as flags_mod
    import autocompiler.loop as loop_mod
    monkeypatch.setattr(flags_mod, 'ac_enabled', lambda key, *a, **k: True)

    def _boom(*a, **k):
        raise RuntimeError('step exploded')
    monkeypatch.setattr(loop_mod, 'step', _boom)
    assert _record_population_safe('a', 'b', _task('tevo-boom'), _NEAR_MISS,
                                   state_dir=tmp_path) is None

    def _boom_flag(*a, **k):
        raise RuntimeError('flag exploded')
    monkeypatch.setattr(flags_mod, 'ac_enabled', _boom_flag)
    assert _record_population_safe('a', 'b', _task('tevo-boom2'), _NEAR_MISS,
                                   state_dir=tmp_path) is None
