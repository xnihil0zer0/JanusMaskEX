"""Tests for planner plan_normalizer to keep required oracle in normalize_plan.

Non-goals: integration testing is out of scope.
"""
from pathlib import Path
import pytest
from harness.planner.plan_normalizer import normalize_plan

def _impl(mod_relpath, vcmd):
    return {'task_id': 'IMPL_1', 'title': 'edit existing module', 'meta_task_type': 'io_adapter', 'priority': 'high', 'dependencies': [], 'files_touched': [mod_relpath], 'verification_command': vcmd}

def _oracle(target):
    return {'task_id': 'ORACLE_1', 'title': 'redundant oracle sibling', 'meta_task_type': 'test_authoring', 'priority': 'high', 'dependencies': [], 'mutation_target': target, 'files_touched': ['tests/pkg/test_mod_new.py'], 'verification_command': 'python -m pytest tests/pkg/test_mod_new.py -q'}

def setup_synthetic_repo(tmp_path):
    (tmp_path / 'pkg').mkdir(exist_ok=True)
    (tmp_path / 'pkg' / 'mod.py').write_text('def f():\n    return 1\n')
    (tmp_path / 'tests' / 'pkg').mkdir(parents=True, exist_ok=True)
    (tmp_path / 'tests' / 'pkg' / 'test_mod.py').write_text('from pkg.mod import f\n\ndef test_f():\n    assert f() == 1\n')

def test_required_oracle_is_kept(tmp_path):
    setup_synthetic_repo(tmp_path)
    plan = {'plan_kind': 'implementation', 'required_task_ids': ['ORACLE_1'], 'tasks': [_impl('pkg/mod.py', 'python -m pytest tests/pkg/test_mod.py -q'), _oracle('pkg.mod')]}
    out = normalize_plan(plan, repo_root=tmp_path, required_task_ids=['ORACLE_1'])
    ids = {t['task_id'] for t in out['tasks'] if isinstance(t, dict)}
    assert 'ORACLE_1' in ids
    assert 'IMPL_1' in ids

def test_non_required_oracle_is_dropped(tmp_path):
    setup_synthetic_repo(tmp_path)
    plan = {'plan_kind': 'implementation', 'required_task_ids': ['IMPL_1'], 'tasks': [_impl('pkg/mod.py', 'python -m pytest tests/pkg/test_mod.py -q'), _oracle('pkg.mod')]}
    out = normalize_plan(plan, repo_root=tmp_path)
    ids = {t['task_id'] for t in out['tasks'] if isinstance(t, dict)}
    assert 'ORACLE_1' not in ids
    assert 'IMPL_1' in ids

def test_required_impl_unaffected(tmp_path):
    setup_synthetic_repo(tmp_path)
    for required in [['IMPL_1', 'ORACLE_1'], []]:
        plan = {'plan_kind': 'implementation', 'required_task_ids': required, 'tasks': [_impl('pkg/mod.py', 'python -m pytest tests/pkg/test_mod.py -q'), _oracle('pkg.mod')]}
        out = normalize_plan(plan, repo_root=tmp_path)
        ids = {t['task_id'] for t in out['tasks'] if isinstance(t, dict)}
        assert 'IMPL_1' in ids

def test_determinism_idempotence(tmp_path):
    setup_synthetic_repo(tmp_path)
    plan = {'plan_kind': 'implementation', 'required_task_ids': ['ORACLE_1'], 'tasks': [_impl('pkg/mod.py', 'python -m pytest tests/pkg/test_mod.py -q'), _oracle('pkg.mod')]}
    out1 = normalize_plan(plan, repo_root=tmp_path)
    out2 = normalize_plan(out1, repo_root=tmp_path)
    ids1 = [t['task_id'] for t in out1['tasks'] if isinstance(t, dict)]
    ids2 = [t['task_id'] for t in out2['tasks'] if isinstance(t, dict)]
    assert ids1 == ids2

def test_required_oracle_is_kept_without_kwarg(tmp_path):
    setup_synthetic_repo(tmp_path)
    plan = {'plan_kind': 'implementation', 'required_task_ids': ['ORACLE_1'], 'tasks': [_impl('pkg/mod.py', 'python -m pytest tests/pkg/test_mod.py -q'), _oracle('pkg.mod')]}
    out = normalize_plan(plan, repo_root=tmp_path)
    ids = {t['task_id'] for t in out['tasks'] if isinstance(t, dict)}
    assert 'ORACLE_1' in ids
    assert 'IMPL_1' in ids

def test_required_oracle_is_kept_with_explicit_kwarg(tmp_path):
    setup_synthetic_repo(tmp_path)
    plan = {'plan_kind': 'implementation', 'required_task_ids': [], 'tasks': [_impl('pkg/mod.py', 'python -m pytest tests/pkg/test_mod.py -q'), _oracle('pkg.mod')]}
    out = normalize_plan(plan, repo_root=tmp_path, required_task_ids=['ORACLE_1'])
    ids = {t['task_id'] for t in out['tasks'] if isinstance(t, dict)}
    assert 'ORACLE_1' in ids
    assert 'IMPL_1' in ids

def test_required_oracle_empty_is_dropped(tmp_path):
    setup_synthetic_repo(tmp_path)
    plan = {'plan_kind': 'implementation', 'required_task_ids': [], 'tasks': [_impl('pkg/mod.py', 'python -m pytest tests/pkg/test_mod.py -q'), _oracle('pkg.mod')]}
    out = normalize_plan(plan, repo_root=tmp_path)
    ids = {t['task_id'] for t in out['tasks'] if isinstance(t, dict)}
    assert 'ORACLE_1' not in ids

def test_required_oracle_none_is_dropped(tmp_path):
    setup_synthetic_repo(tmp_path)
    plan = {'plan_kind': 'implementation', 'required_task_ids': None, 'tasks': [_impl('pkg/mod.py', 'python -m pytest tests/pkg/test_mod.py -q'), _oracle('pkg.mod')]}
    out = normalize_plan(plan, repo_root=tmp_path)
    ids = {t['task_id'] for t in out['tasks'] if isinstance(t, dict)}
    assert 'ORACLE_1' not in ids

def test_required_oracle_invalid_types_are_dropped(tmp_path):
    setup_synthetic_repo(tmp_path)
    plan = {'plan_kind': 'implementation', 'required_task_ids': [123, None, '', {}], 'tasks': [_impl('pkg/mod.py', 'python -m pytest tests/pkg/test_mod.py -q'), _oracle('pkg.mod')]}
    out = normalize_plan(plan, repo_root=tmp_path)
    ids = {t['task_id'] for t in out['tasks'] if isinstance(t, dict)}
    assert 'ORACLE_1' not in ids

def test_required_oracle_comma_separated_is_kept(tmp_path):
    setup_synthetic_repo(tmp_path)
    plan = {'plan_kind': 'implementation', 'required_task_ids': 'ORACLE_1, ORACLE_2', 'tasks': [_impl('pkg/mod.py', 'python -m pytest tests/pkg/test_mod.py -q'), _oracle('pkg.mod')]}
    out = normalize_plan(plan, repo_root=tmp_path)
    ids = {t['task_id'] for t in out['tasks'] if isinstance(t, dict)}
    assert 'ORACLE_1' in ids

def test_required_oracle_nonexistent_ids_ignored(tmp_path):
    setup_synthetic_repo(tmp_path)
    plan = {'plan_kind': 'implementation', 'required_task_ids': ['NONEXISTENT_1', 'NONEXISTENT_2'], 'tasks': [_impl('pkg/mod.py', 'python -m pytest tests/pkg/test_mod.py -q'), _oracle('pkg.mod')]}
    out = normalize_plan(plan, repo_root=tmp_path)
    ids = {t['task_id'] for t in out['tasks'] if isinstance(t, dict)}
    assert 'ORACLE_1' not in ids
    assert 'IMPL_1' in ids

def test_required_oracle_non_oracle_id_ignored(tmp_path):
    setup_synthetic_repo(tmp_path)
    plan = {'plan_kind': 'implementation', 'required_task_ids': ['IMPL_1'], 'tasks': [_impl('pkg/mod.py', 'python -m pytest tests/pkg/test_mod.py -q'), _oracle('pkg.mod')]}
    out = normalize_plan(plan, repo_root=tmp_path)
    ids = {t['task_id'] for t in out['tasks'] if isinstance(t, dict)}
    assert 'ORACLE_1' not in ids
    assert 'IMPL_1' in ids

def test_cli_source_asserts_normalize_plan_threads_required_task_ids():
    cli_path = Path(__file__).parent.parent.parent / 'harness' / 'planner' / 'cli.py'
    if not cli_path.exists():
        import sys
        import types
        if 'harness.orchestrator' not in sys.modules:
            dummy_orch = types.ModuleType('harness.orchestrator')
            dummy_orch.load_config = lambda p: {}
            sys.modules['harness.orchestrator'] = dummy_orch
        if 'harness.depth_validator' not in sys.modules:
            dummy_depth = types.ModuleType('harness.depth_validator')
            dummy_depth.check_brief_depth = lambda *args, **kwargs: True
            sys.modules['harness.depth_validator'] = dummy_depth
        if 'harness.planner.plan_validator' not in sys.modules:
            dummy_val = types.ModuleType('harness.planner.plan_validator')
            dummy_val.validate_plan = lambda *args, **kwargs: []
            sys.modules['harness.planner.plan_validator'] = dummy_val
        if 'harness.planner.plan_normalizer' not in sys.modules:
            dummy_norm = types.ModuleType('harness.planner.plan_normalizer')
            dummy_norm.normalize_plan = lambda plan, *args, **kwargs: plan
            sys.modules['harness.planner.plan_normalizer'] = dummy_norm
        if 'harness.planner.reconciliation' not in sys.modules:
            dummy_recon = types.ModuleType('harness.planner.reconciliation')

            class TrackRecordUnavailable(Exception):
                pass
            dummy_recon.TrackRecordUnavailable = TrackRecordUnavailable
            sys.modules['harness.planner.reconciliation'] = dummy_recon
        if 'harness.paths' not in sys.modules:
            dummy_paths = types.ModuleType('harness.paths')
            dummy_paths._target_is_self = lambda x: True
            dummy_paths.PROJECT_ROOT = Path('/home/xnihil0zer0/AI-Data/JanusMaskEX')
            sys.modules['harness.paths'] = dummy_paths
        import harness.planner.cli
        cli_path = Path(harness.planner.cli.__file__)
    content = cli_path.read_text(encoding='utf-8')
    assert 'normalize_plan(' in content
    idx = content.find('normalize_plan(')
    window = content[max(0, idx - 50):min(len(content), idx + 250)]
    assert 'required_task_ids=' in window