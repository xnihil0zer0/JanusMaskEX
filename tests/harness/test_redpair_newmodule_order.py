import pytest
from pathlib import Path
from harness.planner.plan_normalizer import normalize_plan

def test_new_module_redpair_bug_empty_repo_root():
    plan = {'tasks': [{'task_id': 'pkg-newmod-oracle', 'meta_task_type': 'test_authoring', 'mutation_target': 'pkg.newmod', 'files_touched': ['tests/pkg/test_newmod.py'], 'dependencies': []}, {'task_id': 'pkg-newmod-impl', 'meta_task_type': 'harness_self_fix', 'files_touched': ['pkg/newmod.py'], 'dependencies': ['pkg-newmod-oracle'], 'verification_command': 'python -m pytest tests/pkg/test_newmod.py -q'}]}
    normalized = normalize_plan(plan, repo_root='')
    tasks = normalized['tasks']
    oracle = next((t for t in tasks if t['task_id'] == 'pkg-newmod-oracle'))
    impl = next((t for t in tasks if t['task_id'] == 'pkg-newmod-impl'))
    assert oracle.get('dependencies', []) == []
    assert impl.get('dependencies', []) == ['pkg-newmod-oracle']

def test_new_module_redpair_bug_none_repo_root():
    plan = {'tasks': [{'task_id': 'pkg-newmod-oracle', 'meta_task_type': 'test_authoring', 'mutation_target': 'pkg.newmod', 'files_touched': ['tests/pkg/test_newmod.py'], 'dependencies': []}, {'task_id': 'pkg-newmod-impl', 'meta_task_type': 'harness_self_fix', 'files_touched': ['pkg/newmod.py'], 'dependencies': ['pkg-newmod-oracle'], 'verification_command': 'python -m pytest tests/pkg/test_newmod.py -q'}]}
    normalized = normalize_plan(plan, repo_root=None)
    tasks = normalized['tasks']
    oracle = next((t for t in tasks if t['task_id'] == 'pkg-newmod-oracle'))
    impl = next((t for t in tasks if t['task_id'] == 'pkg-newmod-impl'))
    assert oracle.get('dependencies', []) == []
    assert impl.get('dependencies', []) == ['pkg-newmod-oracle']

def test_non_vacuity_regression():
    plan = {'tasks': [{'task_id': 'pkg-newmod-oracle', 'meta_task_type': 'test_authoring', 'mutation_target': 'pkg.newmod', 'files_touched': ['tests/pkg/test_newmod.py'], 'dependencies': []}, {'task_id': 'pkg-newmod-impl', 'meta_task_type': 'harness_self_fix', 'files_touched': ['pkg/newmod.py'], 'dependencies': ['pkg-newmod-oracle'], 'verification_command': 'python -m pytest tests/pkg/test_unrelated.py -q'}]}
    normalized = normalize_plan(plan, repo_root='')
    tasks = normalized['tasks']
    oracle = next((t for t in tasks if t['task_id'] == 'pkg-newmod-oracle'))
    impl = next((t for t in tasks if t['task_id'] == 'pkg-newmod-impl'))
    assert oracle.get('dependencies', []) == ['pkg-newmod-impl']
    assert impl.get('dependencies', []) == []

def test_existing_module_control(tmp_path):
    pkg_dir = tmp_path / 'pkg'
    pkg_dir.mkdir(parents=True, exist_ok=True)
    module_file = pkg_dir / 'newmod.py'
    module_file.write_text('# content')
    plan = {'tasks': [{'task_id': 'pkg-newmod-oracle', 'meta_task_type': 'test_authoring', 'mutation_target': 'pkg.newmod', 'files_touched': ['tests/pkg/test_newmod.py'], 'dependencies': []}, {'task_id': 'pkg-newmod-impl', 'meta_task_type': 'harness_self_fix', 'files_touched': ['pkg/newmod.py'], 'dependencies': ['pkg-newmod-oracle'], 'verification_command': 'python -m pytest tests/pkg/test_newmod.py -q'}]}
    normalized = normalize_plan(plan, repo_root=str(tmp_path))
    tasks = normalized['tasks']
    oracle = next((t for t in tasks if t['task_id'] == 'pkg-newmod-oracle'))
    impl = next((t for t in tasks if t['task_id'] == 'pkg-newmod-impl'))
    assert oracle.get('dependencies', []) == []
    assert impl.get('dependencies', []) == ['pkg-newmod-oracle']