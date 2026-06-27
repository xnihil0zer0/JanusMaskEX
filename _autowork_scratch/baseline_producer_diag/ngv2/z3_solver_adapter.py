"""Optional real-z3 ``SolverFn`` factory for the ``Z3Bridge`` injection seam.

This leaf module is the real-z3 side of the injected solver seam exposed by
``ngv2.z3_bridge`` as ``Z3Bridge(solver_fn=...)``. Its single public function
:func:`make_z3_solver` returns ``None`` when the ``z3`` package is absent (the
import is guarded *in-body*, never at module scope, so importing this module
never requires z3), letting the system degrade to the stdlib rule fallback.

When z3 is importable, :func:`make_z3_solver` returns a stateless-per-call
``SolverFn`` closure that translates the two committed constraint sets
('grounding', 'gate') into z3 ``Bool``/``Implies`` assertions whose verdicts
differentially match the stdlib rule fallback on every reachable state:

    'grounding': (codeql_found OR joern_found) -> confidence >= HIGH
    'gate':      (submitting AND live_test_required) -> live_test_passed

The rank table and the typing alias are imported from ``ngv2.z3_bridge`` and
are never redeclared here.
"""
from typing import Mapping, Optional
from ngv2.z3_bridge import _CONFIDENCE_RANK, SolverFn

def make_z3_solver() -> Optional[SolverFn]:
    """Build a real-z3 ``SolverFn``, or ``None`` when z3 is unavailable.

    The ``import z3`` is performed here, inside the body, wrapped in a
    ``try/except ImportError`` so the import is re-attempted on every call and
    no module-level result is cached. When z3 is blocked (e.g. by a
    ``sys.meta_path`` finder) this returns ``None`` deterministically.
    """
    try:
        import z3
    except ImportError:
        return None

    def _solver(constraint_set: str, state: Mapping[str, object]) -> bool:
        cs = str(constraint_set).lower()
        if cs == 'grounding':
            codeql = z3.BoolVal(bool(state.get('codeql_found', False)))
            joern = z3.BoolVal(bool(state.get('joern_found', False)))
            rank = _CONFIDENCE_RANK.get(str(state.get('confidence', 'LOW')).upper(), 0)
            conf_ge_high = z3.BoolVal(rank >= _CONFIDENCE_RANK['HIGH'])
            s = z3.Solver()
            s.add(z3.Implies(z3.Or(codeql, joern), conf_ge_high))
            return s.check() == z3.sat
        if cs == 'gate':
            submitting = z3.BoolVal(bool(state.get('submitting', False)))
            required = z3.BoolVal(bool(state.get('live_test_required', True)))
            passed = z3.BoolVal(bool(state.get('live_test_passed', False)))
            s = z3.Solver()
            s.add(z3.Implies(z3.And(submitting, required), passed))
            return s.check() == z3.sat
        return True
    return _solver