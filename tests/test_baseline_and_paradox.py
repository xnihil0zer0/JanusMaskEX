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