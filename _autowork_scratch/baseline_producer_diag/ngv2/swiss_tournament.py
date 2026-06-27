"""Deterministic Swiss-system finding ranker over an injected judge seam.

Epic A, LEAF A3 (``ngv2/swiss_tournament.py``).

Pure, stdlib-only, and deterministic: the sole comparison oracle is the
injected ``judge(a, b) -> float`` seam returning A's score against B
(``1.0`` a wins / ``0.5`` draw / ``0.0`` b wins), mirroring the autocompiler
``rater_seam`` convention. Ranking uses Swiss-system pairing so the judge is
consulted O(rounds * N) times -- strictly fewer than the full round-robin
N*(N-1)/2 -- while producing a stable, fully reproducible ordering.
"""
from __future__ import annotations
import math
from typing import Any, Callable, List
__all__ = ['swiss_rank']

def _num_rounds(n: int) -> int:
    """Bounded round count R = ceil(log2(N)) (>= 1 for any real bracket)."""
    if n <= 1:
        return 0
    return max(1, math.ceil(math.log2(n)))

def swiss_rank(items: List[Any], judge: Callable[[Any, Any], Any]) -> List[Any]:
    """Rank ``items`` best-first via deterministic Swiss-system pairing.

    ``judge(a, b)`` is the only comparison seam; it returns A's score against
    B (``1.0`` win / ``0.5`` draw / ``0.0`` loss). Pairing and tie-breaking are
    deterministic functions of the accumulated score and each item's original
    index, so identical inputs always yield an identical permutation of
    ``items``. The judge is invoked O(R * N) times, never O(N^2).

    Edge cases: empty input returns empty; a single item is returned as-is with
    zero judge calls; an odd bracket awards one item a bye (a free point) each
    round with no judge call.
    """
    n = len(items)
    if n <= 1:
        return list(items)
    scores = [0.0] * n
    byes = [0] * n
    rounds = _num_rounds(n)
    for _ in range(rounds):
        order = sorted(range(n), key=lambda idx: (-scores[idx], idx))
        if n % 2 == 1:
            bye_idx = min(order, key=lambda idx: (byes[idx], scores[idx], -idx))
            byes[bye_idx] += 1
            scores[bye_idx] += 1.0
            order = [idx for idx in order if idx != bye_idx]
        for pos in range(0, len(order), 2):
            a_idx = order[pos]
            b_idx = order[pos + 1]
            a_score = float(judge(items[a_idx], items[b_idx]))
            scores[a_idx] += a_score
            scores[b_idx] += 1.0 - a_score
    final_order = sorted(range(n), key=lambda idx: (-scores[idx], idx))
    return [items[idx] for idx in final_order]