"""Deterministic runner-adapter factories for the NGv2 DetonationChamber.

This module defines the canonical runner-result contract and two factory
functions that produce injectable runner callables for tests. The real
subprocess/bwrap runner is intentionally out of scope here; it is injected at
NGv2 runtime. Each runner has the shape ``runner(poc, target_spec) -> tuple``
and returns a 4-tuple matching :data:`RUNNER_RESULT_FIELDS`.
"""
from typing import Callable, Dict, Tuple
from ngv2.contracts import PoC
__all__ = ('RUNNER_RESULT_FIELDS', 'make_mock_runner', 'make_scripted_runner')
RUNNER_RESULT_FIELDS: Tuple[str, str, str, str] = ('exit_code', 'stdout', 'stderr', 'duration_ms')

def make_mock_runner(exit_code: int=0, stdout: str='', stderr: str='', duration_ms: int=0) -> Callable[[PoC, object], Tuple[int, str, str, int]]:
    """Return a runner that ignores its arguments and yields a fixed tuple.

    The returned ``runner(poc, target_spec)`` closes over the four supplied
    values and returns ``(exit_code, stdout, stderr, duration_ms)`` unchanged
    on every call, making it fully deterministic.
    """
    result: Tuple[int, str, str, int] = (exit_code, stdout, stderr, duration_ms)

    def runner(poc: PoC, target_spec: object) -> Tuple[int, str, str, int]:
        return result
    return runner

def make_scripted_runner(script: Dict[object, tuple]) -> Callable[[PoC, object], tuple]:
    """Return a runner that looks up ``poc.finding_id`` in ``script``.

    A mapped ``finding_id`` yields its stored 4-tuple verbatim; an unmapped
    ``finding_id`` yields the deterministic default ``(None, '', '', 0)``
    without raising.
    """

    def runner(poc: PoC, target_spec: object) -> tuple:
        return script.get(poc.finding_id, (None, '', '', 0))
    return runner