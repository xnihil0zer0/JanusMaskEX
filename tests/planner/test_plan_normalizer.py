"""Hermetic oracle for harness.planner.plan_normalizer.normalize_plan.

Pins the contract of normalize_plan:

* dedupe duplicate ``test_authoring`` oracles that share a ``mutation_target``,
  keeping the one referenced by the creating impl's ``verification_command``
  (else first by ``task_id``) and rewiring every dependency that pointed at the
  dropped oracle to the survivor (no dangling deps),
* enforce module-first ordering by flipping inverted impl/oracle edges so the
  oracle depends on the impl that creates its module and the impl no longer
  depends on the oracle (graph stays acyclic),
* be idempotent / a no-op on an already-correct plan, and
* leave a ``test_authoring`` task whose module has no creating impl untouched.

Fully hermetic: plan dicts are built inline; no filesystem, network, or pip
access, and only ``normalize_plan`` is imported.
"""
from __future__ import annotations
import copy
from typing import Any, Dict, List, Set
from harness.planner.plan_normalizer import normalize_plan

def tasks_of(plan: Any) -> List[Dict[str, Any]]:
    """Return the task list whether the plan is a ``{"tasks": [...]}`` dict or a
    bare list of task dicts."""
    if isinstance(plan, dict):
        return list(plan['tasks'])
    return list(plan)

def by_id(plan: Any) -> Dict[str, Dict[str, Any]]:
    return {t['task_id']: t for t in tasks_of(plan)}

def ids(plan: Any) -> Set[str]:
    return {t['task_id'] for t in tasks_of(plan)}

def deps(plan: Any, task_id: str) -> Set[str]:
    return set(by_id(plan)[task_id].get('dependencies', []))

def oracles_for(plan: Any, target: str) -> List[Dict[str, Any]]:
    return [t for t in tasks_of(plan) if t.get('meta_task_type') == 'test_authoring' and t.get('mutation_target') == target]

def assert_no_dangling_deps(plan: Any) -> None:
    present = ids(plan)
    for t in tasks_of(plan):
        for d in t.get('dependencies', []):
            assert d in present, f'dangling dependency {d!r} on task {t['task_id']!r}'

def is_acyclic(plan: Any) -> bool:
    graph = {t['task_id']: list(t.get('dependencies', [])) for t in tasks_of(plan)}
    WHITE, GRAY, BLACK = (0, 1, 2)
    color = {node: WHITE for node in graph}

    def visit(node: str) -> bool:
        color[node] = GRAY
        for nxt in graph.get(node, []):
            if nxt not in color:
                continue
            if color[nxt] == GRAY:
                return False
            if color[nxt] == WHITE and (not visit(nxt)):
                return False
        color[node] = BLACK
        return True
    return all((visit(node) for node in graph if color[node] == WHITE))

def make_duplicate_oracle_plan() -> Dict[str, Any]:
    """impl + two oracles sharing a mutation_target; impl's verification_command
    references oracle 'a'; an unrelated consumer depends on oracle 'b'."""
    return {'tasks': [{'task_id': 'impl-x', 'meta_task_type': 'implementation', 'mutation_target': 'harness.planner.x', 'files_touched': ['harness/planner/x.py'], 'dependencies': [], 'verification_command': 'python -m pytest tests/planner/test_x_a.py -q'}, {'task_id': 'oracle-x-a', 'meta_task_type': 'test_authoring', 'mutation_target': 'harness.planner.x', 'files_touched': ['tests/planner/test_x_a.py'], 'dependencies': ['impl-x'], 'verification_command': 'python -m pytest tests/planner/test_x_a.py -q'}, {'task_id': 'oracle-x-b', 'meta_task_type': 'test_authoring', 'mutation_target': 'harness.planner.x', 'files_touched': ['tests/planner/test_x_b.py'], 'dependencies': ['impl-x'], 'verification_command': 'python -m pytest tests/planner/test_x_b.py -q'}, {'task_id': 'consumer', 'meta_task_type': 'implementation', 'mutation_target': 'harness.planner.y', 'files_touched': ['harness/planner/y.py'], 'dependencies': ['oracle-x-b'], 'verification_command': 'python -m pytest tests/planner/test_y.py -q'}]}

def make_inverted_edge_plan() -> Dict[str, Any]:
    """impl depends on oracle (inverted); module-first should flip it."""
    return {'tasks': [{'task_id': 'impl-x', 'meta_task_type': 'implementation', 'mutation_target': 'harness.planner.x', 'files_touched': ['harness/planner/x.py'], 'dependencies': ['oracle-x'], 'verification_command': 'python -m pytest tests/planner/test_x.py -q'}, {'task_id': 'oracle-x', 'meta_task_type': 'test_authoring', 'mutation_target': 'harness.planner.x', 'files_touched': ['tests/planner/test_x.py'], 'dependencies': [], 'verification_command': 'python -m pytest tests/planner/test_x.py -q'}]}

def make_already_correct_plan() -> Dict[str, Any]:
    """Module-first, no duplicates: a no-op for normalize_plan."""
    return {'tasks': [{'task_id': 'impl-x', 'meta_task_type': 'implementation', 'mutation_target': 'harness.planner.x', 'files_touched': ['harness/planner/x.py'], 'dependencies': [], 'verification_command': 'python -m pytest tests/planner/test_x.py -q'}, {'task_id': 'oracle-x', 'meta_task_type': 'test_authoring', 'mutation_target': 'harness.planner.x', 'files_touched': ['tests/planner/test_x.py'], 'dependencies': ['impl-x'], 'verification_command': 'python -m pytest tests/planner/test_x.py -q'}]}

def make_no_impl_oracle_plan() -> Dict[str, Any]:
    """An oracle for harness.planner.orphan with no task creating that module."""
    return {'tasks': [{'task_id': 'oracle-orphan', 'meta_task_type': 'test_authoring', 'mutation_target': 'harness.planner.orphan', 'files_touched': ['tests/planner/test_orphan.py'], 'dependencies': ['impl-other'], 'verification_command': 'python -m pytest tests/planner/test_orphan.py -q'}, {'task_id': 'impl-other', 'meta_task_type': 'implementation', 'mutation_target': 'harness.planner.other', 'files_touched': ['harness/planner/other.py'], 'dependencies': [], 'verification_command': 'python -m pytest tests/planner/test_other.py -q'}]}

def make_vc_preference_plan() -> Dict[str, Any]:
    """Two duplicate oracles; first-by-task_id is 'a' but the impl's
    verification_command references 'b' -> 'b' must be kept."""
    return {'tasks': [{'task_id': 'impl-x', 'meta_task_type': 'implementation', 'mutation_target': 'harness.planner.x', 'files_touched': ['harness/planner/x.py'], 'dependencies': [], 'verification_command': 'python -m pytest tests/planner/test_x_b.py -q'}, {'task_id': 'oracle-x-a', 'meta_task_type': 'test_authoring', 'mutation_target': 'harness.planner.x', 'files_touched': ['tests/planner/test_x_a.py'], 'dependencies': ['impl-x'], 'verification_command': 'python -m pytest tests/planner/test_x_a.py -q'}, {'task_id': 'oracle-x-b', 'meta_task_type': 'test_authoring', 'mutation_target': 'harness.planner.x', 'files_touched': ['tests/planner/test_x_b.py'], 'dependencies': ['impl-x'], 'verification_command': 'python -m pytest tests/planner/test_x_b.py -q'}]}

def make_symbol_ledger_plan() -> Dict[str, Any]:
    """Mirror of the corrected plan_hooks_symbol_ledger_module shape: an impl
    plus two duplicate oracles, with the impl inverted onto the soon-dropped
    oracle.  Post-normalization must be deduped AND module-first."""
    return {'tasks': [{'task_id': 'impl-symbol-ledger', 'meta_task_type': 'implementation', 'mutation_target': 'harness.symbol_ledger', 'files_touched': ['harness/symbol_ledger.py'], 'dependencies': ['oracle-symbol-ledger-b'], 'verification_command': 'python -m pytest tests/test_symbol_ledger_a.py -q'}, {'task_id': 'oracle-symbol-ledger-a', 'meta_task_type': 'test_authoring', 'mutation_target': 'harness.symbol_ledger', 'files_touched': ['tests/test_symbol_ledger_a.py'], 'dependencies': [], 'verification_command': 'python -m pytest tests/test_symbol_ledger_a.py -q'}, {'task_id': 'oracle-symbol-ledger-b', 'meta_task_type': 'test_authoring', 'mutation_target': 'harness.symbol_ledger', 'files_touched': ['tests/test_symbol_ledger_b.py'], 'dependencies': [], 'verification_command': 'python -m pytest tests/test_symbol_ledger_b.py -q'}]}

def test_dedupe_duplicate_oracle_dropped_and_deps_rewired() -> None:
    plan = make_duplicate_oracle_plan()
    result = normalize_plan(copy.deepcopy(plan))
    survivors = oracles_for(result, 'harness.planner.x')
    assert len(survivors) == 1, 'exactly one oracle must survive dedupe'
    survivor = survivors[0]['task_id']
    assert survivor in {'oracle-x-a', 'oracle-x-b'}
    dropped = ({'oracle-x-a', 'oracle-x-b'} - {survivor}).pop()
    assert dropped not in ids(result), 'the duplicate oracle must be removed'
    assert deps(result, 'consumer') == {survivor}
    for t in tasks_of(result):
        assert dropped not in t.get('dependencies', [])
    assert_no_dangling_deps(result)

def test_module_first_flip_oracle_depends_on_impl() -> None:
    plan = make_inverted_edge_plan()
    result = normalize_plan(copy.deepcopy(plan))
    assert 'impl-x' in deps(result, 'oracle-x'), 'oracle must depend on its impl'
    assert 'oracle-x' not in deps(result, 'impl-x'), 'impl must not depend on oracle'
    assert is_acyclic(result), 'flipped graph must be acyclic'
    assert_no_dangling_deps(result)

def test_already_correct_plan_returned_unchanged() -> None:
    plan = make_already_correct_plan()
    original = copy.deepcopy(plan)
    result = normalize_plan(plan)
    assert plan == original, 'normalize_plan must not mutate its input'
    assert ids(result) == {'impl-x', 'oracle-x'}
    assert deps(result, 'oracle-x') == {'impl-x'}
    assert deps(result, 'impl-x') == set()
    assert is_acyclic(result)
    assert_no_dangling_deps(result)

def test_oracle_with_no_impl_task_left_untouched() -> None:
    plan = make_no_impl_oracle_plan()
    original_oracle = copy.deepcopy(by_id(plan)['oracle-orphan'])
    result = normalize_plan(copy.deepcopy(plan))
    res_oracle = by_id(result)['oracle-orphan']
    assert res_oracle == original_oracle
    assert res_oracle.get('dependencies') == ['impl-other']

def test_kept_oracle_prefers_impl_verification_command_reference() -> None:
    plan = make_vc_preference_plan()
    result = normalize_plan(copy.deepcopy(plan))
    survivors = oracles_for(result, 'harness.planner.x')
    assert len(survivors) == 1
    assert survivors[0]['task_id'] == 'oracle-x-b'
    assert 'oracle-x-a' not in ids(result)
    assert_no_dangling_deps(result)

def test_normalize_idempotent_double_apply_equal() -> None:
    for factory in (make_duplicate_oracle_plan, make_inverted_edge_plan, make_already_correct_plan, make_no_impl_oracle_plan, make_symbol_ledger_plan):
        once = normalize_plan(factory())
        twice = normalize_plan(copy.deepcopy(once))
        assert twice == once, f'normalize not idempotent for {factory.__name__}'

def test_symbol_ledger_worked_example_post_normalization_shape() -> None:
    plan = make_symbol_ledger_plan()
    result = normalize_plan(copy.deepcopy(plan))
    survivors = oracles_for(result, 'harness.symbol_ledger')
    assert len(survivors) == 1
    kept = survivors[0]['task_id']
    assert kept == 'oracle-symbol-ledger-a'
    assert 'oracle-symbol-ledger-b' not in ids(result)
    assert 'impl-symbol-ledger' in deps(result, kept)
    assert deps(result, 'impl-symbol-ledger') == set()
    assert is_acyclic(result)
    assert_no_dangling_deps(result)