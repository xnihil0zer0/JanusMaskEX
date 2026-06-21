"""Tests for agent selection fallback retry logic."""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path
import pytest
import harness.orchestrator as orch
import harness.orchestrator_worker as ow
ORIGINAL = "def target():\n    return 'pristine'\n"

def _git(repo, *args):
    subprocess.run(['git', *args], cwd=str(repo), check=True, capture_output=True, text=True)

@pytest.fixture
def repo_env(tmp_path, monkeypatch):
    repo = tmp_path / 'repo'
    (repo / 'pkg').mkdir(parents=True)
    target = repo / 'pkg' / 'm.py'
    target.write_text(ORIGINAL)
    _git(repo, 'init', '-q')
    _git(repo, 'config', 'user.email', 't@t')
    _git(repo, 'config', 'user.name', 't')
    _git(repo, 'add', '-A')
    _git(repo, 'commit', '-q', '-m', 'init')
    state_dir = repo / 'state'
    (state_dir / 'tasks').mkdir(parents=True)
    (state_dir / 'sessions').mkdir(parents=True)
    task_id = 'C3_ROLLBACK'
    task = {'task_id': task_id, 'specification': 'x', 'files_touched': ['pkg/m.py'], 'verification_command': 'true', 'meta_task_type': 'harness_self_fix'}
    (state_dir / 'tasks' / f'{task_id}.json').write_text(json.dumps(task))
    cfg = {'synthesis': {'timeout_seconds': 600, 'max_ast_retries': 3, 'antigravity_mode': False, 'active_agents': ['claude', 'gemini']}, 'cross_examination': {'max_rounds': 1}, 'decomposition': {'max_depth': 3}}
    monkeypatch.setattr(orch, 'load_config', lambda *a, **k: cfg)
    monkeypatch.setattr(ow, '_compute_timeout_budgets', lambda cfg: (3600.0, 600.0))
    monkeypatch.setattr(ow, '_precompute_baseline_test_results', lambda *a, **k: None)
    monkeypatch.setenv('JANUSMASK_AGENT_WORKROOT', str(tmp_path / 'wr'))
    monkeypatch.setattr(sys, 'argv', ['ow', '--state-dir', str(state_dir), '--task-id', task_id])
    return {'repo': repo, 'target': target, 'state_dir': state_dir, 'task_id': task_id}

def test_e2e_works_proof_fallback_commits_gemini_on_claude_verify_failure(repo_env, monkeypatch):
    repo = repo_env['repo']
    state_dir = repo_env['state_dir']
    task_id = repo_env['task_id']
    task_file = state_dir / 'tasks' / f'{task_id}.json'
    task = json.loads(task_file.read_text())
    task['verification_command'] = 'grep -q CORRECT pkg/m.py'
    task_file.write_text(json.dumps(task))
    monkeypatch.setattr(orch, 'run_both_agents', lambda *a, **k: ("def target():\n    return 'WRONG'\n", "def target():\n    return 'CORRECT'\n"))
    monkeypatch.setattr(orch, '_validate_submission', lambda *a, **k: (True, []))
    monkeypatch.setattr(orch, '_try_auto_repair', lambda *a, **k: None)
    monkeypatch.setattr(ow, '_detect_and_append_untracked_tests', lambda *a, **k: None)
    rc = ow.main()
    assert rc == 0
    assert 'CORRECT' in (repo / 'pkg' / 'm.py').read_text()

def test_unit_save_final_output_writes_fallback_sidecar(tmp_path):
    state_dir = tmp_path / 'state'
    task_id = 'test_task'
    code = 'def primary(): pass\n'
    fallback = 'def fallback(): pass\n'
    orch._save_final_output(state_dir, task_id, code, fallback_code=fallback)
    fb_file = state_dir / 'output' / f'{task_id}.fallback.py'
    assert fb_file.exists()
    assert fb_file.read_text() == fallback

def test_unit_save_final_output_omitted_fallback_writes_no_sidecar(tmp_path):
    state_dir = tmp_path / 'state'
    task_id = 'test_task'
    code = 'def primary(): pass\n'
    orch._save_final_output(state_dir, task_id, code)
    fb_file = state_dir / 'output' / f'{task_id}.fallback.py'
    assert not fb_file.exists()

def test_unit_promote_returns_false_when_no_fallback(tmp_path):
    state_dir = tmp_path / 'state'
    task_id = 'test_task'
    result = orch._promote_fallback_candidate(state_dir, task_id)
    assert isinstance(result, bool)
    assert result is False

def test_unit_promote_fallback_swaps_into_primary(tmp_path):
    state_dir = tmp_path / 'state'
    task_id = 'test_task'
    out_dir = state_dir / 'output'
    out_dir.mkdir(parents=True)
    pri_file = out_dir / f'{task_id}.py'
    fb_file = out_dir / f'{task_id}.fallback.py'
    fb_patches = out_dir / f'{task_id}.fallback.patches.json'
    pri_file.write_text('def primary(): pass\n')
    fb_file.write_text('def fallback(): pass\n')
    fb_patches.write_text('[]\n')
    result = orch._promote_fallback_candidate(state_dir, task_id)
    assert isinstance(result, bool)
    assert result is True
    assert pri_file.read_text() == 'def fallback(): pass\n'
    assert (out_dir / f'{task_id}.patches.json').exists()
    assert not fb_file.exists()
    assert not fb_patches.exists()

def test_unit_promote_identical_fallback_deletes_fallback_and_returns_false(tmp_path):
    state_dir = tmp_path / 'state'
    task_id = 'test_task'
    out_dir = state_dir / 'output'
    out_dir.mkdir(parents=True)
    pri_file = out_dir / f'{task_id}.py'
    fb_file = out_dir / f'{task_id}.fallback.py'
    fb_patches = out_dir / f'{task_id}.fallback.patches.json'
    code = 'def primary(): pass\n'
    pri_file.write_text(code)
    fb_file.write_text(code)
    fb_patches.write_text('[]\n')
    result = orch._promote_fallback_candidate(state_dir, task_id)
    assert isinstance(result, bool)
    assert result is False
    assert pri_file.read_text() == code
    assert not fb_file.exists()
    assert not fb_patches.exists()