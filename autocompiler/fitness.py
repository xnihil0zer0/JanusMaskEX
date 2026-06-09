"""Pure, deterministic, JSON-safe fitness-vector contract.

This module folds the *already produced* empirical-fuzzer signal
(``harness/diff_fuzzer.py`` ``FuzzResult`` / ``FuzzFailure``) together with the
anti-gaming gate results (``overseer/gates.py`` ``GateResult(ok, reason,
fix_hint)``) into a single fitness ``dict``.

Contract (mirrored from the committed RED oracles
``tests/autocompiler/test_fitness.py`` and ``..._wired.py``):

``compute_fitness(fuzz_result, gate_results, mutation_vacuous, pathology) -> dict``

* ``fuzz_result`` is DUCK-TYPED: any object exposing ``equivalent`` (bool) and
  ``failures`` (list); optional ``total_inputs`` int (default ``20``).
* ``gate_results`` is a ``dict[str, object-with-.ok-or-bool]``.
* The returned dict ALWAYS contains the keys ``score`` (float in ``[0, 1]``),
  ``divergence_rate`` (float in ``[0, 1]``), ``prune`` (bool) and
  ``reasons`` (list[str]).

Hard prune-floor rules (``score == 0.0`` and ``prune is True``):
  * ``pathology`` in ``('error', 'hard_disproof')``,
  * ``mutation_vacuous`` is ``True``,
  * any gate result is falsy / has ``.ok`` False.

A clean equivalent run with all gates ok yields ``score == 1.0``,
``prune is False``. A near-miss (not equivalent, a few failing inputs) is
RATED, not discarded: ``0.0 < score < 1.0``.

The module is pure and stdlib-only: it performs no I/O, spawns no
process/model/network/subprocess, never calls the real fuzzer, touches no
``harness/**`` file and flips no runtime flag. It never raises.
"""
from __future__ import annotations
from typing import Any, Dict, List, Mapping
__all__ = ['compute_fitness', 'PRUNE_FLOOR', 'FULL_SCORE', 'DEFAULT_TOTAL_INPUTS']
PRUNE_FLOOR: float = 0.0
FULL_SCORE: float = 1.0
DEFAULT_TOTAL_INPUTS: int = 20
_FATAL_PATHOLOGIES = ('error', 'hard_disproof')

def _gate_ok(gate: Any) -> bool:
    """Return whether a single gate result is satisfied.

    Accepts either a plain bool/truthy value or a ``GateResult``-shaped object
    exposing an ``.ok`` attribute (``overseer/gates.py``).  Never raises.
    """
    if hasattr(gate, 'ok'):
        return bool(gate.ok)
    return bool(gate)

def _gate_reason(name: str, gate: Any) -> str:
    """Human-readable reason for a failing gate, used in ``reasons``."""
    reason = getattr(gate, 'reason', None)
    if isinstance(reason, str) and reason:
        return "gate '{0}' failed: {1}".format(name, reason)
    return "gate '{0}' failed".format(name)

def _classify(equivalent: bool, n_fail: int, pathology: Any) -> str:
    """Classify the empirical state into a stable string label.

    ``error``        -> the fuzz/build itself errored out,
    ``hard_disproof``-> >=1 counterexample (or a divergent run),
    ``soft_proof``   -> N clean rounds with zero failures.
    """
    if pathology == 'error':
        return 'error'
    if pathology == 'hard_disproof' or n_fail >= 1 or (not equivalent):
        return 'hard_disproof'
    return 'soft_proof'

def compute_fitness(fuzz_result: Any, gate_results: Mapping[str, Any], mutation_vacuous: bool, pathology: Any) -> Dict[str, Any]:
    """Fold the fuzzer signal and anti-gaming gates into a fitness dict.

    Pure and deterministic: identical inputs produce a byte-identical dict.
    The result contains only JSON-native scalar/list/dict types so it
    round-trips losslessly through ``json.dumps`` / ``json.loads``.
    """
    equivalent = bool(getattr(fuzz_result, 'equivalent', True))
    failures = getattr(fuzz_result, 'failures', None) or []
    try:
        n_fail = len(failures)
    except TypeError:
        n_fail = 0
    total_inputs = getattr(fuzz_result, 'total_inputs', DEFAULT_TOTAL_INPUTS)
    try:
        total_inputs = int(total_inputs)
    except (TypeError, ValueError):
        total_inputs = DEFAULT_TOTAL_INPUTS
    if total_inputs <= 0:
        total_inputs = DEFAULT_TOTAL_INPUTS
    divergence_rate = float(n_fail) / float(total_inputs)
    if divergence_rate < 0.0:
        divergence_rate = 0.0
    elif divergence_rate > 1.0:
        divergence_rate = 1.0
    gates_view: Dict[str, bool] = {}
    failed_gates: List[str] = []
    for name in sorted(gate_results or {}):
        gate = gate_results[name]
        ok = _gate_ok(gate)
        gates_view[name] = ok
        if not ok:
            failed_gates.append(name)
    reasons: List[str] = []
    pathology_str = '' if pathology is None else str(pathology)
    if pathology in _FATAL_PATHOLOGIES:
        reasons.append('pathology: {0}'.format(pathology_str))
    if mutation_vacuous:
        reasons.append('mutation is vacuous (no observable behavior)')
    for name in failed_gates:
        reasons.append(_gate_reason(name, gate_results[name]))
    prune = bool(reasons)
    if prune:
        score = PRUNE_FLOOR
    elif equivalent and n_fail == 0:
        score = FULL_SCORE
    else:
        score = 1.0 - divergence_rate
        if score < 0.0:
            score = 0.0
        elif score > 1.0:
            score = 1.0
    state = _classify(equivalent, n_fail, pathology)
    result: Dict[str, Any] = {'score': float(score), 'divergence_rate': float(divergence_rate), 'prune': bool(prune), 'reasons': reasons, 'state': state, 'equivalent': equivalent, 'failures': int(n_fail), 'total_inputs': int(total_inputs), 'mutation_vacuous': bool(mutation_vacuous), 'pathology': pathology_str, 'gates': gates_view}
    return result