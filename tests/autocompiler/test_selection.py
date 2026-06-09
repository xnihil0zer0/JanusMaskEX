"""RED oracle — authoritative contract for autocompiler/selection.py (leaf ac-selection).

Contract: ``p_ucb(cands, c, total_n)`` returns the single candidate maximizing
``elo + c * sqrt(ln(total_n) / n_selected)`` where candidates are duck-typed
objects with attrs ``id`` (str), ``elo`` (float), ``n_selected`` (int).
UNSEEN candidates (``n_selected == 0``) have INFINITE exploration bonus and are
always preferred over seen ones (among several unseen, ties break
deterministically). All ties break deterministically by SMALLEST ``id``.
``p_ucb([], ...)`` returns None. Pure, deterministic, no I/O.
"""
import math
from types import SimpleNamespace

from autocompiler.selection import p_ucb


def _c(cid, elo, n):
    return SimpleNamespace(id=cid, elo=elo, n_selected=n)


def test_unseen_explored_first():
    cands = [_c('strong', 2000.0, 5), _c('fresh', 800.0, 0)]
    assert p_ucb(cands, 2.0, 5).id == 'fresh'


def test_exploit_math_matches_formula():
    a = _c('a', 1300.0, 4)
    b = _c('b', 1280.0, 1)
    c_const, total = 100.0, 5
    score = {x.id: x.elo + c_const * math.sqrt(math.log(total) / x.n_selected) for x in (a, b)}
    want = 'a' if score['a'] >= score['b'] else 'b'
    assert p_ucb([a, b], c_const, total).id == want
    assert score['b'] > score['a'], 'sanity: exploration bonus should favour b here'
    assert p_ucb([a, b], c_const, total).id == 'b'


def test_zero_c_is_pure_exploitation():
    cands = [_c('lo', 1000.0, 3), _c('hi', 1500.0, 9)]
    assert p_ucb(cands, 0.0, 12).id == 'hi'


def test_tie_breaks_by_smallest_id():
    cands = [_c('zeta', 1200.0, 2), _c('alpha', 1200.0, 2)]
    assert p_ucb(cands, 1.0, 4).id == 'alpha'
    cands_unseen = [_c('zeta', 1200.0, 0), _c('alpha', 1200.0, 0)]
    assert p_ucb(cands_unseen, 1.0, 4).id == 'alpha'


def test_deterministic_across_calls():
    def mk():
        return [_c('a', 1250.0, 2), _c('b', 1240.0, 1), _c('c', 1240.0, 1)]
    assert p_ucb(mk(), 3.0, 4).id == p_ucb(mk(), 3.0, 4).id


def test_empty_population_returns_none():
    assert p_ucb([], 1.0, 1) is None
