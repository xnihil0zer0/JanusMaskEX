"""RED oracle — authoritative contract for the ac-wire-js-dispatch leaf
(harness/diff_fuzzer.py::fuzz_from_task JS language dispatch).

Contract: a NEW module-level helper ``_maybe_js_fuzz(code_a, code_b, task,
config, session_id) -> FuzzResult | None`` in ``harness/diff_fuzzer.py`` plus
a guard at the TOP of ``fuzz_from_task`` (return the helper's result when it
is not None; otherwise the existing Python path runs byte-identically).
Behavior:

- Returns None unless ``ac_enabled('js')`` (resolved AT CALL TIME via
  ``from autocompiler.flags import ac_enabled`` inside the body — the bridge
  precedent) AND ``task.get('language') == 'js'``. The flag check NEVER
  raises; an import failure means None (Python path).
- Active: explicit input vectors come from ``task['constraints']['js_inputs']``
  (a list of arg-lists — JS has no type-driven strategy synthesis yet).
  Missing/empty/non-list => ``FuzzResult(equivalent=False, error=...)`` with
  ``'js_inputs'`` in the error.
- Both candidates run through ``autocompiler.js.js_sandbox.execute_js_batch``
  (the runner at ``autocompiler/js/js_runner.js``, node resolved from
  ``$JANUSMASK_NODE_BIN`` or ``shutil.which('node')``; node unavailable =>
  ``FuzzResult(equivalent=False, error=...)`` mentioning ``node``). Inputs are
  compared per-vector with ``js_codec.values_equal`` + matching
  success/timed_out flags: all match => ``equivalent=True``; any divergence
  => ``equivalent=False`` with >=1 ``FuzzFailure`` (its ``input_args`` is the
  vector, ``reason`` non-empty).
"""
import inspect
import json
import shutil

import pytest

import harness.diff_fuzzer as fuzzer_mod
from harness.diff_fuzzer import FuzzResult, fuzz_from_task

_NODE = shutil.which('node')


def _js_task(inputs):
    return {'task_id': 'tjs', 'language': 'js',
            'constraints': {'js_inputs': inputs}}


def test_dispatch_is_wired_into_fuzz_from_task():
    src = inspect.getsource(fuzz_from_task)
    assert '_maybe_js_fuzz(' in src
    assert hasattr(fuzzer_mod, '_maybe_js_fuzz')


def test_flag_off_never_takes_js_path(monkeypatch):
    # Live default config: js flag OFF — the seam must not be touched even for
    # a language=js task; the Python path runs as today.
    import autocompiler.js.js_sandbox as js_sandbox_mod
    calls = []
    monkeypatch.setattr(js_sandbox_mod, 'execute_js_batch',
                        lambda *a, **k: calls.append(1))
    assert fuzzer_mod._maybe_js_fuzz('x', 'y', _js_task([[1]]), {}, 's') is None
    result = fuzz_from_task('module.exports = a => a;', 'module.exports = a => a;',
                            _js_task([[1]]), {})
    assert isinstance(result, FuzzResult)
    assert calls == []


def test_python_tasks_unaffected(monkeypatch):
    # Regression: a plain Python task fuzzes exactly as before even with the
    # flag forced ON (language gate, not flag alone).
    import autocompiler.flags as flags_mod
    monkeypatch.setattr(flags_mod, 'ac_enabled', lambda key, *a, **k: True)
    code = 'def f(x: int) -> int:\n    return x + 1\n'
    result = fuzz_from_task(code, code, {'task_id': 'tpy', 'constraints': {}},
                            {'fuzzing': {'function_level_inputs': 25}})
    assert isinstance(result, FuzzResult)
    assert result.equivalent is True


@pytest.mark.skipif(_NODE is None, reason='node binary unavailable')
def test_flag_on_equivalent_js_candidates(monkeypatch):
    import autocompiler.flags as flags_mod
    monkeypatch.setattr(flags_mod, 'ac_enabled', lambda key, *a, **k: key == 'js')
    result = fuzz_from_task('module.exports = (a, b) => a + b;',
                            'module.exports = (a, b) => b + a;',
                            _js_task([[1, 2], [5, 7], [0, 0]]), {})
    assert result.error is None, result.error
    assert result.equivalent is True


@pytest.mark.skipif(_NODE is None, reason='node binary unavailable')
def test_flag_on_divergent_js_candidates(monkeypatch):
    import autocompiler.flags as flags_mod
    monkeypatch.setattr(flags_mod, 'ac_enabled', lambda key, *a, **k: key == 'js')
    result = fuzz_from_task('module.exports = (a, b) => a + b;',
                            'module.exports = (a, b) => a - b;',
                            _js_task([[1, 2], [3, 4]]), {})
    assert result.equivalent is False
    assert len(result.failures) >= 1
    failure = result.failures[0]
    assert failure.input_args and failure.reason


def test_flag_on_missing_inputs_fails_closed(monkeypatch):
    import autocompiler.flags as flags_mod
    monkeypatch.setattr(flags_mod, 'ac_enabled', lambda key, *a, **k: key == 'js')
    for bad in ({'task_id': 't', 'language': 'js'},
                _js_task([]), _js_task('nope')):
        result = fuzzer_mod._maybe_js_fuzz('x', 'y', bad, {}, 's')
        assert isinstance(result, FuzzResult)
        assert result.equivalent is False
        assert 'js_inputs' in (result.error or '')
