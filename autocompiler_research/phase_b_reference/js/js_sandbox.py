"""Python adapter from (code, inputs) to a js_runner batch (Phase B, ac-js-sandbox-seam).

The SPAWN IS INJECTED: ``spawn_seam(spec) -> str`` receives the
``js_fork_policy.fork_spec`` plan and returns the FD-3 text. This module never
spawns anything itself — at runtime the seam routes through the bwrap agent
jail (never the seccomp fuzz sandbox, which blocks execve/fork by design).
Results decode into ``harness.sandbox.ExecutionResult`` rows, total over any
seam misbehavior.
"""
from __future__ import annotations

import json
import os
from typing import Any, Callable

from autocompiler.js.js_codec import decode_value, encode_value
from autocompiler.js.js_fork_policy import fork_spec
from harness.sandbox import ExecutionResult


def _failure(message: str, timed_out: bool=False) -> ExecutionResult:
    return ExecutionResult(success=False, return_value=None, return_repr='',
                           exception_type=None, exception_message=message,
                           timed_out=timed_out)


def _decode_entry(entry: Any) -> ExecutionResult:
    if not isinstance(entry, dict):
        return _failure(f'malformed result entry: {entry!r}')
    if entry.get('timed_out'):
        return _failure(str(entry.get('error') or 'per-input timeout'), timed_out=True)
    if entry.get('success'):
        value = decode_value(entry.get('value'))
        return ExecutionResult(success=True, return_value=value,
                               return_repr=repr(value))
    return _failure(str(entry.get('error') or 'candidate failed'))


def execute_js_batch(code: str, inputs: list, *, spawn_seam: Callable[[dict], str],
                     node_bin: str, runner_path: str, state_dir,
                     timeout_ms: int=5000) -> list[ExecutionResult]:
    """Run one JS candidate batch through the injected spawn seam.

    Writes the sentinel-encoded batch file under *state_dir*, builds the
    ``fork_spec`` plan, hands it to ``spawn_seam`` and decodes the returned
    FD-3 text. TOTAL: a raising seam / garbage FD-3 / short results array
    yields ``len(inputs)`` rows — never an exception, never truncation.
    """
    n = len(inputs)
    try:
        state = os.fspath(state_dir)
        os.makedirs(state, exist_ok=True)
        batch_path = os.path.join(state, 'js_batch.json')
        with open(batch_path, 'w', encoding='utf-8') as fh:
            json.dump({'code': code, 'inputs': encode_value(list(inputs)),
                       'timeout_ms': timeout_ms}, fh, allow_nan=False)
        spec = fork_spec(node_bin, runner_path, batch_path, timeout_ms=timeout_ms)
        fd3_text = spawn_seam(spec)
        doc = json.loads(fd3_text)
        entries = doc.get('results')
        if not isinstance(entries, list):
            raise ValueError('FD-3 document has no results list')
        out = [_decode_entry(e) for e in entries[:n]]
    except Exception as exc:
        return [_failure(f'js batch execution failed: {exc}') for _ in range(n)]
    while len(out) < n:
        out.append(_failure('runner produced fewer results than inputs'))
    return out
