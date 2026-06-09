"""P-UCB selection logic for autocompiler Candidate records.

Implements :func:`p_ucb`, which selects the single candidate maximizing the
Predictor + Upper Confidence Bound (P-UCB) score::

    elo + c * sqrt(ln(total_n) / n_selected)

Candidates are duck-typed objects exposing ``id`` (str), ``elo`` (float), and
``n_selected`` (int). Unseen candidates (``n_selected == 0``) are forced to
explore by treating their score as infinite, so they are always preferred over
seen candidates. All ties (seen or unseen) are broken deterministically by the
lexicographically smallest ``id``. Pure, deterministic, stdlib-only.
"""
import math
from typing import Optional, Sequence

def p_ucb(cands: Sequence[object], c: float, total_n: int) -> Optional[object]:
    """Return the candidate maximizing the P-UCB score.

    The score for a candidate is ``elo + c * sqrt(ln(total_n) / n_selected)``.
    Candidates with ``n_selected == 0`` are unseen and assigned an infinite
    exploration bonus so they are always selected ahead of seen candidates.
    Ties are resolved deterministically by choosing the lexicographically
    smallest ``id``.

    Args:
        cands: Sequence of candidate-like objects with ``id``, ``elo`` and
            ``n_selected`` attributes.
        c: Exploration constant.
        total_n: Total number of selections so far (the ``N`` in ``ln(N)``).

    Returns:
        The selected candidate, or ``None`` if ``cands`` is empty.
    """
    if not cands:
        return None

    def _score(cand: object) -> float:
        n_selected = cand.n_selected
        if n_selected == 0:
            return math.inf
        return cand.elo + c * math.sqrt(math.log(total_n) / n_selected)
    return min(cands, key=lambda cand: (-_score(cand), cand.id))