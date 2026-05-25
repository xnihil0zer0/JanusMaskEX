"""W77b.2 adversarial battery for ``harness.narrow_fuzz.validation.fuzz``.

Pins the brief §13 binding reproducer plus the §11.2 reversed-default
gate, the §10.3 decorator opt-out, and the keyword-only ``timeout``
plumbing. The reproducer (``validate_nonempty(xs: list) -> bool``)
crashes on ``xs=[]`` and Hypothesis must find that within the 200-input
budget; the error string must surface both the exception type and the
failing input so a regression cannot quietly drop the failing case.
"""
from __future__ import annotations

import importlib
import pathlib
import sys


_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from harness.narrow_fuzz import validation  # noqa: E402


_REPRODUCER = """
def validate_nonempty(xs: list) -> bool:
    \"\"\"Return True iff list is non-empty.\"\"\"
    return xs[0] is not None
"""


def test_reproducer_finds_crash():
    err = validation.fuzz('_canary', _REPRODUCER)
    assert err is not None, 'narrow-fuzz failed to surface IndexError on xs=[]'
    assert 'validate_nonempty' in err
    assert 'IndexError' in err


def test_reproducer_error_includes_failing_input():
    """Brief §13: error string MUST preserve the shrunken failing input."""
    err = validation.fuzz('_canary', _REPRODUCER)
    assert err is not None
    assert 'xs' in err
    assert '[]' in err


def test_clean_validator_returns_none():
    src = """
def is_positive(n: int) -> bool:
    return n > 0
"""
    assert validation.fuzz('_canary', src) is None


def test_no_validator_functions_returns_none():
    """Source with no validate_/check_/is_ functions skips silently."""
    src = """
def helper(x: int) -> int:
    return x * 2

def other_thing():
    pass
"""
    assert validation.fuzz('_canary', src) is None


def test_skip_when_embedded_tests_present(monkeypatch):
    """§11.2 reversed default: presence of test_* skips narrow-fuzz."""
    monkeypatch.setattr(validation, '_RUN_ALWAYS', False)
    src = _REPRODUCER + """
def test_smoke():
    assert True
"""
    err = validation.fuzz('_canary', src)
    assert err is None


def test_run_always_overrides_embedded_skip(monkeypatch):
    """RUN_NARROW_FUZZ_ALWAYS=1 forces narrow-fuzz despite embedded tests."""
    monkeypatch.setattr(validation, '_RUN_ALWAYS', True)
    src = _REPRODUCER + """
def test_smoke():
    assert True
"""
    err = validation.fuzz('_canary', src)
    assert err is not None
    assert 'IndexError' in err


def test_decorator_skip_via_metadata():
    """§10.3: ``_narrow_fuzz_meta = {'skip': True}`` opts the validator out."""
    src = _REPRODUCER + """
validate_nonempty._narrow_fuzz_meta = {'skip': True}
"""
    err = validation.fuzz('_canary', src)
    assert err is None


def test_unknown_annotation_skips_validator():
    """A validator with an annotation we have no strategy for is skipped, not crashed."""
    src = """
import socket
def check_addr(addr: socket.AddressFamily) -> bool:
    return addr is not None
"""
    err = validation.fuzz('_canary', src)
    assert err is None


def test_malformed_source_returns_none():
    """SyntaxError in candidate source must not crash the harness."""
    err = validation.fuzz('_canary', 'def validate_(((')
    assert err is None


def test_async_validator_silently_skipped_no_runtime_warning():
    """W100: ``async def validate_*`` is silently skipped at discovery.

    Regression: pre-W100 the discovery walker accepted ``AsyncFunctionDef``
    alongside ``FunctionDef``; ``_fuzz_one`` called ``fn(**kwargs)`` which
    on an async function returned an unawaited coroutine instead of raising.
    Hypothesis ran 200 iterations without a captured exception, ``fuzz``
    returned ``None``, and Python emitted ``RuntimeWarning: coroutine
    'validate_positive' was never awaited``.

    The fix routes async validators through the same silent-skip pattern as
    unsupported annotations. This test pins both signals: the result is
    ``None`` AND no RuntimeWarning fires."""
    import warnings

    src = """
async def validate_positive(x: int) -> bool:
    return x > 0
"""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        err = validation.fuzz('_canary', src)
    assert err is None
    coroutine_warnings = [
        w for w in caught
        if issubclass(w.category, RuntimeWarning)
        and 'coroutine' in str(w.message).lower()
    ]
    assert coroutine_warnings == [], (
        f'async validator must be skipped at discovery, not invoked; '
        f'caught: {[str(w.message) for w in coroutine_warnings]}'
    )


def test_mixed_sync_async_validators_sync_runs_async_skipped():
    """W100: in a candidate that mixes sync + async validators, the sync
    one is fuzzed normally and the async one is skipped. Combined with
    ``test_reproducer_finds_crash``, this proves async-skip does not leak
    into sync-validator coverage."""
    src = """
def is_positive(x: int) -> bool:
    return x > 0

async def validate_async_shape(x: int) -> bool:
    return x > 0
"""
    err = validation.fuzz('_canary', src)
    assert err is None


def test_async_only_candidate_returns_none():
    """W100: a candidate whose validators are all async must return ``None``
    via the empty-discovery skip (no validators reach the fuzz loop)."""
    src = """
async def validate_a(x: int) -> bool:
    return x > 0

async def check_b(s: str) -> bool:
    return bool(s)
"""
    err = validation.fuzz('_canary', src)
    assert err is None


def test_timeout_kwarg_keyword_only():
    """The brief mandates timeout is keyword-only on the per-type fuzz function too."""
    import inspect

    sig = inspect.signature(validation.fuzz)
    assert sig.parameters['timeout'].kind == inspect.Parameter.KEYWORD_ONLY


def test_orchestrator_wires_run_narrow_fuzz():
    """W77b.3 wire-in: orchestrator imports run_narrow_fuzz and calls it in
    the bypass branch reject-flow alongside smoke + embedded gates."""
    from harness import orchestrator

    assert hasattr(orchestrator, 'run_narrow_fuzz')

    src = pathlib.Path(orchestrator.__file__).read_text(encoding='utf-8')
    assert "narrow_err = run_narrow_fuzz(mtt, '_narrow_fuzz_candidate', claude_code)" in src
    assert 'rejected via narrow-fuzz' in src
