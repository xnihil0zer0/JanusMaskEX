"""C2ROLLBA staging path task-scoping oracle test.

Asserts:
  1. Staging paths derived for two distinct task IDs are distinct (avoiding collisions).
  2. The staging path contains/derives from the task ID.
  3. The staging path is still located under the expected parent directory (sibling to the parent worktree).
"""
import json
import subprocess
from pathlib import Path
import pytest

import harness.orchestrator as orch


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.name", "Test User")
    _git(r, "config", "user.email", "test@example.com")
    
    dummy = r / "dummy.py"
    dummy.write_text("v = 1\n", encoding="utf-8")
    _git(r, "add", "dummy.py")
    _git(r, "commit", "-m", "initial commit")
    
    (r / "state" / "output").mkdir(parents=True)
    return r


def test_c2_rollba_staging_path_taskscoped(repo, monkeypatch):
    state_dir = repo / "state"
    captured_paths = {}
    current_task_id = [None]

    def mock_create_staging_worktree(staging_path, parent_root=None):
        captured_paths[current_task_id[0]] = Path(staging_path).resolve()
        raise RuntimeError("Stop early after staging_path computation")

    monkeypatch.setattr(orch.git_integration, "create_staging_worktree", mock_create_staging_worktree)

    # Task 1
    task_id_1 = "PHASE_C2_ROLLBA_1"
    task_1 = {
        "task_id": task_id_1,
        "files_touched": ["dummy.py"],
    }
    (state_dir / "output" / f"{task_id_1}.files.json").write_text(json.dumps({"dummy.py": "v = 2\n"}))

    current_task_id[0] = task_id_1
    orch._auto_commit_accepted(state_dir, task_1, task_id_1)

    # Task 2
    task_id_2 = "PHASE_C2_ROLLBA_2"
    task_2 = {
        "task_id": task_id_2,
        "files_touched": ["dummy.py"],
    }
    (state_dir / "output" / f"{task_id_2}.files.json").write_text(json.dumps({"dummy.py": "v = 3\n"}))

    current_task_id[0] = task_id_2
    orch._auto_commit_accepted(state_dir, task_2, task_id_2)

    # Verify both paths were captured
    assert task_id_1 in captured_paths, "Task 1 staging path not captured"
    assert task_id_2 in captured_paths, "Task 2 staging path not captured"

    path_1 = captured_paths[task_id_1]
    path_2 = captured_paths[task_id_2]

    # Assertion 3: Must be a sibling of the parent worktree under worktree_root.parent
    worktree_root = repo.resolve()
    assert path_1.parent == worktree_root.parent, f"Staging path {path_1} is not under the expected parent directory"
    assert path_2.parent == worktree_root.parent, f"Staging path {path_2} is not under the expected parent directory"

    # Assertion 2: Staging path contains/derives from the task_id
    assert task_id_1 in path_1.name, f"Staging path {path_1} does not incorporate task ID {task_id_1}"
    assert task_id_2 in path_2.name, f"Staging path {path_2} does not incorporate task ID {task_id_2}"

    # Assertion 1: Distinct task IDs must yield distinct staging paths
    assert path_1 != path_2, f"Staging paths collide: {path_1} == {path_2}"
