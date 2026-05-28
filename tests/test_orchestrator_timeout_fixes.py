from __future__ import annotations
import json
import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
from harness.orchestrator_worker import main

@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    sd = tmp_path / 'state'
    (sd / 'tasks').mkdir(parents=True)
    (sd / 'sessions').mkdir(parents=True)
    (sd / 'output').mkdir(parents=True)
    return sd

def test_double_timeout_exits_with_status_2(state_dir: Path) -> None:
    task_id = 'test_double_timeout'
    task_data = {'task_id': task_id, 'depth': 0, 'files_touched': [], 'dependencies': []}
    task_file = state_dir / 'tasks' / f'{task_id}.json'
    task_file.write_text(json.dumps(task_data), encoding='utf-8')
    argv = ['--state-dir', str(state_dir), '--task-id', task_id]
    with patch('sys.argv', [''] + argv), patch('harness.orchestrator.load_config') as mock_load_config, patch('harness.orchestrator.run_both_agents') as mock_run_both, patch('harness.orchestrator_worker._precompute_baseline_test_results'), patch('harness.orchestrator._clear_stale_submissions'):
        mock_load_config.return_value = {'synthesis': {'max_ast_retries': 3, 'use_retry_module': False, 'active_agents': ['claude', 'gemini']}}
        mock_run_both.return_value = (None, None)
        exit_code = main()
        assert exit_code == 2

def test_double_timeout_exits_with_status_2_use_retry_module(state_dir: Path) -> None:
    task_id = 'test_double_timeout_retry_mod'
    task_data = {'task_id': task_id, 'depth': 0, 'files_touched': [], 'dependencies': []}
    task_file = state_dir / 'tasks' / f'{task_id}.json'
    task_file.write_text(json.dumps(task_data), encoding='utf-8')
    argv = ['--state-dir', str(state_dir), '--task-id', task_id]
    with patch('sys.argv', [''] + argv), patch('harness.orchestrator.load_config') as mock_load_config, patch('harness.ast_retry.synthesize_with_retries') as mock_synth, patch('harness.orchestrator_worker._precompute_baseline_test_results'), patch('harness.orchestrator._clear_stale_submissions'):
        mock_load_config.return_value = {'synthesis': {'max_ast_retries': 3, 'use_retry_module': True, 'active_agents': ['claude', 'gemini']}}
        mock_synth.return_value = (False, None, [])
        exit_code = main()
        assert exit_code == 2

def test_retry_budget_exhaustion_exits_with_status_2(state_dir: Path) -> None:
    task_id = 'test_budget_exhaustion'
    task_data = {'task_id': task_id, 'depth': 0, 'files_touched': [], 'dependencies': []}
    task_file = state_dir / 'tasks' / f'{task_id}.json'
    task_file.write_text(json.dumps(task_data), encoding='utf-8')
    argv = ['--state-dir', str(state_dir), '--task-id', task_id]
    with patch('sys.argv', [''] + argv), patch('harness.orchestrator.load_config') as mock_load_config, patch('harness.orchestrator.run_both_agents') as mock_run_both, patch('harness.orchestrator_worker._precompute_baseline_test_results'), patch('harness.orchestrator._clear_stale_submissions'), patch('time.monotonic') as mock_mono:
        mock_load_config.return_value = {'synthesis': {'max_ast_retries': 3, 'use_retry_module': False, 'active_agents': ['claude', 'gemini']}}
        mock_mono.side_effect = [0.0, 400.0, 400.0]
        mock_run_both.return_value = (None, 'code')
        exit_code = main()
        assert exit_code == 2

def test_retry_budget_exhaustion_exits_with_status_2_use_retry_module(state_dir: Path) -> None:
    task_id = 'test_budget_exhaustion_retry_mod'
    task_data = {'task_id': task_id, 'depth': 0, 'files_touched': [], 'dependencies': []}
    task_file = state_dir / 'tasks' / f'{task_id}.json'
    task_file.write_text(json.dumps(task_data), encoding='utf-8')
    argv = ['--state-dir', str(state_dir), '--task-id', task_id]
    with patch('sys.argv', [''] + argv), patch('harness.orchestrator.load_config') as mock_load_config, patch('harness.orchestrator_worker._precompute_baseline_test_results'), patch('harness.orchestrator._clear_stale_submissions'), patch('harness.orchestrator.run_agent_phase') as mock_run, patch('time.monotonic') as mock_mono:
        mock_load_config.return_value = {'synthesis': {'max_ast_retries': 3, 'use_retry_module': True, 'active_agents': ['claude']}}
        mock_mono.side_effect = [0.0, 0.0, 0.0, 400.0, 400.0, 400.0]
        mock_run.return_value = None
        with pytest.raises(SystemExit) as excinfo:
            main()
        assert excinfo.value.code == 2