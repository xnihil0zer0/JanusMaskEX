import unittest
from unittest.mock import patch, MagicMock
import pathlib
import tempfile
import json
import time
import os
import subprocess

from harness.autowork_daemon import _escalate_to_autobrief, _retry_blocked_tasks

class TestAutoworkEscalation(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.state_dir = pathlib.Path(self.tmp_dir.name)
        
        # Prepare directory structure inside state_dir
        (self.state_dir / 'tasks' / 'blocked').mkdir(parents=True, exist_ok=True)
        (self.state_dir / 'control' / 'autowork').mkdir(parents=True, exist_ok=True)
        
    def tearDown(self):
        self.tmp_dir.cleanup()

    @patch('harness.autowork_daemon.yaml')
    @patch('subprocess.Popen')
    def test_escalate_to_autobrief_safe_loads_config(self, mock_popen, mock_yaml):
        # Setup config yaml mock
        mock_yaml.safe_load.return_value = {
            'control': {'autobrief_default_agent': 'claude'},
            'agents': {'claude': {'command': 'claude', 'args': []}}
        }
        mock_yaml.safe_load.called = False
        
        # Write mock task JSON
        task_id = 'task_config_load'
        task_path = self.state_dir / 'tasks' / 'blocked' / f'{task_id}.json'
        task_path.write_text(json.dumps({
            'task_id': task_id,
            'files_touched': ['file.py'],
            'objective': 'test objective'
        }))
        
        # We need config.yaml mock file to exist so is_file returns True
        with patch('pathlib.Path.is_file', return_value=True), \
             patch('builtins.open', unittest.mock.mock_open(read_data="agents:\n  claude:\n    command: claude")):
            _escalate_to_autobrief(self.state_dir, task_id, 'synthesis_or_ast_failed')
            
        self.assertTrue(mock_yaml.safe_load.called)

    @patch('subprocess.Popen')
    def test_escalate_to_autobrief_writes_history_record(self, mock_popen):
        task_id = 'task_history'
        task_path = self.state_dir / 'tasks' / 'blocked' / f'{task_id}.json'
        files = ['foo.py', 'bar.py']
        obj = 'heal components'
        task_path.write_text(json.dumps({
            'task_id': task_id,
            'files_touched': files,
            'objective': obj
        }))
        
        # Run escalation
        _escalate_to_autobrief(self.state_dir, task_id, 'smoke_failed')
        
        # Check history record
        history_path = self.state_dir / 'control' / 'autowork' / 'self_healing_history.jsonl'
        self.assertTrue(history_path.is_file())
        
        lines = history_path.read_text(encoding='utf-8').strip().split('\n')
        self.assertEqual(len(lines), 1)
        record = json.loads(lines[0])
        
        self.assertIn('ts', record)
        self.assertEqual(record['task_id'], task_id)
        self.assertEqual(record['files_touched'], files)
        self.assertEqual(record['outcome'], 'smoke_failed')
        self.assertEqual(record['spec_objective'], obj)

    @patch('harness.autowork_daemon.yaml')
    @patch('subprocess.Popen')
    def test_escalate_to_autobrief_resolves_agent_command(self, mock_popen, mock_yaml):
        mock_yaml.safe_load.return_value = {
            'control': {'autobrief_default_agent': 'custom_agent'},
            'agents': {
                'custom_agent': {
                    'command': 'my_agent_cmd_${PROJECT_ROOT}',
                    'args': ['--state-dir=${STATE_DIR}', '--config=${CONFIG_DIR}']
                }
            }
        }
        
        task_id = 'task_resolve'
        task_path = self.state_dir / 'tasks' / 'blocked' / f'{task_id}.json'
        task_path.write_text(json.dumps({
            'task_id': task_id,
            'files_touched': ['xyz.py'],
            'objective': 'do something'
        }))
        
        # Mock file checks to pass
        with patch('pathlib.Path.is_file', return_value=True), \
             patch('builtins.open', unittest.mock.mock_open(read_data="dummy")):
            _escalate_to_autobrief(self.state_dir, task_id, 'embedded_tests_failed')
            
        self.assertTrue(mock_popen.called)
        args, kwargs = mock_popen.call_args
        cmd = args[0]
        
        # Verify placeholders resolved
        from harness.paths import PROJECT_ROOT_STR, CONFIG_DIR_STR
        self.assertIn(PROJECT_ROOT_STR, cmd[0])
        self.assertIn(str(self.state_dir), cmd[1])
        self.assertIn(CONFIG_DIR_STR, cmd[2])

    @patch('subprocess.Popen')
    def test_escalate_to_autobrief_spawns_subprocess(self, mock_popen):
        task_id = 'task_spawn'
        task_path = self.state_dir / 'tasks' / 'blocked' / f'{task_id}.json'
        task_path.write_text(json.dumps({
            'task_id': task_id,
            'files_touched': ['abc.py'],
            'objective': 'heal'
        }))
        
        _escalate_to_autobrief(self.state_dir, task_id, 'narrow_fuzz_failed')
        
        self.assertTrue(mock_popen.called)
        args, kwargs = mock_popen.call_args
        env = kwargs.get('env', {})
        self.assertEqual(env.get('JANUSMASK_MODE'), 'planning')
        self.assertEqual(env.get('JANUSMASK_TASK_ID'), task_id)
        self.assertEqual(env.get('JANUSMASK_STATE_DIR'), str(self.state_dir))

    @patch('harness.autowork_daemon._escalate_to_autobrief')
    def test_retry_blocked_tasks_triggers_escalation(self, mock_escalate):
        # 1. Setup deterministic failure with 1-attempt budget
        task_id = 'task_determ'
        task_path = self.state_dir / 'tasks' / 'blocked' / f'{task_id}.json'
        task_path.write_text(json.dumps({'task_id': task_id, 'files_touched': ['foo.py'], 'priority': 'high'}))
        
        # sidecar attempts = 1
        sidecar_path = self.state_dir / 'tasks' / 'blocked' / f'{task_id}.retry.json'
        sidecar_path.write_text(json.dumps({
            'attempts': 1,
            'ts': time.time(),
            'last_outcome': 'smoke_failed'
        }))
        
        summary = {}
        _retry_blocked_tasks(self.state_dir, summary, max_attempts=3)
        
        mock_escalate.assert_called_once_with(self.state_dir, task_id, 'smoke_failed')
        
        # Verify exhausted marker created
        exhausted_marker = self.state_dir / 'tasks' / 'blocked' / f'{task_id}.exhausted'
        self.assertTrue(exhausted_marker.is_file())

    @patch('harness.autowork_daemon._escalate_to_autobrief')
    def test_retry_blocked_tasks_does_not_double_escalate(self, mock_escalate):
        task_id = 'task_double'
        task_path = self.state_dir / 'tasks' / 'blocked' / f'{task_id}.json'
        task_path.write_text(json.dumps({'task_id': task_id, 'files_touched': ['foo.py'], 'priority': 'high'}))
        
        sidecar_path = self.state_dir / 'tasks' / 'blocked' / f'{task_id}.retry.json'
        sidecar_path.write_text(json.dumps({
            'attempts': 2,
            'ts': time.time(),
            'last_outcome': 'smoke_failed'
        }))
        
        # exhausted marker already exists
        exhausted_marker = self.state_dir / 'tasks' / 'blocked' / f'{task_id}.exhausted'
        exhausted_marker.write_text('1')
        
        summary = {}
        _retry_blocked_tasks(self.state_dir, summary, max_attempts=1)
        
        self.assertFalse(mock_escalate.called)

    @patch('subprocess.Popen')
    def test_daemon_full_escalation_flow(self, mock_popen):
        task_id = 'task_full'
        task_path = self.state_dir / 'tasks' / 'blocked' / f'{task_id}.json'
        task_path.write_text(json.dumps({'task_id': task_id, 'files_touched': ['foo.py'], 'priority': 'high'}))
        
        sidecar_path = self.state_dir / 'tasks' / 'blocked' / f'{task_id}.retry.json'
        sidecar_path.write_text(json.dumps({
            'attempts': 3,
            'ts': time.time(),
            'last_outcome': 'embedded_tests_failed'
        }))
        
        summary = {}
        _retry_blocked_tasks(self.state_dir, summary, max_attempts=3)
        
        # Check Popen was called
        self.assertTrue(mock_popen.called)
        
        # Check history record
        history_path = self.state_dir / 'control' / 'autowork' / 'self_healing_history.jsonl'
        self.assertTrue(history_path.is_file())
        
        lines = history_path.read_text(encoding='utf-8').strip().split('\n')
        record = json.loads(lines[0])
        self.assertEqual(record['task_id'], task_id)
        self.assertEqual(record['outcome'], 'embedded_tests_failed')
