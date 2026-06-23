"""RED oracle for the deterministic contract-injection pass in normalize_plan.

This is an effect-observing unit oracle (NOT an implementation). It exercises
the REAL ``harness.planner.plan_normalizer.normalize_plan`` and proves the new
``contracts=`` keyword behaviour:

* with a ``contracts`` mapping, each COVERED task (one whose ``task_id`` is a
  key of ``contracts``) gains ``constraints.integration_contract`` set to a
  deep copy of the declared contract, while an UNCOVERED task is left
  byte-identical (no ``constraints`` key materialized, no ``integration_contract``);
* with ``contracts`` of ``None`` or ``{}`` the pass is a strict opt-in no-op,
  byte-identical to prior behaviour (distinguishing the empty-dict from the
  None default proves additivity);
* the pass is pure -- it deep-copies and never mutates its input plan.

It is RED today: ``normalize_plan`` currently takes no ``contracts`` kwarg and
there is no ``_inject_integration_contracts`` pass, so the calls below raise /
mis-behave until the pass is implemented. All expected values are built as
test-local literals; no blob is copied.

NON-GOAL: this oracle is a pure unit test of the normalizer pass; it does NOT
integrate with the live runtime / wire-up gate, so a dedicated integration
test is not meaningful and the integration-test requirement is EXCUSED.
"""
from __future__ import annotations
import copy
from harness.planner.plan_normalizer import normalize_plan

def _declared_contract():
    """Return a FRESH copy of the declared integration contract literal."""
    return {'entrypoints': ['harness/orchestrator.py'], 'symbols': ['bar_fn'], 'runtime_oracle': 'drives bar_fn'}

def _make_plan():
    """Hand-build a plain plan dict with a covered and an uncovered task.

    Each task's ``constraints`` is ABSENT (not materialized as ``{}``) so the
    byte-identity / no-key-materialized assertions are meaningful.
    """
    return {'tasks': [{'task_id': 't-covered', 'meta_task_type': 'data_model'}, {'task_id': 't-other', 'meta_task_type': 'data_model'}]}

def _find_task(tasks, task_id):
    """Locate a task in ``tasks`` by ``task_id`` or fail loudly."""
    for t in tasks:
        if isinstance(t, dict) and t.get('task_id') == task_id:
            return t
    raise AssertionError('task %r not found among %r' % (task_id, [t.get('task_id') for t in tasks if isinstance(t, dict)]))

def _constraints_by_id(tasks):
    """Map ``task_id -> deepcopy(constraints)`` for byte-identity comparison."""
    return {t.get('task_id'): copy.deepcopy(t.get('constraints')) for t in tasks if isinstance(t, dict)}

def test_inject_sets_contract_on_covered_task_only():
    plan = _make_plan()
    contracts = {'t-covered': _declared_contract()}
    snapshot = copy.deepcopy(plan)
    out = normalize_plan(plan, repo_root=None, contracts=contracts)
    covered = _find_task(out['tasks'], 't-covered')
    other = _find_task(out['tasks'], 't-other')
    expected = {'entrypoints': ['harness/orchestrator.py'], 'symbols': ['bar_fn'], 'runtime_oracle': 'drives bar_fn'}
    assert covered.get('constraints', {}).get('integration_contract') == expected
    assert 'integration_contract' not in (other.get('constraints') or {})
    assert 'constraints' not in other
    assert plan == snapshot
    contracts['t-covered']['symbols'].append('mutated')
    assert covered['constraints']['integration_contract']['symbols'] == ['bar_fn']

def test_contracts_none_is_noop_byte_identical():
    plan = _make_plan()
    baseline = copy.deepcopy(plan)
    out = normalize_plan(copy.deepcopy(plan), repo_root=None, contracts=None)
    for t in out['tasks']:
        assert 'integration_contract' not in (t.get('constraints') or {})
    assert _constraints_by_id(out['tasks']) == _constraints_by_id(baseline['tasks'])

def test_contracts_empty_dict_is_noop():
    plan = _make_plan()
    baseline = copy.deepcopy(plan)
    out = normalize_plan(copy.deepcopy(plan), repo_root=None, contracts={})
    for t in out['tasks']:
        assert 'integration_contract' not in (t.get('constraints') or {})
    assert _constraints_by_id(out['tasks']) == _constraints_by_id(baseline['tasks'])

def test_normalize_plan_input_not_mutated_purity():
    plan = _make_plan()
    contracts = {'t-covered': _declared_contract()}
    snapshot = copy.deepcopy(plan)
    out = normalize_plan(plan, repo_root=None, contracts=contracts)
    assert out is not plan
    assert plan == snapshot

def test_other_normalize_plan_passes_still_run():
    plan = {'tasks': [{'task_id': 't-covered', 'meta_task_type': 'data_model'}, {'task_id': 't-other', 'meta_task_type': 'data_model', 'priority': 'High'}]}
    contracts = {'t-covered': _declared_contract()}
    out = normalize_plan(plan, repo_root=None, contracts=contracts)
    other = _find_task(out['tasks'], 't-other')
    covered = _find_task(out['tasks'], 't-covered')
    assert other['priority'] == 'high'
    assert covered.get('constraints', {}).get('integration_contract') == _declared_contract()

def test_uncovered_task_constraints_unchanged():
    plan = {'tasks': [{'task_id': 't-covered', 'meta_task_type': 'data_model'}, {'task_id': 't-other', 'meta_task_type': 'data_model', 'constraints': {'max_files': 3}}]}
    contracts = {'t-covered': _declared_contract()}
    out = normalize_plan(plan, repo_root=None, contracts=contracts)
    other = _find_task(out['tasks'], 't-other')
    covered = _find_task(out['tasks'], 't-covered')
    assert other.get('constraints') == {'max_files': 3}
    assert 'integration_contract' not in other.get('constraints', {})
    assert covered.get('constraints', {}).get('integration_contract') == _declared_contract()