from __future__ import annotations
import io
import json
import os
import pathlib
import sys
import tempfile
import time
from unittest.mock import patch
from unittest.mock import MagicMock
from unittest.mock import mock_open
import pytest
import yaml
from harness.autowork_daemon import _escalate_to_autobrief
from harness.autowork_daemon import _retry_blocked_tasks
import harness.hooks.claude.user_prompt_submit as claude_user_prompt_submit
import harness.hooks.gemini.user_prompt_submit as gemini_user_prompt_submit
from harness.hooks import _paths
from harness.hooks import _ledger

@pytest.fixture
def temp_state_dir(tmp_path):
    state = tmp_path / 'state'
    state.mkdir()
    (state / 'tasks' / 'blocked').mkdir(parents=True, exist_ok=True)
    (state / 'control' / 'autowork').mkdir(parents=True, exist_ok=True)
    return state

@pytest.fixture
def mock_popen():
    with patch('subprocess.Popen') as mock:
        yield mock

def test_escalate_to_autobrief_safe_loads_config(temp_state_dir, mock_popen):
    task_id = 'task_config_load'
    task_path = temp_state_dir / 'tasks' / 'blocked' / f'{task_id}.json'
    task_path.write_text(json.dumps({'task_id': task_id, 'files_touched': ['file.py'], 'objective': 'test objective'}), encoding='utf-8')
    config_data = {'control': {'autobrief_default_agent': 'claude'}, 'agents': {'claude': {'command': 'claude', 'args': []}}}
    orig_is_file = pathlib.Path.is_file

    def mock_is_file(self):
        if self.name == 'config.yaml':
            return True
        return orig_is_file(self)
    with patch('pathlib.Path.is_file', mock_is_file), patch('builtins.open', mock_open(read_data=yaml.dump(config_data))):
        _escalate_to_autobrief(temp_state_dir, task_id, 'synthesis_or_ast_failed')
    assert mock_popen.called

def test_escalate_to_autobrief_writes_history_record(temp_state_dir, mock_popen):
    task_id = 'task_history'
    task_path = temp_state_dir / 'tasks' / 'blocked' / f'{task_id}.json'
    files = ['foo.py', 'bar.py']
    obj = 'heal components'
    task_path.write_text(json.dumps({'task_id': task_id, 'files_touched': files, 'objective': obj}), encoding='utf-8')
    _escalate_to_autobrief(temp_state_dir, task_id, 'smoke_failed')
    history_path = temp_state_dir / 'control' / 'autowork' / 'self_healing_history.jsonl'
    assert history_path.is_file()
    lines = history_path.read_text(encoding='utf-8').strip().split('\n')
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert 'ts' in record
    assert record['task_id'] == task_id
    assert record['files_touched'] == files
    assert record['outcome'] == 'smoke_failed'
    assert record['spec_objective'] == obj

def test_escalation_history_logging(temp_state_dir, mock_popen):
    test_escalate_to_autobrief_writes_history_record(temp_state_dir, mock_popen)

def test_escalate_to_autobrief_resolves_agent_command(temp_state_dir, mock_popen):
    config_data = {'control': {'autobrief_default_agent': 'custom_agent'}, 'agents': {'custom_agent': {'command': 'my_agent_cmd_${PROJECT_ROOT}', 'args': ['--state-dir=${STATE_DIR}', '--config=${CONFIG_DIR}']}}}
    task_id = 'task_resolve'
    task_path = temp_state_dir / 'tasks' / 'blocked' / f'{task_id}.json'
    task_path.write_text(json.dumps({'task_id': task_id, 'files_touched': ['xyz.py'], 'objective': 'do something'}), encoding='utf-8')
    orig_is_file = pathlib.Path.is_file

    def mock_is_file(self):
        if self.name == 'config.yaml':
            return True
        return orig_is_file(self)
    with patch('pathlib.Path.is_file', mock_is_file), patch('builtins.open', mock_open(read_data=yaml.dump(config_data))):
        _escalate_to_autobrief(temp_state_dir, task_id, 'embedded_tests_failed')
    assert mock_popen.called
    args, kwargs = mock_popen.call_args
    cmd = args[0]
    from harness.paths import PROJECT_ROOT_STR, CONFIG_DIR_STR
    assert PROJECT_ROOT_STR in cmd[0]
    assert str(temp_state_dir) in cmd[1]
    assert CONFIG_DIR_STR in cmd[2]

def test_escalate_to_autobrief_spawns_subprocess(temp_state_dir, mock_popen):
    task_id = 'task_spawn'
    task_path = temp_state_dir / 'tasks' / 'blocked' / f'{task_id}.json'
    task_path.write_text(json.dumps({'task_id': task_id, 'files_touched': ['abc.py'], 'objective': 'heal'}), encoding='utf-8')
    _escalate_to_autobrief(temp_state_dir, task_id, 'narrow_fuzz_failed')
    assert mock_popen.called
    args, kwargs = mock_popen.call_args
    env = kwargs.get('env', {})
    assert env.get('JANUSMASK_MODE') == 'planning'
    assert env.get('JANUSMASK_TASK_ID') == task_id
    assert env.get('JANUSMASK_STATE_DIR') == str(temp_state_dir)

def test_escalate_to_autobrief_missing_task_json(temp_state_dir, mock_popen):
    task_id = 'task_missing'
    fuzz_dir = temp_state_dir.parent / 'logs' / 'fuzz_results'
    fuzz_dir.mkdir(parents=True, exist_ok=True)
    (fuzz_dir / f'{task_id}.json').write_text(json.dumps({'failures': [{'err': 'x'}]}), encoding='utf-8')
    task_json_path = temp_state_dir / 'tasks' / 'blocked' / f'{task_id}.json'
    _orig_exists = pathlib.Path.exists

    def _exists(self):
        if self == task_json_path:
            return True
        return _orig_exists(self)
    with patch('pathlib.Path.exists', _exists):
        _escalate_to_autobrief(temp_state_dir, task_id, 'smoke_failed')
    history_path = temp_state_dir / 'control' / 'autowork' / 'self_healing_history.jsonl'
    assert history_path.is_file()
    lines = history_path.read_text(encoding='utf-8').strip().split('\n')
    record = json.loads(lines[0])
    assert record['task_id'] == task_id
    assert record['files_touched'] == []
    assert record['spec_objective'] == ''

def test_escalate_to_autobrief_corrupt_task_json(temp_state_dir, mock_popen):
    task_id = 'task_corrupt'
    task_path = temp_state_dir / 'tasks' / 'blocked' / f'{task_id}.json'
    task_path.write_text('corrupted json {', encoding='utf-8')
    fuzz_dir = temp_state_dir.parent / 'logs' / 'fuzz_results'
    fuzz_dir.mkdir(parents=True, exist_ok=True)
    (fuzz_dir / f'{task_id}.json').write_text(json.dumps({'failures': [{'err': 'x'}]}), encoding='utf-8')
    _escalate_to_autobrief(temp_state_dir, task_id, 'smoke_failed')
    history_path = temp_state_dir / 'control' / 'autowork' / 'self_healing_history.jsonl'
    assert history_path.is_file()
    lines = history_path.read_text(encoding='utf-8').strip().split('\n')
    record = json.loads(lines[0])
    assert record['task_id'] == task_id
    assert record['files_touched'] == []
    assert record['spec_objective'] == ''

@pytest.fixture
def synth_workdir_claude(tmp_path, monkeypatch):
    state = tmp_path / 'state'
    state.mkdir()
    workdir = state / 'workdirs' / 'claude' / 'sessClaude'
    (workdir / 'inbox').mkdir(parents=True)
    task_body = {'task_id': 'T', 'title': 'do it', 'files_touched': ['a.py', 'b.py']}
    (workdir / 'inbox' / 'task.json').write_text(json.dumps(task_body), encoding='utf-8')
    (state / 'STATE.json').write_text(json.dumps({'round': 2, 'phase': 'synthesis', 'task_id': 'T'}), encoding='utf-8')
    monkeypatch.setenv('JANUSMASK_STATE_DIR', str(state))
    monkeypatch.setenv('JANUSMASK_WORK_DIR', str(workdir))
    monkeypatch.setenv('JANUSMASK_AGENT', 'claude')
    monkeypatch.setenv('JANUSMASK_MODE', 'synthesis')
    monkeypatch.setenv('JANUSMASK_ROUND', '2')
    return {'state': state, 'workdir': workdir, 'session_id': 'sessClaude', 'task': task_body}

def test_prompt_hook_claude_injects_warning_context(synth_workdir_claude):
    state_dir = synth_workdir_claude['state']
    autowork_dir = state_dir / 'control' / 'autowork'
    autowork_dir.mkdir(parents=True, exist_ok=True)
    history_file = autowork_dir / 'self_healing_history.jsonl'
    record1 = {'ts': 1600000000.0, 'task_id': 'prev_task', 'outcome': 'success', 'files_touched': ['a.py']}
    history_file.write_text(json.dumps(record1) + '\n', encoding='utf-8')
    stdin = io.StringIO(json.dumps({'session_id': synth_workdir_claude['session_id']}))
    stdout = io.StringIO()
    with patch('harness.hooks._ledger.has_verb', return_value=False), patch('harness.hooks._paths.state_dir', return_value=state_dir):
        rc = claude_user_prompt_submit.main(stdin, stdout)
    assert rc == 0
    out = json.loads(stdout.getvalue())
    assert out['decision'] == 'allow'
    msg = out['hookSpecificOutput']['additionalContext']
    assert '--- RECENT SELF-HEALING HISTORY FOR RELATED COMPONENTS ---' in msg
    assert 'prev_task' in msg
    assert 'success' in msg

def test_prompt_hook_warning_context(synth_workdir_claude):
    test_prompt_hook_claude_injects_warning_context(synth_workdir_claude)

def test_prompt_hook_claude_no_overlap(synth_workdir_claude):
    state_dir = synth_workdir_claude['state']
    autowork_dir = state_dir / 'control' / 'autowork'
    autowork_dir.mkdir(parents=True, exist_ok=True)
    history_file = autowork_dir / 'self_healing_history.jsonl'
    record1 = {'ts': 1600000000.0, 'task_id': 'prev_task', 'outcome': 'success', 'files_touched': ['c.py']}
    history_file.write_text(json.dumps(record1) + '\n', encoding='utf-8')
    stdin = io.StringIO(json.dumps({'session_id': synth_workdir_claude['session_id']}))
    stdout = io.StringIO()
    with patch('harness.hooks._ledger.has_verb', return_value=False), patch('harness.hooks._paths.state_dir', return_value=state_dir):
        rc = claude_user_prompt_submit.main(stdin, stdout)
    assert rc == 0
    out = json.loads(stdout.getvalue())
    assert out['decision'] == 'allow'
    msg = out['hookSpecificOutput']['additionalContext']
    assert '--- RECENT SELF-HEALING HISTORY FOR RELATED COMPONENTS ---' not in msg

@pytest.fixture
def synth_workdir_gemini(tmp_path, monkeypatch):
    state = tmp_path / 'state'
    state.mkdir()
    workdir = state / 'workdirs' / 'gemini' / 'sessGemini'
    (workdir / 'inbox').mkdir(parents=True)
    task_body = {'task_id': 'T', 'title': 'do it', 'files_touched': ['a.py', 'b.py']}
    (workdir / 'inbox' / 'task.json').write_text(json.dumps(task_body), encoding='utf-8')
    (state / 'STATE.json').write_text(json.dumps({'round': 2, 'phase': 'synthesis', 'task_id': 'T'}), encoding='utf-8')
    monkeypatch.setenv('JANUSMASK_STATE_DIR', str(state))
    monkeypatch.setenv('JANUSMASK_WORK_DIR', str(workdir))
    monkeypatch.setenv('JANUSMASK_AGENT', 'gemini')
    monkeypatch.setenv('JANUSMASK_MODE', 'synthesis')
    monkeypatch.setenv('JANUSMASK_ROUND', '2')
    return {'state': state, 'workdir': workdir, 'session_id': 'sessGemini', 'task': task_body}

def test_prompt_hook_gemini_injects_warning_context(synth_workdir_gemini):
    state_dir = synth_workdir_gemini['state']
    autowork_dir = state_dir / 'control' / 'autowork'
    autowork_dir.mkdir(parents=True, exist_ok=True)
    history_file = autowork_dir / 'self_healing_history.jsonl'
    record1 = {'ts': 1600000000.0, 'task_id': 'prev_task', 'outcome': 'success', 'files_touched': ['a.py']}
    history_file.write_text(json.dumps(record1) + '\n', encoding='utf-8')
    stdin = io.StringIO(json.dumps({'session_id': synth_workdir_gemini['session_id']}))
    stdout = io.StringIO()
    with patch('harness.hooks._ledger.has_verb', return_value=False), patch('harness.hooks._paths.state_dir', return_value=state_dir):
        rc = gemini_user_prompt_submit.main(stdin, stdout)
    assert rc == 0
    out = json.loads(stdout.getvalue())
    assert out['decision'] == 'allow'
    msg = out['systemMessage']
    assert '--- RECENT SELF-HEALING HISTORY FOR RELATED COMPONENTS ---' in msg
    assert 'prev_task' in msg
    assert 'success' in msg

def test_prompt_hook_gemini_no_overlap(synth_workdir_gemini):
    state_dir = synth_workdir_gemini['state']
    autowork_dir = state_dir / 'control' / 'autowork'
    autowork_dir.mkdir(parents=True, exist_ok=True)
    history_file = autowork_dir / 'self_healing_history.jsonl'
    record1 = {'ts': 1600000000.0, 'task_id': 'prev_task', 'outcome': 'success', 'files_touched': ['c.py']}
    history_file.write_text(json.dumps(record1) + '\n', encoding='utf-8')
    stdin = io.StringIO(json.dumps({'session_id': synth_workdir_gemini['session_id']}))
    stdout = io.StringIO()
    with patch('harness.hooks._ledger.has_verb', return_value=False), patch('harness.hooks._paths.state_dir', return_value=state_dir):
        rc = gemini_user_prompt_submit.main(stdin, stdout)
    assert rc == 0
    out = json.loads(stdout.getvalue())
    assert out['decision'] == 'allow'
    msg = out['systemMessage']
    assert '--- RECENT SELF-HEALING HISTORY FOR RELATED COMPONENTS ---' not in msg

def test_hooks_handle_missing_history_file_gracefully(synth_workdir_claude):
    stdin = io.StringIO(json.dumps({'session_id': synth_workdir_claude['session_id']}))
    stdout = io.StringIO()
    with patch('harness.hooks._ledger.has_verb', return_value=False), patch('harness.hooks._paths.state_dir', return_value=synth_workdir_claude['state']):
        rc = claude_user_prompt_submit.main(stdin, stdout)
    assert rc == 0
    out = json.loads(stdout.getvalue())
    assert out['decision'] == 'allow'
    msg = out['hookSpecificOutput']['additionalContext']
    assert '--- RECENT SELF-HEALING HISTORY FOR RELATED COMPONENTS ---' not in msg

def test_hooks_handle_corrupt_history_file_gracefully(synth_workdir_claude):
    state_dir = synth_workdir_claude['state']
    autowork_dir = state_dir / 'control' / 'autowork'
    autowork_dir.mkdir(parents=True, exist_ok=True)
    history_file = autowork_dir / 'self_healing_history.jsonl'
    history_file.write_text('corrupted json string\n{}\n', encoding='utf-8')
    stdin = io.StringIO(json.dumps({'session_id': synth_workdir_claude['session_id']}))
    stdout = io.StringIO()
    with patch('harness.hooks._ledger.has_verb', return_value=False), patch('harness.hooks._paths.state_dir', return_value=state_dir):
        rc = claude_user_prompt_submit.main(stdin, stdout)
    assert rc == 0
    out = json.loads(stdout.getvalue())
    assert out['decision'] == 'allow'

def test_end_to_end_escalation_and_warning_injection(temp_state_dir, mock_popen, monkeypatch):
    task_id = 'task_e2e'
    task_path = temp_state_dir / 'tasks' / 'blocked' / f'{task_id}.json'
    task_path.write_text(json.dumps({'task_id': task_id, 'files_touched': ['critical_file.py'], 'objective': 'fix core bug', 'priority': 'high'}), encoding='utf-8')
    sidecar_path = temp_state_dir / 'tasks' / 'blocked' / f'{task_id}.retry.json'
    sidecar_path.write_text(json.dumps({'attempts': 1, 'ts': time.time(), 'last_outcome': 'smoke_failed'}), encoding='utf-8')
    summary = {}
    _retry_blocked_tasks(temp_state_dir, summary, max_attempts=3)
    assert mock_popen.called
    history_path = temp_state_dir / 'control' / 'autowork' / 'self_healing_history.jsonl'
    assert history_path.is_file()
    lines = history_path.read_text(encoding='utf-8').strip().split('\n')
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record['task_id'] == task_id
    assert record['outcome'] == 'smoke_failed'
    assert record['files_touched'] == ['critical_file.py']
    workdir = temp_state_dir / 'workdirs' / 'claude' / 'sessE2E'
    (workdir / 'inbox').mkdir(parents=True)
    task_body = {'task_id': 'new_task', 'title': 'touch file', 'files_touched': ['critical_file.py']}
    (workdir / 'inbox' / 'task.json').write_text(json.dumps(task_body), encoding='utf-8')
    (temp_state_dir / 'STATE.json').write_text(json.dumps({'round': 1, 'phase': 'synthesis', 'task_id': 'new_task'}), encoding='utf-8')
    monkeypatch.setenv('JANUSMASK_STATE_DIR', str(temp_state_dir))
    monkeypatch.setenv('JANUSMASK_WORK_DIR', str(workdir))
    monkeypatch.setenv('JANUSMASK_AGENT', 'claude')
    monkeypatch.setenv('JANUSMASK_MODE', 'synthesis')
    monkeypatch.setenv('JANUSMASK_ROUND', '1')
    stdin = io.StringIO(json.dumps({'session_id': 'sessE2E'}))
    stdout = io.StringIO()
    with patch('harness.hooks._ledger.has_verb', return_value=False), patch('harness.hooks._paths.state_dir', return_value=temp_state_dir):
        rc = claude_user_prompt_submit.main(stdin, stdout)
    assert rc == 0
    out = json.loads(stdout.getvalue())
    assert out['decision'] == 'allow'
    msg = out['hookSpecificOutput']['additionalContext']
    assert '--- RECENT SELF-HEALING HISTORY FOR RELATED COMPONENTS ---' in msg
    assert task_id in msg
    assert 'smoke_failed' in msg
'Unit + integration tests for the autowork self-healing escalation flow.\n\nCovers:\n  * ``harness.autowork_daemon._escalate_to_autobrief`` — config loading,\n    history-log append, prompt + command assembly, and subprocess spawn.\n  * ``harness.autowork_daemon._retry_blocked_tasks`` — escalation triggered\n    when a deterministic failure exhausts its 1-attempt retry budget.\n  * ``harness.hooks.claude.user_prompt_submit`` / ``harness.hooks.gemini.user_prompt_submit``\n    — file-touched history overlap detection and warning-section injection.\n'