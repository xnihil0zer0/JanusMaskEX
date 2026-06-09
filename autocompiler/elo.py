"""Standard pairwise Elo rating math for the autocompiler.

Provides ``expected_score`` and ``update_elo`` (the standard K-factor Elo
formulas) plus ``tournament_round``, which runs pairwise tournaments using
ONLY an injected ``rater_seam`` callable -- it never spawns a real model,
process, or network call. Standard library only.
"""
from __future__ import annotations
from typing import Callable, Dict, List, Tuple
__all__ = ['expected_score', 'update_elo', 'tournament_round']

def expected_score(ra: float, rb: float) -> float:
    """Return the expected score for player A against player B.

    Standard Elo logistic expectation::

        expected_a = 1.0 / (1.0 + 10.0 ** ((rb - ra) / 400.0))

    For equal ratings this is exactly ``0.5`` and it is symmetric in the
    sense that ``expected_score(ra, rb) + expected_score(rb, ra) == 1.0``.
    """
    return 1.0 / (1.0 + 10.0 ** ((rb - ra) / 400.0))

def update_elo(ra: float, rb: float, score_a: float, k: float=32.0) -> Tuple[float, float]:
    """Return updated ratings ``(ra', rb')`` after a game between A and B.

    ``score_a`` is A's outcome (1.0 win / 0.5 draw / 0.0 loss); B's outcome
    is ``1.0 - score_a``. Each rating moves by ``k`` times the difference
    between the actual and expected score. Because the expected scores and
    the actual scores each sum to 1.0, total rating is conserved.
    """
    expected_a = expected_score(ra, rb)
    expected_b = expected_score(rb, ra)
    score_b = 1.0 - score_a
    ra_new = ra + k * (score_a - expected_a)
    rb_new = rb + k * (score_b - expected_b)
    return (ra_new, rb_new)

def tournament_round(pairs: List[Tuple[object, object]], rater_seam: Callable[[object, object], float]) -> Dict[str, float]:
    """Run a round of pairwise games and return updated ratings by id.

    ``pairs`` is a list of ``(cand_a, cand_b)`` where each candidate is a
    duck-typed object with attributes ``id`` (str) and ``elo`` (float). The
    injected ``rater_seam(cand_a, cand_b) -> float`` is the ONLY external
    call; it is invoked exactly once per pair and returns A's score
    (1.0 win / 0.5 draw / 0.0 loss). Ratings are accumulated across the
    round and returned as a dict keyed by candidate id. Pure and
    deterministic given a deterministic rater -- never spawns a model,
    process, or network call.
    """
    ratings: Dict[str, float] = {}
    for cand_a, cand_b in pairs:
        ratings.setdefault(cand_a.id, float(cand_a.elo))
        ratings.setdefault(cand_b.id, float(cand_b.elo))
    for cand_a, cand_b in pairs:
        score_a = rater_seam(cand_a, cand_b)
        ra_new, rb_new = update_elo(ratings[cand_a.id], ratings[cand_b.id], score_a)
        ratings[cand_a.id] = ra_new
        ratings[cand_b.id] = rb_new
    return ratings