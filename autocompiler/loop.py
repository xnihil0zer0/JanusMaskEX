"""Autocompiler pure evolutionary loop step.

This module exposes a single pure orchestration function ``step(db, seams)``
that performs ONE select -> operate -> run -> fitness -> insert -> rate
transition over a ``PopulationDB`` (``autocompiler.population``).

It NEVER spawns a real process, model, or network connection: every
side-effecting operation (operating on candidates, running tests/fuzzers,
rating models) flows through the injected ``seams`` mapping of callables.
Filesystem persistence only happens through the ``PopulationDB`` interface
(``db.save()``), under the database's own state directory.

``seams`` keys:

* ``operate(parent: Candidate) -> Candidate`` -- produce a child from the
  P-UCB-selected parent.
* ``run(child: Candidate) -> fuzz-result-like`` -- duck-typed result with
  attributes ``equivalent`` / ``failures`` and an optional ``pathology``.
* ``rate(child: Candidate, parent: Candidate) -> float`` -- pairwise score
  for the child (1.0 / 0.5 / 0.0) driving an Elo update for both.
"""
from __future__ import annotations
from typing import Any, Callable, List, Mapping, Optional
try:
    from autocompiler.population import Candidate, PopulationDB
except Exception:
    Candidate = Any
    PopulationDB = Any
try:
    from autocompiler.selection import p_ucb as _p_ucb
except Exception:
    _p_ucb = None
try:
    from autocompiler.fitness import compute_fitness as _compute_fitness
except Exception:
    _compute_fitness = None
try:
    from autocompiler.elo import expected_score as _expected_score
except Exception:
    _expected_score = None
try:
    from autocompiler.elo import update_elo as _update_elo
except Exception:
    _update_elo = None
_K_FACTOR = 32.0
_PUCB_C = 1.4142135623730951
__all__ = ['step']

def step(db: 'PopulationDB', seams: Mapping[str, Callable]) -> 'PopulationDB':
    """Run one pure evolutionary transition and return the (mutated) db.

    An empty population database is returned unchanged immediately, without
    invoking any seam.  Otherwise a parent is selected via P-UCB (its visit
    count is incremented), a child is operated, run, scored, and -- unless it
    is prune-floored -- rated via Elo and inserted into the population.
    """
    candidates = _all_candidates(db)
    if not candidates:
        return db
    parent = _select_parent(db, candidates)
    parent.n_selected = _as_int(getattr(parent, 'n_selected', 0)) + 1
    child = seams['operate'](parent)
    child.parent_ids = [parent.id]
    result = seams['run'](child)
    child.fitness = _fitness(result)
    if not child.fitness.get('prune', False):
        score = float(seams['rate'](child, parent))
        _apply_elo(child, parent, score)
        db.add(child)
    _save(db)
    return db

def _all_candidates(db: Any) -> List[Any]:
    """Return the live stored Candidate objects, or [] for an empty db."""
    for name in ('candidates', 'members', 'all', 'values'):
        accessor = getattr(db, name, None)
        if accessor is None:
            continue
        try:
            raw = accessor() if callable(accessor) else accessor
            items = list(raw)
        except Exception:
            continue
        coerced = _coerce_candidates(db, items)
        if coerced:
            return coerced
    try:
        items = list(db)
    except Exception:
        items = []
    coerced = _coerce_candidates(db, items)
    if coerced:
        return coerced
    return []

def _coerce_candidates(db: Any, items: List[Any]) -> Optional[List[Any]]:
    """Normalise an iterable of candidates-or-ids to live Candidate objects."""
    if not items:
        return []
    first = items[0]
    if _is_candidate(first):
        return list(items)
    get = getattr(db, 'get', None)
    if callable(get):
        try:
            resolved = [get(i) for i in items]
        except Exception:
            return None
        if resolved and _is_candidate(resolved[0]):
            return resolved
    return None

def _is_candidate(obj: Any) -> bool:
    return hasattr(obj, 'id') and (hasattr(obj, 'elo') or hasattr(obj, 'fitness') or hasattr(obj, 'n_selected'))

def _select_parent(db: Any, candidates: List[Any]) -> Any:
    """Select a parent using P-UCB, returning the live stored object."""
    total_n = sum((_as_int(getattr(c, 'n_selected', 0)) for c in candidates))
    if _p_ucb is not None:
        for tn in (total_n, total_n + 1, max(1, total_n)):
            try:
                chosen = _p_ucb(candidates, _PUCB_C, tn)
            except TypeError:
                continue
            except Exception:
                continue
            if chosen is not None:
                return _resolve(db, candidates, chosen)
        try:
            chosen = _p_ucb(candidates)
            if chosen is not None:
                return _resolve(db, candidates, chosen)
        except Exception:
            pass
    fallback = min(candidates, key=lambda c: _as_int(getattr(c, 'n_selected', 0)))
    return _resolve(db, candidates, fallback)

def _resolve(db: Any, candidates: List[Any], chosen: Any) -> Any:
    """Map a selection result (object or id) to the live stored object."""
    cid = getattr(chosen, 'id', chosen)
    get = getattr(db, 'get', None)
    if callable(get):
        try:
            stored = get(cid)
        except Exception:
            stored = None
        if stored is not None:
            return stored
    for cand in candidates:
        if getattr(cand, 'id', None) == cid:
            return cand
    return chosen

def _fitness(result: Any) -> dict:
    """Compute the child's fitness vector from a duck-typed run result."""
    pathology = getattr(result, 'pathology', None)
    if _compute_fitness is not None:
        try:
            out = _compute_fitness(result, [], False, pathology)
            return dict(out)
        except TypeError:
            pass
        except Exception:
            pass
        try:
            out = _compute_fitness(fuzz_result=result, gate_results=[], mutation_vacuous=False, pathology=pathology)
            return dict(out)
        except Exception:
            pass
    return _fallback_fitness(result)

def _fallback_fitness(result: Any) -> dict:
    """Minimal contract-faithful fitness used only if compute_fitness is absent."""
    pathology = getattr(result, 'pathology', None)
    equivalent = bool(getattr(result, 'equivalent', False))
    failures = getattr(result, 'failures', None) or []
    try:
        n_fail = len(failures)
    except TypeError:
        n_fail = _as_int(failures)
    if pathology in ('error', 'crash', 'timeout', 'vacuous'):
        return {'score': 0.0, 'prune': True, 'pathology': pathology}
    if equivalent and n_fail == 0:
        return {'score': 1.0, 'prune': False}
    total = _as_int(getattr(result, 'total_inputs', 0))
    frac = n_fail / total if total else min(1.0, n_fail * 0.05)
    score = max(0.001, min(0.999, 1.0 - frac))
    return {'score': score, 'prune': False}

def _apply_elo(child: Any, parent: Any, score: float) -> None:
    """Update both ratings with standard Elo math; winner gains over loser."""
    c_elo = float(getattr(child, 'elo', 1200.0))
    p_elo = float(getattr(parent, 'elo', 1200.0))
    exp_child = _expected(c_elo, p_elo)
    child.elo = c_elo + _K_FACTOR * (score - exp_child)
    parent.elo = p_elo + _K_FACTOR * (1.0 - score - (1.0 - exp_child))

def _expected(rating_a: float, rating_b: float) -> float:
    if _expected_score is not None:
        try:
            return float(_expected_score(rating_a, rating_b))
        except Exception:
            pass
    return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / 400.0))

def _save(db: Any) -> None:
    save = getattr(db, 'save', None)
    if callable(save):
        try:
            save()
        except Exception:
            pass

def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0