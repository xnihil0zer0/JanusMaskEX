"""Python-side adapter from (code, inputs) to a ``js_runner.js`` batch run.

This module turns a ``(code, inputs)`` pair into a single ``js_runner.js``
batch invocation and decodes the FD-3 results document into
``harness.sandbox.ExecutionResult`` rows aligned with ``inputs``. The spawn is
INJECTED via ``spawn_seam`` so this adapter never spawns anything itself: at
runtime the seam routes through the bwrap agent jail (NEVER the seccomp fuzz
sandbox), and in tests it is a fake returning canned FD-3 text.

The adapter is TOTAL: a raising seam, garbage/empty FD-3 text, or a results
list shorter than ``inputs`` yields exactly ``len(inputs)`` failure rows -- it
never raises and never truncates.
"""
from __future__ import annotations
import json
import os
from typing import Any, Callable
from autocompiler.js.js_codec import decode_value, encode_value
from autocompiler.js.js_fork_policy import fork_spec
from harness.sandbox import ExecutionResult

def _failure(message: str, timed_out: bool=False) -> ExecutionResult:
    """Build a uniform failure row."""
    return ExecutionResult(success=False, return_value=None, return_repr='', exception_type=None, exception_message=message, timed_out=timed_out)

def _decode_entry(entry: Any) -> ExecutionResult:
    """Map a single runner result entry to an ExecutionResult."""
    if not isinstance(entry, dict):
        return _failure('malformed runner result entry')
    if entry.get('timed_out'):
        return _failure('execution timed out', timed_out=True)
    if entry.get('success'):
        value = decode_value(entry.get('value'))
        return ExecutionResult(success=True, return_value=value, return_repr=repr(value))
    error = entry.get('error')
    return _failure(str(error) if error is not None else 'execution error')

def execute_js_batch(code: str, inputs: list, *, spawn_seam: Callable[[dict], str], node_bin: str, runner_path: str, state_dir, timeout_ms: int=5000) -> list[ExecutionResult]:
    """Run ``code`` over ``inputs`` via an injected spawn seam.

    Writes the sentinel-encoded batch file under ``state_dir``, builds the
    fork plan via :func:`fork_spec`, hands it to ``spawn_seam`` for the FD-3
    text, and decodes ``{"results": [...]}`` into one ExecutionResult per
    input. Never raises; always returns exactly ``len(inputs)`` rows.
    """
    n = len(inputs)
    try:
        base = os.fspath(state_dir)
        os.makedirs(base, exist_ok=True)
        batch_path = os.path.join(base, 'js_batch.json')
        batch = {'code': code, 'inputs': encode_value(list(inputs)), 'timeout_ms': timeout_ms}
        with open(batch_path, 'w', encoding='utf-8') as fh:
            json.dump(batch, fh, allow_nan=False)
        spec = fork_spec(node_bin, runner_path, batch_path, timeout_ms=timeout_ms)
        fd3_text = spawn_seam(spec)
        document = json.loads(fd3_text)
        entries = document['results']
        if not isinstance(entries, list):
            raise ValueError('runner document missing results list')
        out = [_decode_entry(entry) for entry in entries[:n]]
    except Exception as exc:
        return [_failure(f'js batch failed: {exc!s}') for _ in range(n)]
    while len(out) < n:
        out.append(_failure('runner produced fewer results than inputs'))
    return out