"""Tests for auto-detection of untracked test files to resolve checkout paradox."""
from __future__ import annotations
import json
import os
import pathlib
import subprocess
import pytest
from harness.orchestrator_worker import _detect_and_append_untracked_tests
from harness.git_integration import commit_accepted_output

def _git(cwd: pathlib.Path, *args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.setdefault('GIT_AUTHOR_NAME', 't')
    env.setdefault('GIT_AUTHOR_EMAIL', 't@example.com')
    env.setdefault('GIT_COMMITTER_NAME', 't')
    env.setdefault('GIT_COMMITTER_EMAIL', 't@example.com')
    return subprocess.run(['git', *args], cwd=str(cwd), env=env, check=True, capture_output=True, text=True)

@pytest.fixture
def git_repo(tmp_path: pathlib.Path) -> pathlib.Path:
    repo = tmp_path / 'repo'
    repo.mkdir()
    _git(repo, 'init', '-b', 'main', '-q')
    _git(repo, 'config', 'user.email', 't@example.com')
    _git(repo, 'config', 'user.name', 't')
    tests_dir = repo / 'tests'
    tests_dir.mkdir()
    initial_file = repo / 'initial.py'
    initial_file.write_text('# initial\n')
    _git(repo, 'add', 'initial.py')
    dummy_file = tests_dir / 'dummy.py'
    dummy_file.write_text('# dummy\n')
    _git(repo, 'add', 'tests/dummy.py')
    _git(repo, 'commit', '-m', 'initial commit')
    return repo

@pytest.fixture
def state_dir(git_repo: pathlib.Path) -> pathlib.Path:
    sd = git_repo / 'state'
    (sd / 'output').mkdir(parents=True)
    (sd / 'tasks').mkdir(parents=True)
    return sd

def test_paradox_detect_and_append_untracked_tests(git_repo: pathlib.Path, state_dir: pathlib.Path) -> None:
    test_file = git_repo / 'tests' / 'test_untracked_logic.py'
    test_file.write_text('def test_untracked():\n    pass\n')
    other_file = git_repo / 'tests' / 'helper.py'
    other_file.write_text('# helper\n')
    task_id = 'test_task'
    processing_path = state_dir / 'tasks' / f'{task_id}.json.processing'
    task_data = {'task_id': task_id, 'files_touched': ['initial.py']}
    with open(processing_path, 'w', encoding='utf-8') as f:
        json.dump(task_data, f)
    _detect_and_append_untracked_tests(state_dir, task_data, task_id, processing_path)
    assert 'tests/test_untracked_logic.py' in task_data['files_touched']
    assert 'tests/helper.py' not in task_data['files_touched']
    with open(processing_path, 'r', encoding='utf-8') as f:
        saved_data = json.load(f)
    assert 'tests/test_untracked_logic.py' in saved_data['files_touched']
    assert 'tests/helper.py' not in saved_data['files_touched']

def test_paradox_commit_accepted_output_with_untracked_tests(git_repo: pathlib.Path, state_dir: pathlib.Path) -> None:
    target_file = git_repo / 'initial.py'
    task_id = 'TASK-001'
    output_file = state_dir / 'output' / f'{task_id}.py'
    output_file.write_text('# initial\n# modified content\n')
    untracked_test = git_repo / 'tests' / 'test_new_feature.py'
    untracked_test.write_text('def test_new_feature():\n    assert True\n')
    res = commit_accepted_output(task_id, str(target_file), state_dir, worktree_root=git_repo)
    assert res['committed'] is True
    assert res['error'] is None
    sidecar_path = state_dir / 'output' / f'{task_id}.files.json'
    assert sidecar_path.exists()
    with open(sidecar_path, 'r', encoding='utf-8') as f:
        manifest = json.load(f)
    assert 'initial.py' in manifest
    assert 'tests/test_new_feature.py' in manifest
    assert manifest['tests/test_new_feature.py'] == 'def test_new_feature():\n    assert True\n'
    status_res = _git(git_repo, 'status', '--porcelain', 'initial.py', 'tests/test_new_feature.py')
    assert status_res.stdout.strip() == ''
    show_res = _git(git_repo, 'show', 'HEAD', '--name-only')
    committed_files = show_res.stdout.splitlines()
    assert any(('initial.py' in f for f in committed_files))
    assert any(('tests/test_new_feature.py' in f for f in committed_files))
from harness.orchestrator_worker import _precompute_baseline_test_results
from harness.hooks.claude import user_prompt_submit as claude_ups
from harness.hooks.gemini import user_prompt_submit as gemini_ups

def test_baseline_precompute_writes_json_with_passing_outcome(tmp_path: pathlib.Path) -> None:
    """Helper persists a JSON sidecar carrying command/outcome/exit_code/stdout/stderr."""
    state_dir = tmp_path / 'state'
    (state_dir / 'tasks').mkdir(parents=True)
    task_id = 'baseline_pass_task'
    task = {'task_id': task_id, 'verification_command': 'echo hello-baseline'}
    _precompute_baseline_test_results(state_dir, task, task_id)
    out_path = state_dir / 'tasks' / 'test_results' / f'{task_id}_baseline.json'
    assert out_path.exists(), 'baseline JSON sidecar was not written'
    body = json.loads(out_path.read_text(encoding='utf-8'))
    assert body['command'] == 'echo hello-baseline'
    assert body['outcome'] == 'passed'
    assert body['exit_code'] == 0
    assert 'hello-baseline' in body['stdout']
    for key in ('command', 'outcome', 'exit_code', 'stdout', 'stderr'):
        assert key in body, f'baseline payload missing expected key: {key}'

def test_baseline_precompute_creates_results_dir_when_missing(tmp_path: pathlib.Path) -> None:
    """Edge case: parent results dir is created on demand."""
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    task_id = 'baseline_dir_task'
    task = {'task_id': task_id, 'verification_command': 'true'}
    _precompute_baseline_test_results(state_dir, task, task_id)
    results_dir = state_dir / 'tasks' / 'test_results'
    assert results_dir.is_dir(), 'helper failed to create test_results directory'
    out_path = results_dir / f'{task_id}_baseline.json'
    assert out_path.exists()
    body = json.loads(out_path.read_text(encoding='utf-8'))
    assert body['outcome'] == 'passed'
    assert body['exit_code'] == 0

def test_baseline_precompute_captures_failing_exit_code(tmp_path: pathlib.Path) -> None:
    """A non-zero exit from the verification command is recorded as 'failed'."""
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    task_id = 'baseline_fail_task'
    task = {'task_id': task_id, 'verification_command': "bash -c 'echo oh-no 1>&2; exit 3'"}
    _precompute_baseline_test_results(state_dir, task, task_id)
    out_path = state_dir / 'tasks' / 'test_results' / f'{task_id}_baseline.json'
    body = json.loads(out_path.read_text(encoding='utf-8'))
    assert body['outcome'] == 'failed'
    assert body['exit_code'] == 3
    assert 'oh-no' in body['stderr']

def test_baseline_precompute_handles_missing_verification_command(tmp_path: pathlib.Path) -> None:
    """Edge case: no verification_command anywhere -> outcome=no_verification_command."""
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    task_id = 'baseline_missing_task'
    task = {'task_id': task_id}
    _precompute_baseline_test_results(state_dir, task, task_id)
    out_path = state_dir / 'tasks' / 'test_results' / f'{task_id}_baseline.json'
    assert out_path.exists()
    body = json.loads(out_path.read_text(encoding='utf-8'))
    assert body['outcome'] == 'no_verification_command'
    assert body['exit_code'] is None

def test_baseline_hook_formatter_renders_markdown_block(tmp_path: pathlib.Path) -> None:
    """Both prompt hooks render the baseline JSON into a markdown block."""
    state_root = tmp_path / 'state'
    results_dir = state_root / 'tasks' / 'test_results'
    results_dir.mkdir(parents=True)
    task_id = 'baseline_format_task'
    payload = {'task_id': task_id, 'command': 'pytest tests/foo.py', 'outcome': 'failed', 'exit_code': 1, 'stdout': 'collected 0 items', 'stderr': 'E   AssertionError: boom'}
    (results_dir / f'{task_id}_baseline.json').write_text(json.dumps(payload), encoding='utf-8')
    claude_section = claude_ups._format_baseline_section(state_root, task_id)
    gemini_section = gemini_ups._format_baseline_section(state_root, task_id)
    for section in (claude_section, gemini_section):
        assert section is not None
        assert 'BASELINE TEST RESULTS' in section
        assert 'pytest tests/foo.py' in section
        assert 'failed' in section
        assert 'Exit code: 1' in section
        assert 'AssertionError: boom' in section

def test_baseline_hook_formatter_returns_none_when_missing(tmp_path: pathlib.Path) -> None:
    """Hook formatter returns None when the baseline sidecar does not exist."""
    state_root = tmp_path / 'state'
    state_root.mkdir()
    assert claude_ups._format_baseline_section(state_root, 'no_such_task') is None
    assert gemini_ups._format_baseline_section(state_root, 'no_such_task') is None
    assert claude_ups._format_baseline_section(state_root, '') is None
    assert gemini_ups._format_baseline_section(state_root, '') is None
'Tests for auto-detection of untracked test files to resolve checkout paradox,\nand pre-computation of baseline verification_command results at worker startup.'