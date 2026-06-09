"""RED oracle — authoritative contract for autocompiler/elo.py (leaf ac-elo).

Contract: standard Elo over candidates. ``expected_score(ra, rb) -> float`` =
1 / (1 + 10 ** ((rb - ra) / 400)). ``update_elo(ra, rb, score_a, k=32) ->
(ra', rb')`` with ra' = ra + k * (score_a - expected_score(ra, rb)) and the
symmetric update for rb (score_b = 1 - score_a). ``tournament_round(pairs,
rater_seam) -> dict[str, float]`` takes ``pairs`` = list of (cand_a, cand_b)
where candidates are duck-typed objects with attrs ``id`` (str) and ``elo``
(float); calls the INJECTED ``rater_seam(cand_a, cand_b) -> float`` (score for
a: 1.0 win / 0.5 draw / 0.0 loss) EXACTLY ONCE per pair, and returns the dict
of updated ratings keyed by candidate id. Pure: the injected rater is the ONLY
external call — no process, model, or network.
"""
import math
from types import SimpleNamespace

from autocompiler.elo import expected_score, update_elo, tournament_round


def test_expected_score_symmetric_at_equal_rating():
    assert expected_score(1200.0, 1200.0) == 0.5


def test_expected_score_formula():
    assert math.isclose(expected_score(1400.0, 1200.0),
                        1 / (1 + 10 ** ((1200.0 - 1400.0) / 400)))
    assert math.isclose(expected_score(1400.0, 1200.0) + expected_score(1200.0, 1400.0), 1.0)


def test_update_elo_k_factor():
    ra2, rb2 = update_elo(1200.0, 1200.0, 1.0)
    assert math.isclose(ra2, 1216.0) and math.isclose(rb2, 1184.0)


def test_update_elo_zero_sum():
    ra2, rb2 = update_elo(1350.0, 1100.0, 0.0, k=24)
    assert math.isclose((ra2 - 1350.0) + (rb2 - 1100.0), 0.0, abs_tol=1e-9)


def test_tournament_round_uses_injected_rater_only():
    a = SimpleNamespace(id='a', elo=1200.0)
    b = SimpleNamespace(id='b', elo=1200.0)
    c = SimpleNamespace(id='c', elo=1200.0)
    calls = []

    def rater(x, y):
        calls.append((x.id, y.id))
        return 1.0
    ratings = tournament_round([(a, b), (a, c)], rater)
    assert len(calls) == 2, 'rater_seam must be called exactly once per pair'
    assert ratings['a'] > 1200.0
    assert ratings['b'] < 1200.0 and ratings['c'] < 1200.0


def test_tournament_round_deterministic():
    def mk():
        return (SimpleNamespace(id='a', elo=1200.0), SimpleNamespace(id='b', elo=1250.0))
    r1 = tournament_round([mk()], lambda x, y: 0.5)
    r2 = tournament_round([mk()], lambda x, y: 0.5)
    assert r1 == r2


def test_tournament_round_empty():
    assert tournament_round([], lambda x, y: 1.0) == {}
