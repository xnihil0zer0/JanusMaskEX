import pytest
import os
import subprocess
import copy
from pathlib import Path
from typing import Dict, Any, Set, List
from harness.planner.plan_normalizer import _drop_committed_module_impls

def init_git_repo(repo_dir: Path) -> Path:
    subprocess.run(['git', 'init'], cwd=str(repo_dir), capture_output=True, check=True)
    subprocess.run(['git', 'config', 'user.name', 'Test User'], cwd=str(repo_dir), capture_output=True, check=True)
    subprocess.run(['git', 'config', 'user.email', 'test@example.com'], cwd=str(repo_dir), capture_output=True, check=True)
    dummy_file = repo_dir / 'dummy.txt'
    dummy_file.write_text('initial')
    subprocess.run(['git', 'add', 'dummy.txt'], cwd=str(repo_dir), capture_output=True, check=True)
    subprocess.run(['git', 'commit', '-m', 'initial commit'], cwd=str(repo_dir), capture_output=True, check=True)
    return repo_dir

def commit_file(repo_dir: Path, rel_path: str, content: str='# module content'):
    file_path = repo_dir / rel_path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content)
    subprocess.run(['git', 'add', rel_path], cwd=str(repo_dir), capture_output=True, check=True)
    subprocess.run(['git', 'commit', '-m', f'add {rel_path}'], cwd=str(repo_dir), capture_output=True, check=True)

def make_clobber_plan() -> Dict[str, Any]:
    return {'tasks': [{'task_id': 'impl-1', 'meta_task_type': 'impl', 'files_touched': ['pkg/mod.py']}, {'task_id': 'oracle-1', 'meta_task_type': 'test_authoring', 'mutation_target': 'pkg.mod', 'files_touched': ['tests/harness/test_mod.py']}], 'normalizer_telemetry': []}

def test_required_pair_is_retained(tmp_path):
    repo_dir = init_git_repo(tmp_path)
    commit_file(repo_dir, 'pkg/mod.py')
    plan = make_clobber_plan()
    res = _drop_committed_module_impls(copy.deepcopy(plan), repo_dir, {'impl-1', 'oracle-1'})
    tasks = res.get('tasks', [])
    task_ids = {t.get('task_id') for t in tasks if isinstance(t, dict)}
    assert 'impl-1' in task_ids
    assert 'oracle-1' in task_ids
    assert not any(('duplicate_module_skipped' in str(m) for m in res.get('normalizer_telemetry', [])))

def test_non_required_clobber_still_dropped(tmp_path):
    repo_dir = init_git_repo(tmp_path)
    commit_file(repo_dir, 'pkg/mod.py')
    plan = make_clobber_plan()
    res = _drop_committed_module_impls(copy.deepcopy(plan), repo_dir, set())
    tasks = res.get('tasks', [])
    task_ids = {t.get('task_id') for t in tasks if isinstance(t, dict)}
    assert 'impl-1' not in task_ids
    assert 'oracle-1' not in task_ids
    telemetry = res.get('normalizer_telemetry', [])
    assert any(('duplicate_module_skipped:pkg/mod.py' in str(m) for m in telemetry))

def test_impl_only_pinned_retains_pair(tmp_path):
    repo_dir = init_git_repo(tmp_path)
    commit_file(repo_dir, 'pkg/mod.py')
    plan = make_clobber_plan()
    res = _drop_committed_module_impls(copy.deepcopy(plan), repo_dir, {'impl-1'})
    tasks = res.get('tasks', [])
    task_ids = {t.get('task_id') for t in tasks if isinstance(t, dict)}
    assert 'impl-1' in task_ids
    assert 'oracle-1' in task_ids
    assert not any(('duplicate_module_skipped' in str(m) for m in res.get('normalizer_telemetry', [])))

def test_oracle_only_pinned_retains_pair(tmp_path):
    repo_dir = init_git_repo(tmp_path)
    commit_file(repo_dir, 'pkg/mod.py')
    plan = make_clobber_plan()
    res = _drop_committed_module_impls(copy.deepcopy(plan), repo_dir, {'oracle-1'})
    tasks = res.get('tasks', [])
    task_ids = {t.get('task_id') for t in tasks if isinstance(t, dict)}
    assert 'impl-1' in task_ids
    assert 'oracle-1' in task_ids
    assert not any(('duplicate_module_skipped' in str(m) for m in res.get('normalizer_telemetry', [])))

def test_no_head_module_is_noop(tmp_path):
    repo_dir = init_git_repo(tmp_path)
    plan = make_clobber_plan()
    res = _drop_committed_module_impls(copy.deepcopy(plan), repo_dir, set())
    tasks = res.get('tasks', [])
    task_ids = {t.get('task_id') for t in tasks if isinstance(t, dict)}
    assert 'impl-1' in task_ids
    assert 'oracle-1' in task_ids
    assert not any(('duplicate_module_skipped' in str(m) for m in res.get('normalizer_telemetry', [])))

def test_determinism_and_purity(tmp_path):
    repo_dir = init_git_repo(tmp_path)
    commit_file(repo_dir, 'pkg/mod.py')
    plan = make_clobber_plan()
    res1 = _drop_committed_module_impls(copy.deepcopy(plan), repo_dir, {'impl-1'})
    res2 = _drop_committed_module_impls(copy.deepcopy(plan), repo_dir, {'impl-1'})
    assert res1 == res2
    plan_copy = copy.deepcopy(plan)
    res = _drop_committed_module_impls(plan, repo_dir, {'impl-1'})
    assert plan == plan_copy

def test_drop_committed_module_impls_none_pins_still_dropped(tmp_path):
    repo_dir = init_git_repo(tmp_path)
    commit_file(repo_dir, 'pkg/mod.py')
    plan = make_clobber_plan()
    res = _drop_committed_module_impls(copy.deepcopy(plan), repo_dir, None)
    tasks = res.get('tasks', [])
    task_ids = {t.get('task_id') for t in tasks if isinstance(t, dict)}
    assert 'impl-1' not in task_ids
    assert 'oracle-1' not in task_ids
    telemetry = res.get('normalizer_telemetry', [])
    assert any(('duplicate_module_skipped:pkg/mod.py' in str(m) for m in telemetry))

def test_drop_committed_module_impls_unrelated_pins_still_dropped(tmp_path):
    repo_dir = init_git_repo(tmp_path)
    commit_file(repo_dir, 'pkg/mod.py')
    plan = make_clobber_plan()
    res = _drop_committed_module_impls(copy.deepcopy(plan), repo_dir, {'unrelated-id'})
    tasks = res.get('tasks', [])
    task_ids = {t.get('task_id') for t in tasks if isinstance(t, dict)}
    assert 'impl-1' not in task_ids
    assert 'oracle-1' not in task_ids
    telemetry = res.get('normalizer_telemetry', [])
    assert any(('duplicate_module_skipped:pkg/mod.py' in str(m) for m in telemetry))

def test_drop_committed_module_impls_no_repo_root_is_noop():
    plan = make_clobber_plan()
    res = _drop_committed_module_impls(copy.deepcopy(plan), None, set())
    tasks = res.get('tasks', [])
    task_ids = {t.get('task_id') for t in tasks if isinstance(t, dict)}
    assert 'impl-1' in task_ids
    assert 'oracle-1' in task_ids
    assert not any(('duplicate_module_skipped' in str(m) for m in res.get('normalizer_telemetry', [])))

def test_drop_committed_module_impls_multiple_pairs_mixed(tmp_path):
    repo_dir = init_git_repo(tmp_path)
    commit_file(repo_dir, 'pkg/mod_a.py')
    commit_file(repo_dir, 'pkg/mod_b.py')
    plan = {'tasks': [{'task_id': 'impl-A', 'meta_task_type': 'impl', 'files_touched': ['pkg/mod_a.py']}, {'task_id': 'oracle-A', 'meta_task_type': 'test_authoring', 'mutation_target': 'pkg.mod_a', 'files_touched': ['tests/harness/test_mod_a.py']}, {'task_id': 'impl-B', 'meta_task_type': 'impl', 'files_touched': ['pkg/mod_b.py']}, {'task_id': 'oracle-B', 'meta_task_type': 'test_authoring', 'mutation_target': 'pkg.mod_b', 'files_touched': ['tests/harness/test_mod_b.py']}], 'normalizer_telemetry': []}
    res = _drop_committed_module_impls(copy.deepcopy(plan), repo_dir, {'impl-A'})
    tasks = res.get('tasks', [])
    task_ids = {t.get('task_id') for t in tasks if isinstance(t, dict)}
    assert 'impl-A' in task_ids
    assert 'oracle-A' in task_ids
    assert 'impl-B' not in task_ids
    assert 'oracle-B' not in task_ids
    telemetry = res.get('normalizer_telemetry', [])
    assert any(('duplicate_module_skipped:pkg/mod_b.py' in str(m) for m in telemetry))
    assert not any(('duplicate_module_skipped:pkg/mod_a.py' in str(m) for m in telemetry))

def test_drop_committed_module_impls_dependency_rewriting(tmp_path):
    repo_dir = init_git_repo(tmp_path)
    commit_file(repo_dir, 'pkg/mod.py')
    plan = {'tasks': [{'task_id': 'impl-1', 'meta_task_type': 'impl', 'files_touched': ['pkg/mod.py'], 'dependencies': ['pre-req']}, {'task_id': 'oracle-1', 'meta_task_type': 'test_authoring', 'mutation_target': 'pkg.mod', 'files_touched': ['tests/harness/test_mod.py'], 'dependencies': ['impl-1']}, {'task_id': 'other-task', 'meta_task_type': 'impl', 'files_touched': ['pkg/other.py'], 'dependencies': ['impl-1', 'oracle-1', 'independent-task']}], 'normalizer_telemetry': []}
    res_dropped = _drop_committed_module_impls(copy.deepcopy(plan), repo_dir, set())
    tasks_dropped = {t.get('task_id'): t for t in res_dropped.get('tasks', []) if isinstance(t, dict)}
    assert 'impl-1' not in tasks_dropped
    assert 'oracle-1' not in tasks_dropped
    assert tasks_dropped['other-task']['dependencies'] == ['independent-task']
    res_retained = _drop_committed_module_impls(copy.deepcopy(plan), repo_dir, {'impl-1'})
    tasks_retained = {t.get('task_id'): t for t in res_retained.get('tasks', []) if isinstance(t, dict)}
    assert 'impl-1' in tasks_retained
    assert 'oracle-1' in tasks_retained
    assert tasks_retained['other-task']['dependencies'] == ['impl-1', 'oracle-1', 'independent-task']

def test_drop_committed_module_impls_string_list_tuple_formats(tmp_path):
    repo_dir = init_git_repo(tmp_path)
    commit_file(repo_dir, 'pkg/mod.py')
    plan_template = make_clobber_plan()
    res_list = _drop_committed_module_impls(copy.deepcopy(plan_template), repo_dir, ['impl-1'])
    assert 'impl-1' in {t.get('task_id') for t in res_list['tasks']}
    res_tuple = _drop_committed_module_impls(copy.deepcopy(plan_template), repo_dir, ('oracle-1',))
    assert 'oracle-1' in {t.get('task_id') for t in res_tuple['tasks']}
    res_str = _drop_committed_module_impls(copy.deepcopy(plan_template), repo_dir, 'impl-1, oracle-1')
    assert 'impl-1' in {t.get('task_id') for t in res_str['tasks']}
    assert 'oracle-1' in {t.get('task_id') for t in res_str['tasks']}