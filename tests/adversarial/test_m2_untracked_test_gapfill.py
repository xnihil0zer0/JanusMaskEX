"""Oracle for PHASE_M2_GAPFILL: fix untracked-test commit-poisoning deadlock."""
from __future__ import annotations

import os
import pathlib
import subprocess
import pytest

from harness.git_integration import commit_accepted_output, create_staging_worktree


def _git(cwd: pathlib.Path, *args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.setdefault("GIT_AUTHOR_NAME", "t")
    env.setdefault("GIT_AUTHOR_EMAIL", "t@example.com")
    env.setdefault("GIT_COMMITTER_NAME", "t")
    env.setdefault("GIT_COMMITTER_EMAIL", "t@example.com")
    return subprocess.run(
        ["git", *args], cwd=str(cwd), env=env, check=True,
        capture_output=True, text=True,
    )


@pytest.fixture
def repo_setup(tmp_path):
    # 1. Init a parent repo
    parent = tmp_path / "parent"
    parent.mkdir()
    _git(parent, "init", "-b", "main", "-q")
    _git(parent, "config", "user.email", "t@example.com")
    _git(parent, "config", "user.name", "t")
    
    # Create initial commit
    dummy = parent / "dummy.py"
    dummy.write_text("x = 1\n")
    _git(parent, "add", "dummy.py")
    _git(parent, "commit", "-m", "initial commit")
    
    # Create target file tracked in parent
    target_rel = "src/foo.py"
    target_file = parent / target_rel
    target_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.write_text("def my_func():\n    return 1\n")
    _git(parent, "add", target_rel)
    
    # Track a dummy test file under tests/ so tests/ is a tracked directory
    dummy_test_rel = "tests/test_dummy.py"
    dummy_test = parent / dummy_test_rel
    dummy_test.parent.mkdir(parents=True, exist_ok=True)
    dummy_test.write_text("def test_dummy():\n    pass\n")
    _git(parent, "add", dummy_test_rel)
    
    _git(parent, "commit", "-m", "add target file and dummy test")
    
    # 2. Create a staging worktree via create_staging_worktree (sibling of parent)
    staging = tmp_path / "staging"
    create_staging_worktree(str(staging), parent_root=parent)
    
    # 3. Create state_dir under parent
    state_dir = parent / "state"
    (state_dir / "output").mkdir(parents=True, exist_ok=True)
    
    return parent, staging, state_dir, target_rel


def test_m2_untracked_test_gapfill_remedy_a(repo_setup):
    """Test 1 (Remedy A): in the STAGING worktree write a new tests/test_newly_authored.py NOT in
    files_touched; call commit_accepted_output(..., worktree_root=staging, allowed_files={target_rel});
    assert result['committed'] is True AND the new test's CONTENT lands committed in staging.
    """
    parent, staging, state_dir, target_rel = repo_setup
    
    # Write a new test file in the staging worktree
    tests_dir = staging / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    new_test = tests_dir / "test_newly_authored.py"
    new_test_content = "def test_authored():\n    pass\n"
    new_test.write_text(new_test_content)
    
    # Prepare the accepted output file
    (state_dir / "output" / "T_A.py").write_text("def my_func():\n    return 2\n")
    
    # Call commit_accepted_output
    result = commit_accepted_output(
        task_id="T_A",
        target_file=str(staging / target_rel),
        state_dir=state_dir,
        worktree_root=staging,
        allowed_files={target_rel}
    )
    
    # Assert result and that the test is committed in staging
    assert result['committed'] is True, f"Commit failed: {result}"
    
    # Check that the test file was committed in staging (should exist in git show HEAD:tests/test_newly_authored.py)
    show_res = subprocess.run(
        ["git", "show", "HEAD:tests/test_newly_authored.py"],
        cwd=str(staging), capture_output=True, text=True
    )
    assert show_res.returncode == 0, "Test file was not committed in staging"
    assert show_res.stdout == new_test_content, "Committed content does not match"


def test_m2_untracked_test_gapfill_remedy_b(repo_setup):
    """Test 2 (Remedy B): leave a dirty untracked tests/test_scratch.py in the PARENT repo only;
    run an unrelated accept; assert it is NOT poisoned (committed True) and the parent scratch
    file is NOT pulled into the commit.
    """
    parent, staging, state_dir, target_rel = repo_setup
    
    # Leave a dirty untracked test file in the parent repo only
    parent_tests_dir = parent / "tests"
    parent_tests_dir.mkdir(parents=True, exist_ok=True)
    parent_scratch = parent_tests_dir / "test_scratch.py"
    parent_scratch.write_text("def test_scratch():\n    pass\n")
    
    # Prepare the accepted output file for an unrelated accept
    (state_dir / "output" / "T_B.py").write_text("def my_func():\n    return 3\n")
    
    # Call commit_accepted_output
    result = commit_accepted_output(
        task_id="T_B",
        target_file=str(staging / target_rel),
        state_dir=state_dir,
        worktree_root=staging,
        allowed_files={target_rel}
    )
    
    # Assert that the commit is NOT poisoned (committed True)
    assert result['committed'] is True, f"Commit poisoned or failed: {result}"
    
    # Assert that the parent scratch file was NOT pulled into the commit in staging
    show_res = subprocess.run(
        ["git", "show", "HEAD:tests/test_scratch.py"],
        cwd=str(staging), capture_output=True, text=True
    )
    assert show_res.returncode != 0, "Parent scratch file was incorrectly committed in staging"
