"""Mutation-killing tests for ``ngv2.gated_advance.advance_with_gates``.

These tests pin the *fail-closed gating contract*:

* ``advance`` runs exactly once iff all four required gates pass, and never
  otherwise (the explicit mutation-killing assertion: a mutant that always
  advances must fail ``advance.call_count == 0`` on a failing gate).
* ``run_gates`` is invoked with the four required gate identifiers and the
  ``build_evidence`` output.
* Exceptions raised by ``run_gates`` or ``build_evidence`` are converted into a
  fail-closed result dict with no ``advance`` call (errors are *not* swallowed
  into a success, and are *not* re-raised).

All collaborators are injected fakes/spies -- no real db or network is used.
The fakes deliberately do not hard-code the gate identifier strings: the
``run_gates`` spy captures whatever identifiers the implementation passes and
builds its result dict keyed by those exact identifiers, so the suite verifies
behaviour without coupling to the concrete gate names.
"""
from __future__ import annotations
import itertools
from typing import Any, Dict, List, Tuple
import pytest
from ngv2.gated_advance import advance_with_gates
SESSION_ID = 'sess-123'
ADVANCE_ERR = 'advance-boom-7f3'
RUN_GATES_ERR = 'run-gates-boom-9c1'
BUILD_EVIDENCE_ERR = 'build-evidence-boom-2d4'

class _Evidence:
    """Distinctive, non-collection sentinel returned by ``build_evidence``.

    Using a bespoke object (rather than a list/dict/str) means it can never be
    mistaken for the gate-id collection when inspecting ``run_gates`` call args.
    """

def _make_db() -> object:
    """Opaque sentinel standing in for the db handle (never touched for I/O)."""
    return object()
Call = Tuple[Tuple[Any, ...], Dict[str, Any]]

def _find_gate_ids(call: Call) -> List[str]:
    """Extract the gate-identifier collection from a ``run_gates`` call.

    Prefers a list/tuple/set of strings; falls back to dict string keys, then to
    bare positional string args. This keeps the spy agnostic to the exact call
    signature the implementation uses.
    """
    args, kwargs = call
    values = list(args) + list(kwargs.values())
    for v in values:
        if isinstance(v, (list, tuple, set, frozenset)):
            items = list(v)
            if items and all((isinstance(x, str) for x in items)):
                return items
    for v in values:
        if isinstance(v, dict) and v and all((isinstance(k, str) for k in v)):
            return list(v.keys())
    return [v for v in values if isinstance(v, str)]

def _evidence_passed(call: Call, sentinel: object) -> bool:
    args, kwargs = call
    values = list(args) + list(kwargs.values())
    return any((v is sentinel for v in values))

def _arg_seen(call: Call, value: object) -> bool:
    args, kwargs = call
    return value in args or value in kwargs.values()

class Spy:
    """Generic call-recording spy (used for ``advance``)."""

    def __init__(self, result: Any=None, raises: BaseException | None=None) -> None:
        self.calls: List[Call] = []
        self._result = result
        self._raises = raises

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append((args, kwargs))
        if self._raises is not None:
            raise self._raises
        return self._result

class FakeBuildEvidence:
    """Fixed-output fake; optionally raises to exercise the fail-closed path."""

    def __init__(self, evidence: object, raises: BaseException | None=None) -> None:
        self.calls: List[Call] = []
        self._evidence = evidence
        self._raises = raises

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def __call__(self, *args: Any, **kwargs: Any) -> object:
        self.calls.append((args, kwargs))
        if self._raises is not None:
            raise self._raises
        return self._evidence

class SpyRunGates:
    """Configurable fake keyed by the four gate ids the implementation supplies.

    The returned mapping uses the *actual* identifiers received, so the pass
    decision is driven by index/position rather than hard-coded gate names.
    """

    def __init__(self, *, fail_index: int | None=None, omit_index: int | None=None, extra_keys: bool=False, raises: BaseException | None=None, pass_mask: List[bool] | None=None) -> None:
        self.calls: List[Call] = []
        self.last_gate_ids: List[str] | None = None
        self._fail_index = fail_index
        self._omit_index = omit_index
        self._extra_keys = extra_keys
        self._raises = raises
        self._pass_mask = pass_mask

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def __call__(self, *args: Any, **kwargs: Any) -> Dict[str, bool]:
        self.calls.append((args, kwargs))
        if self._raises is not None:
            raise self._raises
        gate_ids = _find_gate_ids((args, kwargs))
        self.last_gate_ids = list(gate_ids)
        result: Dict[str, bool] = {}
        for i, gid in enumerate(gate_ids):
            if self._pass_mask is not None:
                passed = bool(self._pass_mask[i]) if i < len(self._pass_mask) else True
            elif self._fail_index is not None and i == self._fail_index:
                passed = False
            else:
                passed = True
            result[gid] = passed
        if self._omit_index is not None and gate_ids:
            idx = self._omit_index % len(gate_ids)
            result.pop(gate_ids[idx], None)
        if self._extra_keys:
            result['__totally_unknown_gate__'] = False
        return result

def _call(run_gates: Any, advance: Any, build_evidence: Any) -> Any:
    """Invoke the unit under test; fail loudly if it raises instead of fail-closing."""
    try:
        return advance_with_gates(SESSION_ID, _make_db(), run_gates, advance, build_evidence)
    except Exception as exc:
        pytest.fail(f'advance_with_gates must fail closed, not raise: {exc!r}')

def test_advance_called_once_all_pass() -> None:
    run_gates = SpyRunGates()
    advance = Spy(result={'state': 'next'})
    build_evidence = FakeBuildEvidence(_Evidence())
    result = _call(run_gates, advance, build_evidence)
    assert advance.call_count == 1
    assert isinstance(result, dict)
    assert _arg_seen(advance.calls[0], SESSION_ID)

@pytest.mark.parametrize('fail_index', [0, 1, 2, 3])
def test_advance_zero_calls_on_each_single_gate_failure(fail_index: int) -> None:
    run_gates = SpyRunGates(fail_index=fail_index)
    advance = Spy()
    build_evidence = FakeBuildEvidence(_Evidence())
    result = _call(run_gates, advance, build_evidence)
    assert advance.call_count == 0
    assert isinstance(result, dict)

def test_run_gates_receives_evidence_and_four_gate_ids() -> None:
    evidence = _Evidence()
    run_gates = SpyRunGates()
    advance = Spy()
    build_evidence = FakeBuildEvidence(evidence)
    _call(run_gates, advance, build_evidence)
    assert run_gates.call_count == 1
    gate_ids = run_gates.last_gate_ids
    assert gate_ids is not None
    assert len(set(gate_ids)) == 4
    assert build_evidence.call_count == 1
    assert _evidence_passed(run_gates.calls[0], evidence)

def test_run_gates_exception_fails_closed() -> None:
    run_gates = SpyRunGates(raises=RuntimeError(RUN_GATES_ERR))
    advance = Spy()
    build_evidence = FakeBuildEvidence(_Evidence())
    result = _call(run_gates, advance, build_evidence)
    assert advance.call_count == 0
    assert isinstance(result, dict)

def test_build_evidence_exception_fails_closed() -> None:
    run_gates = SpyRunGates()
    advance = Spy()
    build_evidence = FakeBuildEvidence(_Evidence(), raises=RuntimeError(BUILD_EVIDENCE_ERR))
    result = _call(run_gates, advance, build_evidence)
    assert run_gates.call_count == 0
    assert advance.call_count == 0
    assert isinstance(result, dict)

@pytest.mark.parametrize('omit_index', [0, 1, 2, 3])
def test_advance_zero_calls_on_missing_required_gate(omit_index: int) -> None:
    run_gates = SpyRunGates(omit_index=omit_index)
    advance = Spy()
    build_evidence = FakeBuildEvidence(_Evidence())
    _call(run_gates, advance, build_evidence)
    assert advance.call_count == 0

def test_extra_gate_keys_do_not_flip_pass() -> None:
    run_gates = SpyRunGates(extra_keys=True)
    advance = Spy()
    build_evidence = FakeBuildEvidence(_Evidence())
    _call(run_gates, advance, build_evidence)
    assert advance.call_count == 1

def test_pass_and_block_paths_with_fakes() -> None:
    evidence = _Evidence()
    advance_pass = Spy(result={'state': 'advanced'})
    pass_result = _call(SpyRunGates(), advance_pass, FakeBuildEvidence(evidence))
    assert advance_pass.call_count == 1
    assert isinstance(pass_result, dict)
    advance_block = Spy()
    block_result = _call(SpyRunGates(fail_index=1), advance_block, FakeBuildEvidence(evidence))
    assert advance_block.call_count == 0
    assert isinstance(block_result, dict)

@pytest.mark.parametrize('mask', list(itertools.product([True, False], repeat=4)))
def test_advance_count_equals_one_iff_all_gates_pass(mask: Tuple[bool, ...]) -> None:
    run_gates = SpyRunGates(pass_mask=list(mask))
    advance = Spy()
    build_evidence = FakeBuildEvidence(_Evidence())
    _call(run_gates, advance, build_evidence)
    expected = 1 if all(mask) else 0
    assert advance.call_count == expected

def test_advance_exception_surfaced_in_result() -> None:
    run_gates = SpyRunGates()
    advance = Spy(raises=RuntimeError(ADVANCE_ERR))
    build_evidence = FakeBuildEvidence(_Evidence())
    result = _call(run_gates, advance, build_evidence)
    assert advance.call_count == 1
    assert isinstance(result, dict)
    assert ADVANCE_ERR in repr(result)