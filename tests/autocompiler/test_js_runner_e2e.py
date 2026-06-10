"""RED oracle — authoritative contract for autocompiler/js/js_runner.js (leaf ac-js-runner).

Contract (the ONLY real Node I/O in the beachhead): ``node js_runner.js
<batch.json>`` where the batch file is JSON:

    {"code": "<CommonJS source whose module.exports is the target function>",
     "inputs": [[...args], ...],
     "timeout_ms": <int per-input budget>}

The runner evaluates ``code`` as a CommonJS module, calls
``module.exports(...args)`` for each input IN ORDER (awaiting Promises via
``await`` + ``Promise.race`` against the timeout), and writes ONE JSON
document to **FD 3** (never stdout — stdout belongs to candidate noise):

    {"results": [{"success": bool,
                  "value": <sentinel-encoded: undefined/NaN/±Infinity as
                            {"__sentinel__": tag}>,
                  "error": str | null,
                  "timed_out": bool}, ...]}

aligned 1:1 with ``inputs``. A never-resolving Promise must surface as
``timed_out: true`` within the budget — the runner exits, it does not hang.
The runner forks the evaluation into a child process per batch
(``child_process.fork``) so a wedged candidate can be killed wholesale.

This oracle drives the REAL node binary (host-side; runtime confinement is the
bwrap agent jail, see Phase D). Skips only when node is unavailable.
"""
import json
import math
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_RUNNER = _REPO / 'autocompiler' / 'js' / 'js_runner.js'
_NODE = shutil.which('node')

pytestmark = pytest.mark.skipif(_NODE is None, reason='node binary unavailable')


def _run_batch(tmp_path, code, inputs, timeout_ms=2000, wall_timeout=30):
    assert _RUNNER.is_file(), f'{_RUNNER} does not exist'
    batch = tmp_path / 'batch.json'
    batch.write_text(json.dumps(
        {'code': code, 'inputs': inputs, 'timeout_ms': timeout_ms}), encoding='utf-8')
    fd3_out = tmp_path / 'fd3.json'
    proc = subprocess.run(
        ['bash', '-c', 'exec 3>"$1"; exec "$2" "$3" "$4"', '_',
         str(fd3_out), _NODE, str(_RUNNER), str(batch)],
        capture_output=True, text=True, timeout=wall_timeout)
    fd3_text = fd3_out.read_text(encoding='utf-8')
    doc = json.loads(fd3_text)
    assert isinstance(doc.get('results'), list)
    return doc['results'], proc, fd3_text


def test_simple_function_values_in_order(tmp_path):
    results, _, _ = _run_batch(tmp_path, 'module.exports = (a, b) => a + b;',
                               [[1, 2], [5, 7]])
    assert len(results) == 2
    assert results[0]['success'] is True and results[0]['value'] == 3
    assert results[1]['success'] is True and results[1]['value'] == 12
    assert results[0]['timed_out'] is False


def test_async_function_is_awaited(tmp_path):
    results, _, _ = _run_batch(
        tmp_path,
        'module.exports = async (a) => { return a * 2; };',
        [[21]])
    assert results[0]['success'] is True and results[0]['value'] == 42


def test_stdout_pollution_does_not_corrupt_results(tmp_path):
    # Regression: candidate console.log noise must never reach FD 3.
    results, proc, fd3_text = _run_batch(
        tmp_path,
        'module.exports = (a) => { console.log("JUNK-NOISE-" + a); return a; };',
        [[7]])
    assert results[0]['value'] == 7
    assert 'JUNK-NOISE' not in fd3_text


def test_never_resolving_promise_times_out_not_hangs(tmp_path):
    # Edge case: the runner must exit within the budget, not wedge the worker.
    t0 = time.monotonic()
    results, _, _ = _run_batch(
        tmp_path,
        'module.exports = () => new Promise(() => {});',
        [[]], timeout_ms=1000, wall_timeout=25)
    assert time.monotonic() - t0 < 20
    assert results[0]['timed_out'] is True
    assert results[0]['success'] is False


def test_undefined_and_nan_sentinel_encoded(tmp_path):
    results, _, _ = _run_batch(
        tmp_path,
        'module.exports = (k) => k === 1 ? undefined : (k === 2 ? NaN : Infinity);',
        [[1], [2], [3]])
    assert results[0]['value'] == {'__sentinel__': 'undefined'}
    assert results[1]['value'] == {'__sentinel__': 'NaN'}
    assert results[2]['value'] == {'__sentinel__': 'Infinity'}


def test_throwing_function_reports_error(tmp_path):
    # Edge case: a throw is a per-input failure, not a batch abort.
    results, _, _ = _run_batch(
        tmp_path,
        'module.exports = (a) => { if (a === 0) { throw new TypeError("boom"); } return a; };',
        [[0], [9]])
    assert results[0]['success'] is False
    assert 'boom' in (results[0]['error'] or '')
    assert results[0]['timed_out'] is False
    assert results[1]['success'] is True and results[1]['value'] == 9


def test_runner_forks_a_child_for_evaluation():
    # Structural pin: per-batch child_process.fork is the kill-wholesale seam.
    src = _RUNNER.read_text(encoding='utf-8')
    assert 'fork' in src, 'runner must fork the evaluation child'
    assert 'Promise.race' in src, 'runner must race evaluation against the timeout'
