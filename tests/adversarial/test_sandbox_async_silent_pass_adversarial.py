"""W101 adversarial battery for the sandbox async silent-pass gate.

Pre-W101 bug (round-2 audit-E1): both `harness.sandbox._RUNNER_TEMPLATE`
(used by `Sandbox.execute`) and `_BATCH_RUNNER_TEMPLATE` (used by
`BatchRunner` and `BatchWorkerPool`) called the resolved submission
function synchronously via `func(*args, **kwargs)`. For an `async def`
submission this returned an unawaited coroutine instead of raising —
``repr(coro)`` succeeded, ``json.dumps(coro)`` raised TypeError and the
inner handler silently set ``return_value=None``, and the result was
recorded as ``success=True``. When two submissions both defined the same
async function the differential fuzzer compared (None, None) and declared
them equivalent; the gate was bypassed without ever executing.

Fix: detect async functions at the same seam as the existing
``func is None`` guard, and reject with ``success=False`` +
``TypeError`` ("async function ... not supported in differential fuzz
sandbox"). Pattern mirrors W100's narrow-fuzz async-skip but at the
sandbox layer where the differential gate enforces equivalence.

These tests pin the runner-template structure (both templates carry the
guard, in canonical order: import → resolution → async-detect →
invocation) and the end-to-end behavior of ``Sandbox.execute`` on an
async submission.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from harness import sandbox  # noqa: E402
from harness.sandbox import (  # noqa: E402
    Sandbox,
    SandboxConfig,
    _BATCH_RUNNER_TEMPLATE,
    _RUNNER_TEMPLATE,
)


# ---------------------------------------------------------------------------
# (i) Both runner templates import inspect AND carry the async guard.
# ---------------------------------------------------------------------------

def test_runner_template_imports_inspect() -> None:
    """``import inspect`` lands at the top of the template alongside json/os/etc.
    Without it the iscoroutinefunction call below would NameError."""
    assert 'import inspect' in _RUNNER_TEMPLATE


def test_batch_runner_template_imports_inspect() -> None:
    assert 'import inspect' in _BATCH_RUNNER_TEMPLATE


def test_runner_template_carries_async_guard() -> None:
    """``_RUNNER_TEMPLATE`` covers two invocation paths (``main_single`` +
    ``main_pool``); the guard must appear in BOTH, so dropping either site
    re-opens the silent-pass."""
    assert _RUNNER_TEMPLATE.count('inspect.iscoroutinefunction') == 2
    assert _RUNNER_TEMPLATE.count(
        "async function '{func_name}' not supported in differential fuzz sandbox"
    ) == 2


def test_batch_runner_template_carries_async_guard() -> None:
    """``_BATCH_RUNNER_TEMPLATE`` covers two invocation paths (``main_single``
    multi-input + ``main_pool`` per-fork); the guard must appear in both,
    or one path silently re-opens the bug."""
    assert _BATCH_RUNNER_TEMPLATE.count('inspect.iscoroutinefunction') == 2
    assert _BATCH_RUNNER_TEMPLATE.count(
        "async function '{func_name}' not supported in differential fuzz sandbox"
    ) == 2


# ---------------------------------------------------------------------------
# (ii) Guard ordering: detection sits AFTER resolution and BEFORE invocation.
# Out-of-order guards either NameError on the missing func or fire after the
# silent-pass, both of which re-open the bug.
# ---------------------------------------------------------------------------

def test_runner_template_main_single_guard_ordering() -> None:
    """Inside the main_single block of _RUNNER_TEMPLATE, the iscoroutine
    check sits between ``func = namespace.get(func_name)`` and the
    ``ret = func(*call_args, **call_kwargs)`` invocation."""
    main_single_segment = _RUNNER_TEMPLATE.split('def main_pool')[0]
    resolve = main_single_segment.index("func = namespace.get(func_name)")
    guard = main_single_segment.index('inspect.iscoroutinefunction(func)')
    invoke = main_single_segment.index('ret = func(*call_args, **call_kwargs)')
    assert resolve < guard < invoke, (
        'main_single async guard must sit between func resolution and '
        'invocation; reordering re-opens the silent-pass'
    )


def _all_indexes(s: str, sub: str) -> list[int]:
    out, i = [], 0
    while True:
        j = s.find(sub, i)
        if j < 0:
            return out
        out.append(j)
        i = j + 1


def test_batch_runner_template_guard_ordering() -> None:
    """Both paths in ``_BATCH_RUNNER_TEMPLATE`` (main_single and main_pool)
    share the same resolve→guard→invoke order. Verify each pair
    independently so a partial revert (guard kept in only one path) trips
    the gate."""
    resolves = _all_indexes(_BATCH_RUNNER_TEMPLATE, "func = namespace.get(func_name)")
    guards = _all_indexes(_BATCH_RUNNER_TEMPLATE, 'inspect.iscoroutinefunction(func)')
    invokes = _all_indexes(_BATCH_RUNNER_TEMPLATE, 'ret = func(*call_args, **call_kwargs)')
    assert len(resolves) == len(guards) == len(invokes) == 2
    for r, g, v in zip(resolves, guards, invokes):
        assert r < g < v, (
            f'batch-template async guard out of order in one path: '
            f'resolve={r} guard={g} invoke={v}'
        )


# ---------------------------------------------------------------------------
# (iii) End-to-end: Sandbox.execute on an async submission must reject with
# success=False, exception_type=TypeError, and 'async' in the message.
# ---------------------------------------------------------------------------

def test_sandbox_execute_rejects_async_function() -> None:
    """The full e2e path: write runner template to disk, spawn subprocess,
    parse result. Async submission must NOT silently succeed with None.

    Pre-fix this test would fail with ``result.success is True`` and
    ``result.return_value is None`` — the exact silent-pass shape that
    breaks differential equivalence."""
    code = "async def solve(x: int) -> int:\n    return x + 1\n"
    sb = Sandbox(config=SandboxConfig(timeout_per_input_ms=2000), session_id='w101_async')
    try:
        result = sb.execute(code, 'solve', args=[1])
    finally:
        sb.cleanup()

    assert result.success is False, (
        f'async submission must be rejected, got success=True with '
        f'return_value={result.return_value!r}'
    )
    assert result.exception_type == 'TypeError'
    assert 'async' in (result.exception_message or '').lower()
    assert 'solve' in (result.exception_message or '')


def test_sandbox_execute_sync_function_still_passes() -> None:
    """Negative control: a clean sync function must still execute and
    return its value. The async guard must not regress sync invocation."""
    code = "def solve(x: int) -> int:\n    return x + 1\n"
    sb = Sandbox(config=SandboxConfig(timeout_per_input_ms=2000), session_id='w101_sync')
    try:
        result = sb.execute(code, 'solve', args=[41])
    finally:
        sb.cleanup()

    assert result.success is True
    assert result.return_value == 42


# ---------------------------------------------------------------------------
# W104: async-generator silent-pass extension. The W101 guard used
# ``inspect.iscoroutinefunction`` only, which is False for ``async def
# foo(): yield ...`` (async-generator function). Calling such a func
# returns an async_generator object — repr() succeeds, json.dumps() raises
# TypeError, return_value is silently dropped to None, success=True. Two
# distinct async-gen submissions then match-as-equivalent in
# diff_fuzzer.outputs_match via _deep_compare(None, None) = (True,
# both_none). The W104 fix extends each of the 4 W101 guard sites to also
# call ``inspect.isasyncgenfunction`` so async generators are rejected at
# the same gate.
# ---------------------------------------------------------------------------

def test_runner_template_carries_async_gen_guard() -> None:
    """Both invocation paths in ``_RUNNER_TEMPLATE`` must invoke
    ``isasyncgenfunction`` alongside ``iscoroutinefunction``; dropping
    either one re-opens the W104 silent-pass for async generators."""
    assert _RUNNER_TEMPLATE.count('inspect.isasyncgenfunction') == 2


def test_batch_runner_template_carries_async_gen_guard() -> None:
    assert _BATCH_RUNNER_TEMPLATE.count('inspect.isasyncgenfunction') == 2


def test_runner_template_async_gen_guard_inline_or_pattern() -> None:
    """Tighter regression guard: pin the literal ``or``-connective so a
    partial revert that splits the two checks into separate ``if``
    statements (or replaces ``or`` with a stale-fallback) trips the test.
    Both invocation paths share the same connective shape."""
    assert _RUNNER_TEMPLATE.count(
        'inspect.iscoroutinefunction(func) or inspect.isasyncgenfunction(func)'
    ) == 2


def test_batch_runner_template_async_gen_guard_inline_or_pattern() -> None:
    assert _BATCH_RUNNER_TEMPLATE.count(
        'inspect.iscoroutinefunction(func) or inspect.isasyncgenfunction(func)'
    ) == 2


def test_sandbox_execute_rejects_async_generator_function() -> None:
    """The full e2e path on an async-generator submission. Pre-W104 this
    test would fail with ``result.success is True`` and
    ``result.return_value is None`` — exactly the silent-pass shape that
    breaks differential equivalence via ``_deep_compare(None, None)``."""
    code = "async def gen(x: int):\n    yield x * 2\n"
    sb = Sandbox(config=SandboxConfig(timeout_per_input_ms=2000), session_id='w104_asyncgen')
    try:
        result = sb.execute(code, 'gen', args=[7])
    finally:
        sb.cleanup()

    assert result.success is False, (
        f'async-generator submission must be rejected, got success=True with '
        f'return_value={result.return_value!r}'
    )
    assert result.exception_type == 'TypeError'
    assert 'async' in (result.exception_message or '').lower()
    assert 'gen' in (result.exception_message or '')
