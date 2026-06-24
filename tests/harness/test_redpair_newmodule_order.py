import pytest
from pathlib import Path
from typing import Any, Dict, List
from harness.planner.plan_normalizer import normalize_plan
'\nMetadata:\nnon_goals: Integration is out of scope (no integration testing is performed).\nspec_author: null\n'

def test_new_module_redpair_bug(tmp_path):
    """
    Verify that for a new-module red-pair with empty repo_root (absent module),
    dependencies are preserved: impl depends on oracle, oracle dependencies are empty.
    (This is the bug: previously it would flip to oracle depending on impl if the module was absent).
    """
    plan = {'tasks': [{'task_id': 'pkg-newmod-oracle', 'meta_task_type': 'test_authoring', 'mutation_target': 'pkg.newmod', 'files_touched': ['tests/pkg/test_newmod.py'], 'dependencies': [], 'verification_command': 'python -m pytest tests/pkg/test_newmod.py -q'}, {'task_id': 'pkg-newmod-impl', 'meta_task_type': 'harness_self_fix', 'files_touched': ['pkg/newmod.py'], 'dependencies': ['pkg-newmod-oracle'], 'verification_command': 'python -m pytest tests/pkg/test_newmod.py -q'}]}
    normalized = normalize_plan(plan, repo_root=str(tmp_path))
    tasks = normalized['tasks']
    oracle_task = [t for t in tasks if t['task_id'] == 'pkg-newmod-oracle'][0]
    impl_task = [t for t in tasks if t['task_id'] == 'pkg-newmod-impl'][0]
    assert oracle_task.get('dependencies') == []
    assert impl_task.get('dependencies') == ['pkg-newmod-oracle']

def test_non_vacuity_regression(tmp_path):
    """
    Verify narrowness: if the verification command does not substring-name the oracle test,
    the dependency direction is flipped (oracle depends on impl).
    """
    plan = {'tasks': [{'task_id': 'pkg-newmod-oracle', 'meta_task_type': 'test_authoring', 'mutation_target': 'pkg.newmod', 'files_touched': ['tests/pkg/test_newmod.py'], 'dependencies': [], 'verification_command': 'python -m pytest tests/pkg/test_newmod.py -q'}, {'task_id': 'pkg-newmod-impl', 'meta_task_type': 'harness_self_fix', 'files_touched': ['pkg/newmod.py'], 'dependencies': ['pkg-newmod-oracle'], 'verification_command': 'python -m pytest tests/pkg/test_unrelated.py -q'}]}
    normalized = normalize_plan(plan, repo_root=str(tmp_path))
    tasks = normalized['tasks']
    oracle_task = [t for t in tasks if t['task_id'] == 'pkg-newmod-oracle'][0]
    impl_task = [t for t in tasks if t['task_id'] == 'pkg-newmod-impl'][0]
    assert oracle_task.get('dependencies') == ['pkg-newmod-impl']
    assert impl_task.get('dependencies') == []

def test_existing_module_control(tmp_path):
    """
    Verify existing-module control: when the module file is present in the repo_root,
    the dependency direction is preserved (impl depends on oracle).
    """
    pkg_dir = tmp_path / 'pkg'
    pkg_dir.mkdir(parents=True, exist_ok=True)
    module_file = pkg_dir / 'newmod.py'
    module_file.write_text('# existing module content')
    plan = {'tasks': [{'task_id': 'pkg-newmod-oracle', 'meta_task_type': 'test_authoring', 'mutation_target': 'pkg.newmod', 'files_touched': ['tests/pkg/test_newmod.py'], 'dependencies': [], 'verification_command': 'python -m pytest tests/pkg/test_newmod.py -q'}, {'task_id': 'pkg-newmod-impl', 'meta_task_type': 'harness_self_fix', 'files_touched': ['pkg/newmod.py'], 'dependencies': ['pkg-newmod-oracle'], 'verification_command': 'python -m pytest tests/pkg/test_newmod.py -q'}]}
    normalized = normalize_plan(plan, repo_root=str(tmp_path))
    tasks = normalized['tasks']
    oracle_task = [t for t in tasks if t['task_id'] == 'pkg-newmod-oracle'][0]
    impl_task = [t for t in tasks if t['task_id'] == 'pkg-newmod-impl'][0]
    assert oracle_task.get('dependencies') == []
    assert impl_task.get('dependencies') == ['pkg-newmod-oracle']

def test_new_module_redpair_bug_none_repo_root():
    """
    Verify new-module redpair logic when repo_root is not provided or is None.
    With the fix (removing repo_root guard), it preserves the dependency direction.
    """
    plan = {'tasks': [{'task_id': 'pkg-newmod-oracle', 'meta_task_type': 'test_authoring', 'mutation_target': 'pkg.newmod', 'files_touched': ['tests/pkg/test_newmod.py'], 'dependencies': [], 'verification_command': 'python -m pytest tests/pkg/test_newmod.py -q'}, {'task_id': 'pkg-newmod-impl', 'meta_task_type': 'harness_self_fix', 'files_touched': ['pkg/newmod.py'], 'dependencies': ['pkg-newmod-oracle'], 'verification_command': 'python -m pytest tests/pkg/test_newmod.py -q'}]}
    normalized = normalize_plan(plan, repo_root=None)
    tasks = normalized['tasks']
    oracle_task = [t for t in tasks if t['task_id'] == 'pkg-newmod-oracle'][0]
    impl_task = [t for t in tasks if t['task_id'] == 'pkg-newmod-impl'][0]
    assert oracle_task.get('dependencies') == []
    assert impl_task.get('dependencies') == ['pkg-newmod-oracle']

def test_new_module_redpair_bug_no_tasks():
    """Verify normalizer behaviour when tasks is empty."""
    plan = {'tasks': []}
    normalized = normalize_plan(plan, repo_root='/tmp')
    assert normalized == {'tasks': []}

def test_new_module_redpair_bug_not_dict_plan():
    """Verify normalizer behaviour when plan is not a dictionary."""
    plan = 'not-a-dict'
    normalized = normalize_plan(plan, repo_root='/tmp')
    assert normalized == 'not-a-dict'

def test_new_module_redpair_bug_unrelated_tasks():
    """Verify that unrelated tasks (not test_authoring/impl pairings) remain unchanged."""
    plan = {'tasks': [{'task_id': 'generic-task', 'dependencies': ['other-task']}]}
    normalized = normalize_plan(plan, repo_root='/tmp')
    tasks = normalized['tasks']
    assert tasks[0]['dependencies'] == ['other-task']

def test_new_module_redpair_bug_deduplication():
    """Verify deduplication logic alongside the redpair logic."""
    plan = {'tasks': [{'task_id': 'oracle-a', 'meta_task_type': 'test_authoring', 'mutation_target': 'pkg.newmod', 'files_touched': ['tests/pkg/test_newmod.py'], 'dependencies': [], 'verification_command': 'python -m pytest tests/pkg/test_newmod.py -q'}, {'task_id': 'oracle-b', 'meta_task_type': 'test_authoring', 'mutation_target': 'pkg.newmod', 'files_touched': ['tests/pkg/test_newmod.py'], 'dependencies': [], 'verification_command': 'python -m pytest tests/pkg/test_newmod.py -q'}]}
    normalized = normalize_plan(plan, repo_root='/tmp')
    tasks = normalized['tasks']
    assert len(tasks) == 1
    assert tasks[0]['task_id'] in ('oracle-a', 'oracle-b')

def test_new_module_redpair_bug_acyclic_cycle():
    """Verify that enforcing module-first ordering preserves acyclicity."""
    plan = {'tasks': [{'task_id': 'oracle-cycle', 'meta_task_type': 'test_authoring', 'mutation_target': 'pkg.newmod', 'files_touched': ['tests/pkg/test_newmod.py'], 'dependencies': ['impl-cycle'], 'verification_command': 'python -m pytest tests/pkg/test_unrelated.py -q'}, {'task_id': 'impl-cycle', 'meta_task_type': 'harness_self_fix', 'files_touched': ['pkg/newmod.py'], 'dependencies': ['oracle-cycle'], 'verification_command': 'python -m pytest tests/pkg/test_unrelated.py -q'}]}
    normalized = normalize_plan(plan, repo_root=None)
    tasks = normalized['tasks']
    oracle_task = [t for t in tasks if t['task_id'] == 'oracle-cycle'][0]
    impl_task = [t for t in tasks if t['task_id'] == 'impl-cycle'][0]
    assert not (impl_task['task_id'] in oracle_task.get('dependencies', []) and oracle_task['task_id'] in impl_task.get('dependencies', []))

def test_new_module_redpair_bug_idempotency(tmp_path):
    """Verify that normalize_plan is idempotent."""
    plan = {'tasks': [{'task_id': 'pkg-newmod-oracle', 'meta_task_type': 'test_authoring', 'mutation_target': 'pkg.newmod', 'files_touched': ['tests/pkg/test_newmod.py'], 'dependencies': [], 'verification_command': 'python -m pytest tests/pkg/test_newmod.py -q'}, {'task_id': 'pkg-newmod-impl', 'meta_task_type': 'harness_self_fix', 'files_touched': ['pkg/newmod.py'], 'dependencies': ['pkg-newmod-oracle'], 'verification_command': 'python -m pytest tests/pkg/test_newmod.py -q'}]}
    normalized_once = normalize_plan(plan, repo_root=str(tmp_path))
    normalized_twice = normalize_plan(normalized_once, repo_root=str(tmp_path))
    assert normalized_once == normalized_twice

def test_new_module_redpair_bug_multiple_oracles_one_impl(tmp_path):
    """
    Verify that when multiple oracles are mapped to a single impl via verification_command,
    their dependencies are all correctly preserved (impl depends on all oracles).
    """
    plan = {'tasks': [{'task_id': 'oracle-1', 'meta_task_type': 'test_authoring', 'mutation_target': 'pkg.newmod', 'files_touched': ['tests/pkg/test1.py'], 'dependencies': [], 'verification_command': 'python -m pytest tests/pkg/test1.py -q'}, {'task_id': 'oracle-2', 'meta_task_type': 'test_authoring', 'mutation_target': 'pkg.newmod', 'files_touched': ['tests/pkg/test2.py'], 'dependencies': [], 'verification_command': 'python -m pytest tests/pkg/test2.py -q'}, {'task_id': 'pkg-newmod-impl', 'meta_task_type': 'harness_self_fix', 'files_touched': ['pkg/newmod.py'], 'dependencies': ['oracle-1', 'oracle-2'], 'verification_command': 'python -m pytest tests/pkg/test1.py tests/pkg/test2.py -q'}]}
    normalized = normalize_plan(plan, repo_root=str(tmp_path))
    tasks = normalized['tasks']
    o1_task = [t for t in tasks if t['task_id'] == 'oracle-1'][0]
    o2_task = [t for t in tasks if t['task_id'] == 'oracle-2'][0]
    impl_task = [t for t in tasks if t['task_id'] == 'pkg-newmod-impl'][0]
    assert o1_task.get('dependencies') == []
    assert o2_task.get('dependencies') == []
    assert set(impl_task.get('dependencies', [])) == {'oracle-1', 'oracle-2'}