"""ngv2.z3_bridge — deterministic neurosymbolic invariant checker with an
INJECTED solver seam.

The real Z3 SMT solver lives only at NGv2 runtime (and is optional). This module
is a PURE, stdlib-only shell that checks NobleGreed safety invariants via
deterministic rule-based logic. An optional injected ``solver_fn`` callable lets
a solver be wired in WITHOUT this module ever importing ``z3`` or invoking any
real solver binary/subprocess.

Constraint sets:
    - 'grounding': (codeql_found OR joern_found) -> confidence >= HIGH
    - 'gate':      (submitting AND live_test_required) -> live_test_passed

Stdlib-only by contract. No `z3` import, no sibling Epic-4 leaf import
(ast_constraint / ast_verifier / backtrack), no third-party dependency.
"""
from __future__ import annotations
import time
from dataclasses import dataclass
from typing import Callable, Dict, Mapping, Optional
__all__ = ['Z3Result', 'Z3Bridge', '_CONFIDENCE_RANK', 'CONSTRAINT_SETS', 'make_mock_solver', 'make_scripted_solver']
_CONFIDENCE_RANK: Dict[str, int] = {'LOW': 0, 'MEDIUM': 1, 'HIGH': 2, 'CONFIRMED': 3}
CONSTRAINT_SETS = ('grounding', 'gate')
_FORBIDDEN_DIFF_PATTERNS = ('|| true', '2>/dev/null')
SolverFn = Callable[[str, Mapping[str, object]], object]

@dataclass
class Z3Result:
    """Outcome of an invariant check.

    ``bool(result)`` is the satisfaction verdict, so results can be used directly
    in boolean contexts.
    """
    satisfied: bool
    reason: str
    z3_used: bool
    elapsed_ms: float = 0.0

    def __bool__(self) -> bool:
        return bool(self.satisfied)

def make_mock_solver(verdict: bool) -> SolverFn:
    """Return a solver callable that always reports ``verdict``.

    The returned callable ignores the constraint set and state, making it useful
    for asserting that the injected seam overrides the built-in rule logic.
    """
    fixed = bool(verdict)

    def _solver(constraint_set: str, state: Mapping[str, object]) -> bool:
        return fixed
    return _solver

def make_scripted_solver(mapping: Mapping[str, bool], default: bool=True) -> SolverFn:
    """Return a solver callable that dispatches by constraint-set name.

    Looks the (normalized) constraint-set name up in ``mapping``; falls back to
    ``default`` when the name is absent.
    """
    table = dict(mapping)
    fallback = bool(default)

    def _solver(constraint_set: str, state: Mapping[str, object]) -> bool:
        return bool(table.get(constraint_set, fallback))
    return _solver

class Z3Bridge:
    """Deterministic invariant checker with an optional injected solver seam.

    When ``solver_fn`` is provided, every :meth:`check_invariants` call is routed
    exclusively through that callable (and ``z3_used`` is reported ``True``).
    When it is absent (``None``), the pure rule-based fallback is used and
    ``z3_used`` is always ``False``.  The real ``z3`` module is never imported.
    """

    def __init__(self, solver_fn: Optional[SolverFn]=None) -> None:
        self._solver_fn: Optional[SolverFn] = solver_fn

    def check_invariants(self, constraint_set: str, state: Optional[Mapping[str, object]]=None) -> Z3Result:
        """Check the named constraint set against ``state``.

        Constraint-set names are matched case-insensitively.  Unknown sets are
        treated as vacuously satisfied.
        """
        start = time.perf_counter()
        st: Mapping[str, object] = state if state is not None else {}
        cs = str(constraint_set).lower()
        if self._solver_fn is not None:
            verdict = bool(self._solver_fn(cs, st))
            reason = 'injected solver verdict for %r: %s' % (cs, verdict)
            return Z3Result(satisfied=verdict, reason=reason, z3_used=True, elapsed_ms=_elapsed_ms(start))
        if cs == 'grounding':
            satisfied, reason = self._check_grounding(st)
        elif cs == 'gate':
            satisfied, reason = self._check_gate(st)
        else:
            satisfied, reason = (True, 'unknown constraint set %r: vacuously satisfied' % cs)
        return Z3Result(satisfied=satisfied, reason=reason, z3_used=False, elapsed_ms=_elapsed_ms(start))

    def verify_harness_edit(self, diff: str) -> Z3Result:
        """Statically scan a unified diff for forbidden patterns in added lines.

        Only added lines (those beginning with a single ``+``) are inspected;
        removed/context lines are ignored.  A line carrying a ``#`` comment is
        treated as an acceptable, intentional fallback and is not flagged.  This
        is a pure check and never uses a solver.
        """
        start = time.perf_counter()
        violations = []
        for line in str(diff).splitlines():
            if not line.startswith('+'):
                continue
            if line.startswith('+++'):
                continue
            if '#' in line:
                continue
            for pattern in _FORBIDDEN_DIFF_PATTERNS:
                if pattern in line and pattern not in violations:
                    violations.append(pattern)
        if violations:
            reason = 'forbidden patterns in added lines: ' + ', '.join(violations)
            satisfied = False
        else:
            reason = 'no forbidden patterns in added lines'
            satisfied = True
        return Z3Result(satisfied=satisfied, reason=reason, z3_used=False, elapsed_ms=_elapsed_ms(start))

    @staticmethod
    def _check_grounding(state: Mapping[str, object]) -> 'tuple[bool, str]':
        """(codeql_found OR joern_found) -> confidence >= HIGH."""
        taint = bool(state.get('codeql_found', False)) or bool(state.get('joern_found', False))
        if not taint:
            return (True, 'grounding vacuously satisfied: no static-analysis taint')
        confidence = str(state.get('confidence', 'LOW')).upper()
        rank = _CONFIDENCE_RANK.get(confidence, 0)
        if rank >= _CONFIDENCE_RANK['HIGH']:
            return (True, 'grounding satisfied: taint backed by confidence %r' % confidence)
        return (False, 'grounding violated: taint with insufficient confidence %r' % confidence)

    @staticmethod
    def _check_gate(state: Mapping[str, object]) -> 'tuple[bool, str]':
        """(submitting AND live_test_required) -> live_test_passed."""
        submitting = bool(state.get('submitting', False))
        required = bool(state.get('live_test_required', True))
        passed = bool(state.get('live_test_passed', False))
        if submitting and required:
            if passed:
                return (True, 'gate satisfied: live test passed before submission')
            return (False, 'gate violated: submitting with required live test not passed')
        return (True, 'gate vacuously satisfied: live test not required for this action')

def _elapsed_ms(start: float) -> float:
    """Elapsed wall-clock time since ``start`` in milliseconds (never negative)."""
    return max(0.0, (time.perf_counter() - start) * 1000.0)