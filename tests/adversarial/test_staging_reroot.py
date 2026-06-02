import inspect
import pathlib
import subprocess
import pytest
from harness import git_integration
from harness import orchestrator
import harness.target_bootstrap

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

def test_external_accept(repo_root, tmp_path, monkeypatch):
    # Monkeypatch harness.target_bootstrap.external_staging_root to return a tmp dir (NOT a sibling of the repo).
    # Resolve so the fix-side comparison (staging_path_obj.parent == external_staging_root()) is symlink-stable
    # (e.g. /tmp -> /tmp/claude-1000).
    ext_staging = (tmp_path / "external_staging").resolve()
    ext_staging.mkdir()

    monkeypatch.setattr(harness.target_bootstrap, "external_staging_root", lambda: ext_staging)

    # staging_path placed DIRECTLY under external_staging_root() -- NOT a sibling of the repo.
    # On HEAD create_staging_worktree raises the sibling ValueError (RED); after the fix it is accepted.
    staging_path = ext_staging / "repo_staging"
    
    # Call create_staging_worktree with parent_root kwarg
    git_integration.create_staging_worktree(str(staging_path), parent_root=repo_root)
    
    assert staging_path.exists()
    assert (staging_path / "dummy.txt").exists()
    assert (staging_path / "dummy.txt").read_text(encoding="utf-8") == "initial content"

def test_self_sibling_negative_control(repo_root, tmp_path, monkeypatch):
    # Monkeypatch harness.target_bootstrap.external_staging_root to return a tmp dir
    ext_staging = tmp_path / "external_staging"
    ext_staging.mkdir()
    
    monkeypatch.setattr(harness.target_bootstrap, "external_staging_root", lambda: ext_staging)
    
    # A non-sibling staging path whose parent is NEITHER the repo's sibling dir NOR external_staging_root()
    invalid_staging_path = tmp_path / "arbitrary_parent" / "repo_staging"
    invalid_staging_path.parent.mkdir(parents=True, exist_ok=True)
    
    with pytest.raises(ValueError, match="Staging worktree must be placed in a sibling directory of the repository root"):
        git_integration.create_staging_worktree(str(invalid_staging_path), parent_root=repo_root)


def test_orchestrator_external_staging_reroot_source():
    # The orchestrator's _auto_commit_accepted must re-root the staging worktree
    # for EXTERNAL tasks under the JM-owned external_staging_root() (CR-3 / T3),
    # deriving worktree_root via effective_target_root(working_dir). On HEAD the
    # function uses only the sibling derivation (worktree_root.parent /
    # f"{worktree_root.name}_{task_id}_staging") and references neither helper ->
    # RED. After the fix both helpers appear in the external branch.
    src = inspect.getsource(orchestrator._auto_commit_accepted)
    assert "effective_target_root" in src, (
        "external worktree_root must be derived via harness.paths.effective_target_root(working_dir)"
    )
    assert "external_staging_root" in src, (
        "external staging_path must be re-rooted under harness.target_bootstrap.external_staging_root()"
    )
