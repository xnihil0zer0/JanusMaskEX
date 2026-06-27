"""Pure, deterministic payload-mutation selection layer (Epic A, LEAF A1).

AlphaZero-PUCT arm selection with a softmax-over-Elo prior, plus a
verbatim-ported Elo update. Stdlib-only (``math`` only), no I/O, no network,
no subprocess, no LLM, and decoupled from JanusMaskJR's ``autocompiler``
package.

Selection score (AlphaZero PUCT, *not* UCB1)::

    score(a) = Q(a) + c * P(a) * sqrt(N) / (1 + N(a))

where ``Q(a)`` is the per-arm value, ``N`` the total visit count, ``N(a)`` the
per-arm visit count, and ``P(a)`` a softmax over the arms' Elo ratings using an
Elo-scaled temperature. The ``1 + N(a)`` denominator keeps unseen arms
(``N(a) == 0``) finitely scored and selectable.
"""
from __future__ import annotations
import math
from typing import Dict, Hashable, List, Mapping, Tuple
__all__ = ['expected_score', 'update_elo', 'select_next_mutation']
ELO_TEMPERATURE: float = 400.0 / math.log(10.0)

def expected_score(a: float, b: float) -> float:
    """Standard Elo logistic expectation that rating ``a`` beats rating ``b``.

    Verbatim port of ``autocompiler/elo.py``: ``1 / (1 + 10 ** ((b - a) / 400))``.
    """
    return 1.0 / (1.0 + 10.0 ** ((b - a) / 400.0))

def update_elo(winner: float, loser: float, outcome: float, k: float=32.0) -> Tuple[float, float]:
    """K-factor Elo update; returns the updated ``(rating_a, rating_b)`` pair.

    ``outcome`` is A's (``winner`` slot) score: 1.0 win / 0.5 draw / 0.0 loss.
    With the default ``k=32`` and equal ratings, a win yields ``+16`` to A and
    ``-16`` to B. Total rating is conserved (sum before == sum after, up to
    float rounding) since the two deltas are equal and opposite.
    """
    exp_a = expected_score(winner, loser)
    exp_b = expected_score(loser, winner)
    new_a = winner + k * (outcome - exp_a)
    new_b = loser + k * (1.0 - outcome - exp_b)
    return (new_a, new_b)

def _softmax_over_elo(arms: List[Hashable], elo: Mapping[Hashable, float], temperature: float=ELO_TEMPERATURE) -> Dict[Hashable, float]:
    """Softmax prior over arms keyed by their Elo rating.

    Uses max-subtraction for numerical stability so very large Elo gaps do not
    overflow ``math.exp``. Returns a proper probability distribution summing to
    1. Equal ratings yield a uniform distribution.
    """
    ratings = [float(elo[arm]) / temperature for arm in arms]
    top = max(ratings)
    weights = [math.exp(r - top) for r in ratings]
    total = math.fsum(weights)
    return {arm: w / total for arm, w in zip(arms, weights)}

def select_next_mutation(state: Hashable, arms: List[Hashable], elo: Mapping[Hashable, float], visits: Mapping[Hashable, int], values: Mapping[Hashable, float], c: float=1.414) -> Hashable:
    """Select the arm maximizing the AlphaZero-PUCT score.

    ``score(a) = Q(a) + c * P(a) * sqrt(N) / (1 + N(a))`` where ``P`` is a
    softmax over the arms' Elo ratings (Elo-scaled temperature), ``N(a)`` the
    per-arm visit count, and ``N`` the total visit count. Deterministic for
    fixed inputs; unseen arms (``N(a) == 0``) get a finite, prior-weighted
    score via the ``1 + N(a)`` denominator.
    """
    if not arms:
        raise ValueError('arms must be a non-empty sequence')
    prior = _softmax_over_elo(arms, elo)
    total_visits = math.fsum((float(visits.get(arm, 0)) for arm in arms))
    sqrt_total = math.sqrt(total_visits)
    best_arm: Hashable = arms[0]
    best_score = -math.inf
    for arm in arms:
        n_a = float(visits.get(arm, 0))
        q_a = float(values.get(arm, 0.0))
        exploration = c * prior[arm] * sqrt_total / (1.0 + n_a)
        score = q_a + exploration
        if score > best_score:
            best_score = score
            best_arm = arm
    return best_arm