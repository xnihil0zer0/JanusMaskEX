"""RED oracle — authoritative contract for autocompiler/js/js_sandbox.py (leaf ac-js-sandbox-seam).

Contract: the Python-side adapter that turns (code, inputs) into a
``js_runner.js`` batch invocation and decodes the FD-3 results into
``harness.sandbox.ExecutionResult`` rows — with the SPAWN INJECTED so this
oracle is fully hermetic (no node, no subprocess; at runtime the seam routes
through the bwrap agent jail, never the seccomp fuzz sandbox). Exposes:

``execute_js_batch(code, inputs, *, spawn_seam, node_bin, runner_path,
state_dir, timeout_ms=5000) -> list[ExecutionResult]``

- Writes the batch file (JSON: ``code`` str, ``inputs`` sentinel-ENCODED via
  ``js_codec.encode_value``, ``timeout_ms`` int) under ``state_dir``.
- Builds the spawn plan via ``js_fork_policy.fork_spec(node_bin, runner_path,
  <batch path>, timeout_ms=...)`` and calls ``spawn_seam(spec)`` — the seam
  returns the FD-3 text (a JSON object ``{"results": [...]}`` aligned with
  ``inputs``).
- Maps each entry to an ExecutionResult: success+value (sentinel-DECODED via
  ``js_codec.decode_value``) / ``timed_out`` / ``error`` => ``success=False``
  with the error string in ``exception_message``.
- TOTAL: a raising seam, garbage FD-3 text, or a short results array yields
  ``len(inputs)`` failure rows — it NEVER raises and NEVER truncates.
- The module itself never spawns: no ``subprocess`` reference in its source.
"""
import inspect
import json
import math

import pytest

import autocompiler.js.js_sandbox as sandbox_mod
from autocompiler.js.js_codec import UNDEFINED
from autocompiler.js.js_sandbox import execute_js_batch
from harness.sandbox import ExecutionResult

_NODE = '/nvm/versions/node/v22.17.0/bin/node'
_RUNNER = '/repo/autocompiler/js/js_runner.js'


def _seam_returning(payload):
    calls = []

    def seam(spec):
        calls.append(spec)
        return json.dumps(payload)
    seam.calls = calls
    return seam


def test_success_values_decoded(tmp_path):
    seam = _seam_returning({'results': [
        {'success': True, 'value': 3, 'error': None, 'timed_out': False},
        {'success': True, 'value': {'__sentinel__': 'NaN'}, 'error': None, 'timed_out': False},
        {'success': True, 'value': {'__sentinel__': 'undefined'}, 'error': None, 'timed_out': False},
    ]})
    out = execute_js_batch('module.exports = (a, b) => a + b;', [[1, 2], [3, 4], [5, 6]],
                           spawn_seam=seam, node_bin=_NODE, runner_path=_RUNNER,
                           state_dir=tmp_path)
    assert [type(r) for r in out] == [ExecutionResult] * 3
    assert out[0].success is True and out[0].return_value == 3
    assert math.isnan(out[1].return_value)
    assert out[2].return_value is UNDEFINED


def test_seam_receives_fork_spec_and_encoded_batch(tmp_path):
    seam = _seam_returning({'results': [
        {'success': True, 'value': None, 'error': None, 'timed_out': False}]})
    execute_js_batch('module.exports = () => null;', [[float('nan')]],
                     spawn_seam=seam, node_bin=_NODE, runner_path=_RUNNER,
                     state_dir=tmp_path, timeout_ms=1234)
    assert len(seam.calls) == 1
    spec = seam.calls[0]
    assert spec['argv'][0] == _NODE
    assert spec['argv'][1] == _RUNNER
    assert spec['result_fd'] == 3 and spec['timeout_ms'] == 1234
    with open(spec['argv'][2], 'r', encoding='utf-8') as fh:
        batch = json.load(fh)
    assert batch['code'] == 'module.exports = () => null;'
    assert batch['timeout_ms'] == 1234
    assert batch['inputs'] == [[{'__sentinel__': 'NaN'}]]  # sentinel-encoded, JSON-safe


def test_timeout_and_error_entries_mapped(tmp_path):
    seam = _seam_returning({'results': [
        {'success': False, 'value': None, 'error': None, 'timed_out': True},
        {'success': False, 'value': None, 'error': 'TypeError: boom', 'timed_out': False},
    ]})
    out = execute_js_batch('module.exports = () => 1;', [[1], [2]],
                           spawn_seam=seam, node_bin=_NODE, runner_path=_RUNNER,
                           state_dir=tmp_path)
    assert out[0].timed_out is True and out[0].success is False
    assert out[1].success is False and 'TypeError: boom' in (out[1].exception_message or '')


def test_raising_seam_yields_failures_not_raise(tmp_path):
    def seam(spec):
        raise RuntimeError('node exploded')
    out = execute_js_batch('module.exports = () => 1;', [[1], [2], [3]],
                           spawn_seam=seam, node_bin=_NODE, runner_path=_RUNNER,
                           state_dir=tmp_path)
    assert len(out) == 3
    assert all(r.success is False for r in out)
    assert all((r.exception_message or '') for r in out)


def test_garbage_fd3_yields_failures_not_raise(tmp_path):
    # Edge case: a polluted/empty results channel must degrade, not crash.
    for garbage in ('', 'not json', '{"results": "nope"}'):
        out = execute_js_batch('module.exports = () => 1;', [[1]],
                               spawn_seam=lambda spec, g=garbage: g,
                               node_bin=_NODE, runner_path=_RUNNER, state_dir=tmp_path)
        assert len(out) == 1 and out[0].success is False


def test_short_results_padded_to_input_count(tmp_path):
    # Edge case: a runner that died mid-batch reports fewer rows; the adapter
    # pads the tail with failures so callers can still zip(results, inputs).
    seam = _seam_returning({'results': [
        {'success': True, 'value': 1, 'error': None, 'timed_out': False}]})
    out = execute_js_batch('module.exports = () => 1;', [[1], [2], [3]],
                           spawn_seam=seam, node_bin=_NODE, runner_path=_RUNNER,
                           state_dir=tmp_path)
    assert len(out) == 3
    assert out[0].success is True
    assert out[1].success is False and out[2].success is False


def test_module_never_spawns():
    src = inspect.getsource(sandbox_mod)
    for forbidden in ('subprocess', 'Popen', 'os.fork', 'os.exec'):
        assert forbidden not in src, f'js_sandbox must not reference {forbidden}'
