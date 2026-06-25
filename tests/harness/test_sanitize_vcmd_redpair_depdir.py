"""Oracle: verify the dependency-direction gate for fix-forward red-pairs in _sanitize_impl_verification_commands."""
from __future__ import annotations
import importlib
import pytest
plan_normalizer = importlib.import_module('harness.planner.plan_normalizer')
_sanitize_impl_verification_commands = plan_normalizer._sanitize_impl_verification_commands
_build_graph = plan_normalizer._build_graph
_reaches = plan_normalizer._reaches

def _make_repo(tmp_path):
    """A minimal repo with an importable module."""
    pkg_dir = tmp_path / 'pkg'
    pkg_dir.mkdir(parents=True, exist_ok=True)
    (pkg_dir / '__init__.py').write_text('')
    (pkg_dir / 'mod.py').write_text('# module under test\n')
    return tmp_path

def test_downstream_oracle_repaired(tmp_path):
    repo = _make_repo(tmp_path)
    plan = {'tasks': [{'task_id': 'imp', 'meta_task_type': 'validation', 'files_touched': ['pkg/mod.py'], 'dependencies': [], 'verification_command': 'python -m pytest tests/test_mod.py -q'}, {'task_id': 'orc', 'meta_task_type': 'test_authoring', 'mutation_target': 'pkg.mod', 'files_touched': ['tests/test_mod.py'], 'dependencies': ['imp']}]}
    out = _sanitize_impl_verification_commands(plan, repo)
    impl_task = [t for t in out['tasks'] if t['task_id'] == 'imp'][0]
    vc = impl_task['verification_command']
    assert 'tests/test_mod.py' not in vc
    assert 'python -c' in vc
    assert 'pkg.mod' in vc or 'pkg' in vc

def test_ancestor_oracle_preserved(tmp_path):
    repo = _make_repo(tmp_path)
    plan = {'tasks': [{'task_id': 'imp', 'meta_task_type': 'validation', 'files_touched': ['pkg/mod.py'], 'dependencies': ['orc'], 'verification_command': 'python -m pytest tests/test_mod.py -q'}, {'task_id': 'orc', 'meta_task_type': 'test_authoring', 'mutation_target': 'pkg.mod', 'files_touched': ['tests/test_mod.py'], 'dependencies': []}]}
    out = _sanitize_impl_verification_commands(plan, repo)
    impl_task = [t for t in out['tasks'] if t['task_id'] == 'imp'][0]
    vc = impl_task['verification_command']
    assert 'tests/test_mod.py' in vc

def test_transitive_downstream_oracle_repaired(tmp_path):
    repo = _make_repo(tmp_path)
    plan = {'tasks': [{'task_id': 'imp', 'meta_task_type': 'validation', 'files_touched': ['pkg/mod.py'], 'dependencies': [], 'verification_command': 'python -m pytest tests/test_mod.py -q'}, {'task_id': 'mid', 'meta_task_type': 'validation', 'files_touched': ['pkg/mid.py'], 'dependencies': ['imp']}, {'task_id': 'orc', 'meta_task_type': 'test_authoring', 'mutation_target': 'pkg.mod', 'files_touched': ['tests/test_mod.py'], 'dependencies': ['mid']}]}
    out = _sanitize_impl_verification_commands(plan, repo)
    impl_task = [t for t in out['tasks'] if t['task_id'] == 'imp'][0]
    vc = impl_task['verification_command']
    assert 'tests/test_mod.py' not in vc
    assert 'python -c' in vc

def test_transitive_ancestor_oracle_preserved(tmp_path):
    repo = _make_repo(tmp_path)
    plan = {'tasks': [{'task_id': 'imp', 'meta_task_type': 'validation', 'files_touched': ['pkg/mod.py'], 'dependencies': ['mid'], 'verification_command': 'python -m pytest tests/test_mod.py -q'}, {'task_id': 'mid', 'meta_task_type': 'validation', 'files_touched': ['pkg/mid.py'], 'dependencies': ['orc']}, {'task_id': 'orc', 'meta_task_type': 'test_authoring', 'mutation_target': 'pkg.mod', 'files_touched': ['tests/test_mod.py'], 'dependencies': []}]}
    out = _sanitize_impl_verification_commands(plan, repo)
    impl_task = [t for t in out['tasks'] if t['task_id'] == 'imp'][0]
    vc = impl_task['verification_command']
    assert 'tests/test_mod.py' in vc

def test_determinism_and_idempotency(tmp_path):
    repo = _make_repo(tmp_path)
    plan = {'tasks': [{'task_id': 'imp', 'meta_task_type': 'validation', 'files_touched': ['pkg/mod.py'], 'dependencies': ['orc'], 'verification_command': 'python -m pytest tests/test_mod.py -q'}, {'task_id': 'orc', 'meta_task_type': 'test_authoring', 'mutation_target': 'pkg.mod', 'files_touched': ['tests/test_mod.py'], 'dependencies': []}]}
    once = _sanitize_impl_verification_commands(plan, repo)
    twice = _sanitize_impl_verification_commands(once, repo)
    assert once == twice

def test_dynamic_import_loading():
    import sys
    assert 'harness.planner.plan_normalizer' in sys.modules
    with open(__file__, 'r', encoding='utf-8') as f:
        content = f.read()
    import ast
    tree = ast.parse(content)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in ('exec', 'eval', '__import__')

def test_missing_dependencies_defensive(tmp_path):
    repo = _make_repo(tmp_path)
    plan = {'tasks': [{'task_id': 'imp', 'meta_task_type': 'validation', 'files_touched': ['pkg/mod.py'], 'verification_command': 'python -m pytest tests/test_mod.py -q'}, {'task_id': 'orc', 'meta_task_type': 'test_authoring', 'mutation_target': 'pkg.mod', 'files_touched': ['tests/test_mod.py'], 'dependencies': None}]}
    out = _sanitize_impl_verification_commands(plan, repo)
    assert isinstance(out, dict)

def test_cyclical_dependencies(tmp_path):
    repo = _make_repo(tmp_path)
    plan = {'tasks': [{'task_id': 'imp', 'meta_task_type': 'validation', 'files_touched': ['pkg/mod.py'], 'dependencies': ['orc'], 'verification_command': 'python -m pytest tests/test_mod.py -q'}, {'task_id': 'orc', 'meta_task_type': 'test_authoring', 'mutation_target': 'pkg.mod', 'files_touched': ['tests/test_mod.py'], 'dependencies': ['imp']}]}
    out = _sanitize_impl_verification_commands(plan, repo)
    assert isinstance(out, dict)

def test_purity_in_memory_dict(tmp_path):
    repo = _make_repo(tmp_path)
    plan = {'tasks': [{'task_id': 'imp', 'meta_task_type': 'validation', 'files_touched': ['pkg/mod.py'], 'dependencies': [], 'verification_command': 'python -m pytest tests/test_mod.py -q'}]}
    import copy
    plan_copy = copy.deepcopy(plan)
    out = _sanitize_impl_verification_commands(plan, repo)
    assert plan == plan_copy
    assert out is not plan

def test_vcmd_substring_matching(tmp_path):
    repo = _make_repo(tmp_path)
    plan = {'tasks': [{'task_id': 'imp', 'meta_task_type': 'validation', 'files_touched': ['pkg/mod.py'], 'dependencies': [], 'verification_command': 'python -m pytest tests/test_mod.py_backup -q'}, {'task_id': 'orc', 'meta_task_type': 'test_authoring', 'mutation_target': 'pkg.mod', 'files_touched': ['tests/test_mod.py'], 'dependencies': ['imp']}]}
    out = _sanitize_impl_verification_commands(plan, repo)
    impl_task = [t for t in out['tasks'] if t['task_id'] == 'imp'][0]
    vc = impl_task['verification_command']
    assert 'tests/test_mod.py' not in vc

def test_repo_root_globbing(tmp_path):
    repo = _make_repo(tmp_path)
    tests_dir = repo / 'tests' / 'pkg'
    tests_dir.mkdir(parents=True, exist_ok=True)
    (tests_dir / 'test_mod.py').write_text('# existing test')
    plan = {'tasks': [{'task_id': 'imp', 'meta_task_type': 'validation', 'files_touched': ['pkg/mod.py'], 'dependencies': [], 'verification_command': 'python -m pytest tests/test_mod.py -q'}, {'task_id': 'orc', 'meta_task_type': 'test_authoring', 'mutation_target': 'pkg.mod', 'files_touched': ['tests/test_mod_oracle.py'], 'dependencies': ['imp']}]}
    out = _sanitize_impl_verification_commands(plan, repo)
    impl_task = [t for t in out['tasks'] if t['task_id'] == 'imp'][0]
    vc = impl_task['verification_command']
    assert 'tests/pkg/test_mod.py' in vc
    assert 'pytest' in vc

def test_no_importable_target(tmp_path):
    repo = _make_repo(tmp_path)
    plan = {'tasks': [{'task_id': 'imp', 'meta_task_type': 'validation', 'files_touched': ['pkg/data.txt'], 'dependencies': [], 'verification_command': 'python -m pytest tests/test_mod.py -q'}, {'task_id': 'orc', 'meta_task_type': 'test_authoring', 'mutation_target': 'pkg.mod', 'files_touched': ['tests/test_mod.py'], 'dependencies': ['imp']}]}
    out = _sanitize_impl_verification_commands(plan, repo)
    impl_task = [t for t in out['tasks'] if t['task_id'] == 'imp'][0]
    vc = impl_task['verification_command']
    assert vc == 'python -m pytest tests/test_mod.py -q'

def test_no_importable_target_with_meaningful(tmp_path):
    repo = _make_repo(tmp_path)
    plan = {'tasks': [{'task_id': 'imp', 'meta_task_type': 'validation', 'files_touched': ['pkg/data.txt'], 'dependencies': [], 'verification_command': 'python -m pytest tests/test_mod.py extra_tool -q'}, {'task_id': 'orc', 'meta_task_type': 'test_authoring', 'mutation_target': 'pkg.mod', 'files_touched': ['tests/test_mod.py'], 'dependencies': ['imp']}]}
    out = _sanitize_impl_verification_commands(plan, repo)
    impl_task = [t for t in out['tasks'] if t['task_id'] == 'imp'][0]
    vc = impl_task['verification_command']
    assert 'tests/test_mod.py' not in vc
    assert 'extra_tool' in vc
    assert vc == 'python -m pytest extra_tool -q'