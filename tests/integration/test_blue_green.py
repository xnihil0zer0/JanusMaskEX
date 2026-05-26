import os
import sys
import shutil
import subprocess
import pathlib
import pytest
from unittest import mock
from harness import git_integration
from harness import state
from harness import orchestrator

def test_blue_green_handover_e2e(tmp_path):
    # Setup temporary git repo
    repo_path = tmp_path / "test_repo"
    repo_path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=str(repo_path), check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=str(repo_path), check=True)
    subprocess.run(["git", "config", "user.email", "test@janusmask.local"], cwd=str(repo_path), check=True)

    # Create a dummy script that will be executed and hot-swapped
    runner_py = repo_path / "runner.py"
    runner_py.write_text(f"""
import os
import sys
import pathlib
import json

# Adjust sys.path to find harness
sys.path.insert(0, {repr(str(pathlib.Path(__file__).resolve().parent.parent.parent))})
from harness.state import init_state, serialize_orchestrator_state
from harness.orchestrator import perform_process_handover

def main():
    state_dir = pathlib.Path("state")
    state_dir.mkdir(exist_ok=True)
    
    # Read or init state
    current_state = init_state(state_dir)
    
    if os.environ.get("HANDOVER_STAGE") == "2":
        # We check if we are in stage 2 (rehydrated)
        # Note: init_state clears handoff_pending and returns the rehydrated dict
        # if handoff_pending was True.
        print(f"STATE_WAS_PRESERVED={{current_state.get('handoff_pending') is False}}")
        print(f"STEP2_PID={{os.getpid()}}")
        print("STEP2_SUCCESS")
        sys.exit(0)
    else:
        print(f"STEP1_PID={{os.getpid()}}")
        # Prepare for handover
        os.environ["HANDOVER_STAGE"] = "2"
        perform_process_handover(state_dir)

if __name__ == "__main__":
    main()
""", encoding="utf-8")

    # Commit the script
    subprocess.run(["git", "add", "runner.py"], cwd=str(repo_path), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=str(repo_path), check=True)

    # Run the runner subprocess
    # We set HANDOVER_STAGE=1 initially so it triggers handover
    env = {**os.environ, "HANDOVER_STAGE": "1", "PYTHONPATH": str(pathlib.Path(__file__).resolve().parent.parent.parent)}
    res = subprocess.run([sys.executable, "runner.py"], cwd=str(repo_path), env=env, capture_output=True, text=True, timeout=30)

    # Check output
    stdout = res.stdout
    print("Runner stdout:\n", stdout)
    print("Runner stderr:\n", res.stderr)

    assert res.returncode == 0, f"Runner exited with non-zero code {res.returncode}"
    
    # Extract PIDs and verify
    step1_pid = None
    step2_pid = None
    for line in stdout.splitlines():
        if line.startswith("STEP1_PID="):
            step1_pid = line.split("=")[1]
        elif line.startswith("STEP2_PID="):
            step2_pid = line.split("=")[1]

    assert step1_pid is not None, "Failed to find STEP1_PID in output"
    assert step2_pid is not None, "Failed to find STEP2_PID in output"
    assert step1_pid == step2_pid, f"PID changed across handover: {step1_pid} != {step2_pid}"
    assert "STEP2_SUCCESS" in stdout, "Step 2 did not print success marker"

def test_staging_worktree_flow(tmp_path):
    # Setup parent repo
    parent_path = tmp_path / "parent"
    parent_path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=str(parent_path), check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=str(parent_path), check=True)
    subprocess.run(["git", "config", "user.email", "test@janusmask.local"], cwd=str(parent_path), check=True)

    # Commit a dummy file
    test_file = parent_path / "hello.txt"
    test_file.write_text("hello", encoding="utf-8")
    subprocess.run(["git", "add", "hello.txt"], cwd=str(parent_path), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=str(parent_path), check=True)

    staging_path = tmp_path / "staging"

    # Create staging worktree
    git_integration.create_staging_worktree(str(staging_path), parent_root=parent_path)
    assert staging_path.exists()
    assert (staging_path / "hello.txt").exists()

    # Modify and commit in staging
    (staging_path / "hello.txt").write_text("hello world", encoding="utf-8")
    subprocess.run(["git", "add", "hello.txt"], cwd=str(staging_path), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "staging edit"], cwd=str(staging_path), check=True)

    # Merge back to parent
    git_integration.merge_staging_to_parent(staging_path, parent_root=parent_path)

    # Verify that staging was removed and parent was updated
    assert not staging_path.exists()
    assert test_file.read_text(encoding="utf-8") == "hello world"
