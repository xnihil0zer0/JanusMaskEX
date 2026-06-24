import importlib.util
import sys
from pathlib import Path
import pytest
from harness.paths import PROJECT_ROOT
plan_normalizer_path = Path(PROJECT_ROOT) / 'harness' / 'planner' / 'plan_normalizer.py'
spec = importlib.util.spec_from_file_location('plan_normalizer', str(plan_normalizer_path))
plan_normalizer = importlib.util.module_from_spec(spec)
sys.modules['plan_normalizer'] = plan_normalizer
spec.loader.exec_module(plan_normalizer)
_force_smoke_gated_leaf_impl = plan_normalizer._force_smoke_gated_leaf_impl

def test_external_unfuzzable_survivor(tmp_path):
    shared_oracle = 'test_oracle.py'
    (tmp_path / shared_oracle).touch()
    plan_ngv2_file = {'tasks': [{'task_id': 'task-unfuzzable-1', 'meta_task_type': 'refactor', 'verification_command': f'python -m pytest {shared_oracle}', 'files_touched': ['ngv2/something.py']}]}
    res = _force_smoke_gated_leaf_impl(plan_ngv2_file, tmp_path)
    surv = res['tasks'][0]
    assert surv.get('smoke_gated') is True
    assert surv['meta_task_type'] == 'refactor'
    plan_ngv2_mut = {'tasks': [{'task_id': 'task-unfuzzable-2', 'meta_task_type': 'refactor', 'verification_command': f'python -m pytest {shared_oracle}', 'mutation_target': 'ngv2.dotted.module'}]}
    res = _force_smoke_gated_leaf_impl(plan_ngv2_mut, tmp_path)
    surv = res['tasks'][0]
    assert surv.get('smoke_gated') is True
    assert surv['meta_task_type'] == 'refactor'
    plan_socket_hint = {'tasks': [{'task_id': 'task-unfuzzable-3', 'meta_task_type': 'refactor', 'verification_command': f'python -m pytest {shared_oracle}', 'spec': {'description': 'Uses loopback listener and bind( to run server'}}]}
    res = _force_smoke_gated_leaf_impl(plan_socket_hint, tmp_path)
    surv = res['tasks'][0]
    assert surv.get('smoke_gated') is True
    assert surv['meta_task_type'] == 'refactor'
    plan_socket_hint_notes = {'tasks': [{'task_id': 'task-unfuzzable-4', 'meta_task_type': 'refactor', 'verification_command': f'python -m pytest {shared_oracle}', 'spec': {'notes': 'Starts loopback listener on dynamic port'}}]}
    res = _force_smoke_gated_leaf_impl(plan_socket_hint_notes, tmp_path)
    surv = res['tasks'][0]
    assert surv.get('smoke_gated') is True
    assert surv['meta_task_type'] == 'refactor'

def test_external_fuzzable_survivor(tmp_path):
    shared_oracle = 'test_oracle.py'
    (tmp_path / shared_oracle).touch()
    plan_fuzzable = {'tasks': [{'task_id': 'task-fuzzable', 'meta_task_type': 'refactor', 'verification_command': f'python -m pytest {shared_oracle}', 'files_touched': ['harness/something.py'], 'mutation_target': 'harness.something', 'spec': {'description': 'A normal pure transform that does some calculations'}}]}
    res = _force_smoke_gated_leaf_impl(plan_fuzzable, tmp_path)
    surv = res['tasks'][0]
    assert surv.get('smoke_gated') is not True
    assert surv['meta_task_type'] == 'refactor'

def test_jm_self_noop(tmp_path):
    shared_oracle = 'test_oracle.py'
    (Path(PROJECT_ROOT) / shared_oracle).touch()
    try:
        plan_self = {'tasks': [{'task_id': 'task-self', 'meta_task_type': 'refactor', 'verification_command': f'python -m pytest {shared_oracle}', 'files_touched': ['ngv2/something.py']}]}
        res = _force_smoke_gated_leaf_impl(plan_self, PROJECT_ROOT)
        surv = res['tasks'][0]
        assert surv.get('smoke_gated') is not True
        assert surv['meta_task_type'] == 'refactor'
    finally:
        try:
            (Path(PROJECT_ROOT) / shared_oracle).unlink()
        except OSError:
            pass

def test_grouping_and_keep_more_guard(tmp_path):
    shared_oracle = 'test_oracle.py'
    (tmp_path / shared_oracle).touch()
    plan = {'required_task_ids': ['oracle-pinned'], 'tasks': [{'task_id': 'impl-survivor', 'meta_task_type': 'refactor', 'verification_command': f'python -m pytest {shared_oracle}', 'dependencies': ['oracle-pinned', 'impl-removed-1']}, {'task_id': 'impl-removed-1', 'meta_task_type': 'refactor', 'verification_command': f'python -m pytest {shared_oracle}', 'dependencies': []}, {'task_id': 'oracle-pinned', 'meta_task_type': 'test_authoring', 'verification_command': f'python -m pytest {shared_oracle}', 'dependencies': []}]}
    res = _force_smoke_gated_leaf_impl(plan, tmp_path)
    task_ids = {t['task_id'] for t in res['tasks']}
    assert 'impl-survivor' in task_ids
    assert 'oracle-pinned' in task_ids
    assert 'impl-removed-1' not in task_ids
    surv = next((t for t in res['tasks'] if t['task_id'] == 'impl-survivor'))
    assert 'oracle-pinned' in surv.get('dependencies', [])
    assert 'impl-removed-1' not in surv.get('dependencies', [])

def test_dynamic_import_plan_normalizer():
    assert plan_normalizer is not None
    assert _force_smoke_gated_leaf_impl is not None
    assert callable(_force_smoke_gated_leaf_impl)

def test_verification_command_parsing(tmp_path):
    (tmp_path / 'valid1.py').touch()
    (tmp_path / 'subdir').mkdir()
    (tmp_path / 'subdir' / 'valid2.py').touch()
    plan_group = {'tasks': [{'task_id': 't1', 'meta_task_type': 'refactor', 'verification_command': 'python -m pytest valid1.py subdir/valid2.py', 'files_touched': ['ngv2/foo.py']}, {'task_id': 't2', 'meta_task_type': 'refactor', 'verification_command': 'python -m pytest subdir/valid2.py valid1.py --verbose', 'files_touched': ['ngv2/bar.py']}]}
    res = _force_smoke_gated_leaf_impl(plan_group, tmp_path)
    assert len(res['tasks']) == 1
    surv = res['tasks'][0]
    assert surv['task_id'] == 't1'

def test_regression_under_fuzz_invariant(tmp_path):
    (tmp_path / 'oracle1.py').touch()
    (tmp_path / 'oracle2.py').touch()
    plan = {'tasks': [{'task_id': 'task-unfuzzable', 'meta_task_type': 'refactor', 'verification_command': 'python -m pytest oracle1.py', 'files_touched': ['ngv2/a.py']}, {'task_id': 'task-fuzzable', 'meta_task_type': 'refactor', 'verification_command': 'python -m pytest oracle2.py', 'files_touched': ['harness/b.py']}]}
    res = _force_smoke_gated_leaf_impl(plan, tmp_path)
    assert len(res['tasks']) == 2
    unfuzz = next((t for t in res['tasks'] if t['task_id'] == 'task-unfuzzable'))
    fuzz = next((t for t in res['tasks'] if t['task_id'] == 'task-fuzzable'))
    assert unfuzz.get('smoke_gated') is True
    assert fuzz.get('smoke_gated') is not True

def test_regression_no_unapproved_or_manifest_files_created(tmp_path):
    shared_oracle = 'test_oracle.py'
    (tmp_path / shared_oracle).touch()
    files_before = set(tmp_path.glob('**/*'))
    plan = {'tasks': [{'task_id': 'task-1', 'meta_task_type': 'refactor', 'verification_command': f'python -m pytest {shared_oracle}', 'files_touched': ['ngv2/something.py']}]}
    import copy
    plan_orig = copy.deepcopy(plan)
    res = _force_smoke_gated_leaf_impl(plan, tmp_path)
    assert plan == plan_orig
    files_after = set(tmp_path.glob('**/*'))
    assert files_before == files_after

def test_force_smoke_gated_leaf_impl_non_dict_plan():
    assert _force_smoke_gated_leaf_impl(None, '/some/path') is None
    assert _force_smoke_gated_leaf_impl([], '/some/path') == []
    assert _force_smoke_gated_leaf_impl('invalid', '/some/path') == 'invalid'

def test_force_smoke_gated_leaf_impl_empty_tasks(tmp_path):
    plan1 = {'tasks': []}
    assert _force_smoke_gated_leaf_impl(plan1, tmp_path) == plan1
    plan2 = {'tasks': 'not-a-list'}
    assert _force_smoke_gated_leaf_impl(plan2, tmp_path) == plan2

def test_force_smoke_gated_leaf_impl_child_slugs_noop(tmp_path):
    plan = {'child_slugs': ['some-epic'], 'tasks': [{'task_id': 'task-1', 'meta_task_type': 'refactor', 'verification_command': 'python -m pytest test.py'}]}
    assert _force_smoke_gated_leaf_impl(plan, tmp_path) == plan

def test_force_smoke_gated_leaf_impl_missing_verification_command(tmp_path):
    plan = {'tasks': [{'task_id': 'task-1', 'meta_task_type': 'refactor'}]}
    assert _force_smoke_gated_leaf_impl(plan, tmp_path) == plan

def test_force_smoke_gated_leaf_impl_invalid_repo_root(tmp_path):
    plan = {'tasks': [{'task_id': 'task-1', 'meta_task_type': 'refactor', 'verification_command': 'python -m pytest test.py'}]}
    assert _force_smoke_gated_leaf_impl(plan, None) == plan
    assert _force_smoke_gated_leaf_impl(plan, 12345) == plan

def test_force_smoke_gated_leaf_impl_idempotency(tmp_path):
    shared_oracle = 'test_oracle.py'
    (tmp_path / shared_oracle).touch()
    plan = {'tasks': [{'task_id': 'task-1', 'meta_task_type': 'refactor', 'verification_command': f'python -m pytest {shared_oracle}', 'files_touched': ['ngv2/something.py']}]}
    res1 = _force_smoke_gated_leaf_impl(plan, tmp_path)
    res2 = _force_smoke_gated_leaf_impl(res1, tmp_path)
    assert res1 == res2
regression_under_fuzz_invariant = test_regression_under_fuzz_invariant
regression_no_unapproved_or_manifest_files_created = test_regression_no_unapproved_or_manifest_files_created