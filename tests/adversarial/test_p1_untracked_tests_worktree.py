"""Adversarial test for checking that untracked test files are copied to the staging worktree."""
import os
import pathlib
import subprocess
import pytest

from harness.git_integration import create_staging_worktree


def test_untracked_tests_copied_to_worktree(tmp_path):
    # 1. Build a temp parent git repo
    parent_repo = tmp_path / "parent"
    parent_repo.mkdir()
    
    # Set up environment with git committer/author variables
    env = os.environ.copy()
    env["GIT_AUTHOR_NAME"] = "Test Author"
    env["GIT_AUTHOR_EMAIL"] = "author@example.com"
    env["GIT_COMMITTER_NAME"] = "Test Committer"
    env["GIT_COMMITTER_EMAIL"] = "committer@example.com"
    
    # Initialize the repo
    subprocess.run(["git", "init", "-b", "main", "-q"], cwd=parent_repo, env=env, check=True)
    subprocess.run(["git", "config", "user.name", "Test Committer"], cwd=parent_repo, env=env, check=True)
    subprocess.run(["git", "config", "user.email", "committer@example.com"], cwd=parent_repo, env=env, check=True)
    
    # Commit an initial file to have a commit history
    dummy = parent_repo / "dummy.py"
    dummy.write_text("print('hello')\n")
    subprocess.run(["git", "add", "dummy.py"], cwd=parent_repo, env=env, check=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=parent_repo, env=env, check=True)
    
    # 2. Add an UNTRACKED file tests/test_injected_oracle.py (NOT git-added)
    tests_dir = parent_repo / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    untracked_file = tests_dir / "test_injected_oracle.py"
    untracked_file.write_text("def test_injected():\n    pass\n")
    
    # Ensure it's untracked
    status_res = subprocess.run(["git", "status", "--porcelain", "-u"], cwd=parent_repo, env=env, check=True, capture_output=True, text=True)
    assert "??" in status_res.stdout
    assert "tests/test_injected_oracle.py" in status_res.stdout
    
    # 3. Call harness.git_integration.create_staging_worktree
    staging_path = tmp_path / "staging"
    assert staging_path.parent == parent_repo.parent
    
    create_staging_worktree(str(staging_path), parent_root=parent_repo)
    
    # 4. Assert tests/test_injected_oracle.py EXISTS inside the staging worktree
    copied_untracked = staging_path / "tests" / "test_injected_oracle.py"
    assert copied_untracked.exists()
