"""Tests for harness/planner/cli.py to verify that normalize_plan is called with contracts.

This test file is a RED oracle that verifies that brief_obj.integration_contracts
is threaded into normalize_plan.
"""
import sys
import types
import json
from pathlib import Path
import pytest
def _get_or_create_module(name):
    mod = sys.modules.get(name)
    if mod is None:
        mod = types.ModuleType(name)
        sys.modules[name] = mod
    return mod

dummy_orch = _get_or_create_module('harness.orchestrator')

dummy_depth = _get_or_create_module('harness.depth_validator')

dummy_val = _get_or_create_module('harness.planner.plan_validator')

dummy_norm = _get_or_create_module('harness.planner.plan_normalizer')
if not hasattr(dummy_norm, 'normalize_plan'):
    dummy_norm.normalize_plan = lambda plan, *args, **kwargs: plan

dummy_recon = _get_or_create_module('harness.planner.reconciliation')
if not hasattr(dummy_recon, 'TrackRecordUnavailable'):
    class TrackRecordUnavailable(Exception):
        pass
    dummy_recon.TrackRecordUnavailable = TrackRecordUnavailable

dummy_paths = _get_or_create_module('harness.paths')
dummy_paths.PROJECT_ROOT = Path('/home/xnihil0zer0/AI-Data/JanusMaskEX')
import harness.planner.cli
from harness.planner.brief_loader import load_brief
WORKING_DIR = '/home/xnihil0zer0/AI-Data/JanusMaskEX'
SECTIONS = '# Title\nTest Title\n\n# Scope\nTest Scope\n\n# Inputs\nTest Inputs\n\n# Non-Goals\nThis test covers integration contracts.\n\n# Deliverables\n- Test deliverable\n'

def write_test_brief(tmp_path, integration_contracts=None, epic=False):
    fm_lines = [f'working_dir: {WORKING_DIR}', f'epic: {str(epic).lower()}']
    if integration_contracts is not None:
        fm_lines.append(f'integration_contracts: {json.dumps(integration_contracts)}')
    frontmatter = '\n'.join(fm_lines)
    content = '---\n' + frontmatter + '\n---\n\n' + SECTIONS
    brief_path = tmp_path / 'brief.md'
    brief_path.write_text(content, encoding='utf-8')
    return brief_path

def monkeypatch_cli_stages(monkeypatch, tmp_path):
    monkeypatch.setattr(harness.planner.cli, 'blind_drafts', lambda brief, config, state_dir: types.SimpleNamespace(claude_draft={'plan_kind': 'leaf', 'tasks': [{'task_id': 't1'}]}, gemini_draft={'plan_kind': 'leaf', 'tasks': [{'task_id': 't1'}]}))
    monkeypatch.setattr(harness.planner.cli, 'diff', lambda c_draft, g_draft: 'dummy_diff')
    monkeypatch.setattr(harness.planner.cli, 'reconciliation', lambda diff_obj, c_draft, g_draft, config, state_dir: types.SimpleNamespace(merged_tasks=[{'task_id': 't1'}]))
    monkeypatch.setattr(harness.planner.cli, 'attribution_stamp', lambda merged_tasks, plan_diff, recon_result, bootstrap: [{'task_id': 't1'}])
    critique_path = tmp_path / 'critique.md'
    critique_path.write_text('', encoding='utf-8')
    monkeypatch.setattr(harness.planner.cli, 'adversarial_review', lambda merged_plan, config, state_dir: critique_path)
    monkeypatch.setattr(harness.planner.cli, 'auto_amend_gate', lambda merged_plan, critique_path, config, state_dir: types.SimpleNamespace(amended_plan={'tasks': [{'task_id': 't1'}]}))
    monkeypatch.setattr(harness.planner.cli, 'persist_plan', lambda *args, **kwargs: None)

def apply_thread_mocks(monkeypatch):
    monkeypatch.setattr(dummy_orch, 'load_config', lambda *args, **kwargs: {})
    monkeypatch.setattr(dummy_depth, 'check_brief_depth', lambda *args, **kwargs: True)
    monkeypatch.setattr(dummy_val, 'validate_plan', lambda *args, **kwargs: [])
    monkeypatch.setattr(dummy_paths, '_target_is_self', lambda x: True)

def test_main_threads_declared_contracts_into_normalize_plan_call(tmp_path, monkeypatch):
    apply_thread_mocks(monkeypatch)
    monkeypatch.chdir(tmp_path)
    declared_contracts = {'t1': {'entrypoints': ['harness/orchestrator.py'], 'symbols': ['some_fn'], 'runtime_oracle': 'drives some_fn'}}
    brief_path = write_test_brief(tmp_path, integration_contracts=declared_contracts)
    real_brief = load_brief(brief_path)
    monkeypatch.setattr(harness.planner.cli, 'load_brief', lambda p: real_brief)
    monkeypatch_cli_stages(monkeypatch, tmp_path)
    captured = {}

    def spy(plan, repo_root=None, contracts='__UNSET__', **kw):
        captured['contracts'] = contracts
        return plan
    monkeypatch.setattr(sys.modules['harness.planner.plan_normalizer'], 'normalize_plan', spy)
    output_plan_path = tmp_path / 'plan.json'
    output_critique_path = tmp_path / 'crit.md'
    argv = [str(brief_path), '--output-plan', str(output_plan_path), '--output-critique', str(output_critique_path)]
    with pytest.raises(SystemExit) as exc_info:
        harness.planner.cli.main(argv)
    assert exc_info.value.code == 0
    assert captured.get('contracts') == real_brief.integration_contracts

def test_omitted_kwarg_caught_by_unset_sentinel(monkeypatch):
    captured = {}

    def spy(plan, repo_root=None, contracts='__UNSET__', **kw):
        captured['contracts'] = contracts
        return plan
    monkeypatch.setattr(sys.modules['harness.planner.plan_normalizer'], 'normalize_plan', spy)
    from harness.planner.plan_normalizer import normalize_plan
    normalize_plan({'tasks': []})
    assert captured['contracts'] == '__UNSET__'

def test_source_contains_contracts_kwarg_adjacent_to_normalize_plan_secondary():
    import harness.planner.cli
    cli_path = Path(harness.planner.cli.__file__)
    content = cli_path.read_text(encoding='utf-8')
    assert 'normalize_plan(' in content
    idx = content.find('normalize_plan(')
    window = content[max(0, idx - 50):min(len(content), idx + 250)]
    assert 'contracts=' in window

def test_spy_returns_plan_unchanged_so_downstream_stages_unaffected():
    captured = {}

    def spy(plan, repo_root=None, contracts='__UNSET__', **kw):
        captured['contracts'] = contracts
        return plan
    dummy_plan = {'tasks': [{'task_id': 't1'}]}
    res = spy(dummy_plan, repo_root=None, contracts=None)
    assert res is dummy_plan

def test_main_exits_zero_on_stubbed_happy_path(tmp_path, monkeypatch):
    apply_thread_mocks(monkeypatch)
    monkeypatch.chdir(tmp_path)
    brief_path = write_test_brief(tmp_path)
    real_brief = load_brief(brief_path)
    monkeypatch.setattr(harness.planner.cli, 'load_brief', lambda p: real_brief)
    monkeypatch_cli_stages(monkeypatch, tmp_path)

    def dummy_normalizer(plan, *args, **kwargs):
        return plan
    monkeypatch.setattr(sys.modules['harness.planner.plan_normalizer'], 'normalize_plan', dummy_normalizer)
    output_plan_path = tmp_path / 'plan.json'
    output_critique_path = tmp_path / 'crit.md'
    argv = [str(brief_path), '--output-plan', str(output_plan_path), '--output-critique', str(output_critique_path)]
    with pytest.raises(SystemExit) as exc_info:
        harness.planner.cli.main(argv)
    assert exc_info.value.code == 0

def test_non_contract_main_behavior_unstubbed_paths_unchanged(tmp_path, monkeypatch):
    apply_thread_mocks(monkeypatch)
    monkeypatch.chdir(tmp_path)
    brief_path = write_test_brief(tmp_path, integration_contracts=None)
    real_brief = load_brief(brief_path)
    assert not real_brief.integration_contracts
    monkeypatch.setattr(harness.planner.cli, 'load_brief', lambda p: real_brief)
    monkeypatch_cli_stages(monkeypatch, tmp_path)
    captured = {}

    def spy(plan, repo_root=None, contracts='__UNSET__', **kw):
        captured['contracts'] = contracts
        return plan
    monkeypatch.setattr(sys.modules['harness.planner.plan_normalizer'], 'normalize_plan', spy)
    output_plan_path = tmp_path / 'plan.json'
    output_critique_path = tmp_path / 'crit.md'
    argv = [str(brief_path), '--output-plan', str(output_plan_path), '--output-critique', str(output_critique_path)]
    with pytest.raises(SystemExit) as exc_info:
        harness.planner.cli.main(argv)
    assert exc_info.value.code == 0
    assert captured['contracts'] in (None, '__UNSET__')