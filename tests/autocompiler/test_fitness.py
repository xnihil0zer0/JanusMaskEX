"""RED oracle — authoritative contract for autocompiler/fitness.py (leaf ac-fitness-vector).

Contract: pure ``compute_fitness(fuzz_result, gate_results, mutation_vacuous,
pathology) -> dict``. ``fuzz_result`` is DUCK-TYPED (any object with attrs
``equivalent`` (bool), ``failures`` (list); optional ``total_inputs`` int,
default 20). ``gate_results`` is a dict[str, object-with-.ok-or-bool].
Returned dict ALWAYS contains keys: ``score`` (float in [0,1]),
``divergence_rate`` (float in [0,1]), ``prune`` (bool), ``reasons`` (list[str]).
Hard rules (prune-floor: score == 0.0 and prune True):
  * pathology in ('error', 'hard_disproof')
  * mutation_vacuous is True
  * any gate result falsy / .ok False
A clean equivalent run with all gates ok => score == 1.0, prune False.
A NEAR-MISS (not equivalent, few failing inputs) is NOT pruned: 0 < score < 1.
Deterministic (same inputs => identical dict) and JSON-safe. Never raises.
"""
import json
from types import SimpleNamespace

from autocompiler.fitness import compute_fitness


def _fuzz(equivalent=True, n_fail=0, total=20):
    return SimpleNamespace(equivalent=equivalent,
                           failures=[SimpleNamespace(input=i) for i in range(n_fail)],
                           total_inputs=total)


def test_clean_run_full_score():
    r = compute_fitness(_fuzz(), {'containment': True, 'vacuity': True}, False, None)
    assert r['prune'] is False
    assert r['score'] == 1.0
    assert r['divergence_rate'] == 0.0


def test_near_miss_scored_not_pruned():
    r = compute_fitness(_fuzz(equivalent=False, n_fail=1, total=20), {}, False, None)
    assert r['prune'] is False, 'a near-miss must be RATED, not discarded'
    assert 0.0 < r['score'] < 1.0
    assert r['divergence_rate'] == 1 / 20


def test_error_pathology_prune_floor():
    r = compute_fitness(_fuzz(equivalent=False, n_fail=5), {}, False, 'error')
    assert r['prune'] is True and r['score'] == 0.0


def test_hard_disproof_prune_floor():
    r = compute_fitness(_fuzz(equivalent=False, n_fail=20), {}, False, 'hard_disproof')
    assert r['prune'] is True and r['score'] == 0.0


def test_vacuous_mutation_prunes():
    r = compute_fitness(_fuzz(), {}, True, None)
    assert r['prune'] is True and r['score'] == 0.0


def test_failed_gate_prunes():
    gate = SimpleNamespace(ok=False, reason='write outside EVOLVE range')
    r = compute_fitness(_fuzz(), {'containment': gate}, False, None)
    assert r['prune'] is True and r['score'] == 0.0
    assert any(r['reasons']), 'prune must carry a reason'


def test_deterministic_and_json_safe():
    a = compute_fitness(_fuzz(equivalent=False, n_fail=3), {'g': True}, False, None)
    b = compute_fitness(_fuzz(equivalent=False, n_fail=3), {'g': True}, False, None)
    assert a == b
    json.dumps(a)


def test_required_keys_always_present():
    r = compute_fitness(_fuzz(), {}, False, None)
    assert {'score', 'divergence_rate', 'prune', 'reasons'} <= set(r)
