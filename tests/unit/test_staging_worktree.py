import pathlib
import subprocess
import shutil
import pytest
from harness import git_integration

def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)

@pytest.fixture
def repo_root(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.name", "Test User")
    _git(r, "config", "user.email", "test@example.com")
    
    # Need at least one commit
    dummy = r / "dummy.txt"
    dummy.write_text("initial content", encoding="utf-8")
    _git(r, "add", "dummy.txt")
    _git(r, "commit", "-m", "initial commit")
    return r

def test_create_staging_worktree_success(repo_root, tmp_path):
    staging_path = tmp_path / "repo_staging"
    git_integration.create_staging_worktree(str(staging_path), parent_root=repo_root)
    
    assert staging_path.exists()
    assert (staging_path / "dummy.txt").exists()
    assert (staging_path / "dummy.txt").read_text(encoding="utf-8") == "initial content"

def test_remove_staging_worktree_success(repo_root, tmp_path):
    staging_path = tmp_path / "repo_staging"
    git_integration.create_staging_worktree(str(staging_path), parent_root=repo_root)
    assert staging_path.exists()
    
    git_integration.remove_staging_worktree(str(staging_path), parent_root=repo_root)
    assert not staging_path.exists()

def test_handle_existing_worktree_path(repo_root, tmp_path):
    staging_path = tmp_path / "repo_staging"
    git_integration.create_staging_worktree(str(staging_path), parent_root=repo_root)
    assert staging_path.exists()
    
    # Try creating it again when it already exists
    git_integration.create_staging_worktree(str(staging_path), parent_root=repo_root)
    assert staging_path.exists()

def test_prune_stale_worktrees(repo_root, tmp_path):
    staging_path = tmp_path / "repo_staging"
    git_integration.create_staging_worktree(str(staging_path), parent_root=repo_root)
    assert staging_path.exists()
    
    # Delete the staging directory physically without removing the worktree in git
    shutil.rmtree(staging_path)
    assert not staging_path.exists()
    
    # Running create_staging_worktree should prune it and recreate successfully
    git_integration.create_staging_worktree(str(staging_path), parent_root=repo_root)
    assert staging_path.exists()

def test_staging_worktree_sibling_check(repo_root, tmp_path):
    # Place staging inside the repo (not a sibling)
    invalid_staging_path = repo_root / "staging"
    
    with pytest.raises(ValueError, match="sibling directory"):
        git_integration.create_staging_worktree(str(invalid_staging_path), parent_root=repo_root)
