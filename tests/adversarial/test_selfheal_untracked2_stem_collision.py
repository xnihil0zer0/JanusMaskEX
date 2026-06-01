"""Oracles for self-heal untracked processes and stem collisions.

Pins the following bugs in `harness.autowork_daemon`:
1. `_escalate_to_autobrief` spawns a self-heal process via subprocess.Popen but discards
   the handle and writes no pidfile (untracked child process).
2. `_escalate_inactivity` spawns a self-heal process but writes a pidfile with a static
   stem ('selfheal_claude_daemon_inactivity_stuck'), leading to stem collisions across
   repeated escalations.
"""
from __future__ import annotations

import inspect
import json
import os
import pathlib
import pytest

import harness.autowork_daemon as ad


class FakeProcess:
    def __init__(self, pid: int):
        self.pid = pid


@pytest.fixture
def mock_popen_setup(monkeypatch):
    pids = []

    def fake_popen(*args, **kwargs):
        if pids:
            return FakeProcess(pids.pop(0))
        return FakeProcess(99999)

    monkeypatch.setattr(ad.subprocess, "Popen", fake_popen)
    import subprocess
    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    # Monkeypatch _contain_selfheal to be a simple passthrough
    monkeypatch.setattr(ad, "_contain_selfheal", lambda cmd, env, work_dir, state_dir, config, agent: cmd)

    return pids


def test_autobrief_writes_tracked_pidfile(tmp_path, monkeypatch, mock_popen_setup):
    pids = mock_popen_setup

    # Configure JANUSMASK_AGENT_WORKROOT to avoid polluting the repo and to pass GAP_H3 check
    agent_workroot = tmp_path / "agentwork"
    agent_workroot.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("JANUSMASK_AGENT_WORKROOT", str(agent_workroot))

    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)

    tid = "test_task_123"

    # Set up blocked task JSON at state_dir/tasks/blocked/<tid>.json
    blocked_dir = state_dir / "tasks" / "blocked"
    blocked_dir.mkdir(parents=True, exist_ok=True)

    task_json = blocked_dir / f"{tid}.json"
    task_data = {
        "objective": "Dummy self-heal test task",
        "files_touched": ["dummy_file.py"]
    }
    task_json.write_text(json.dumps(task_data), encoding="utf-8")

    fake_pid = 54321
    pids.append(fake_pid)

    # Call _escalate_to_autobrief
    ad._escalate_to_autobrief(state_dir, tid, 'narrow_fuzz_failed')

    # Assert EXACTLY ONE *.pid file exists under running dir
    running_dir = ad._running_dir(state_dir)
    assert running_dir.exists(), "Running directory was not created"

    pid_files = list(running_dir.glob("*.pid"))
    assert len(pid_files) == 1, f"Expected exactly 1 pid file, found {len(pid_files)}"

    pid_file = pid_files[0]

    # Stem starts with 'selfheal_' and contains the tid
    assert pid_file.stem.startswith("selfheal_")
    assert tid in pid_file.stem

    # Content == str(fake_pid)
    assert pid_file.read_text(encoding="utf-8").strip() == str(fake_pid)


def test_inactivity_stem_collision_free(tmp_path, monkeypatch, mock_popen_setup):
    pids = mock_popen_setup

    # Configure JANUSMASK_AGENT_WORKROOT to avoid polluting the repo and to pass GAP_H3 check
    agent_workroot = tmp_path / "agentwork"
    agent_workroot.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("JANUSMASK_AGENT_WORKROOT", str(agent_workroot))

    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)

    # Create state_dir/control/autowork/auto_promote.allowlist with one allowlisted task line
    control_dir = state_dir / "control" / "autowork"
    control_dir.mkdir(parents=True, exist_ok=True)
    allowlist_file = control_dir / "auto_promote.allowlist"
    allowlist_file.write_text("some_task_id\n", encoding="utf-8")

    # Queue pids for Popen
    pids.extend([111111, 222222])

    config = {}
    # Call _escalate_inactivity twice
    ad._escalate_inactivity(state_dir, config)
    ad._escalate_inactivity(state_dir, config)

    # Assert TWO distinct *.pid files remain under running dir (one per escalation)
    running_dir = ad._running_dir(state_dir)
    assert running_dir.exists(), "Running directory was not created"

    pid_files = list(running_dir.glob("*.pid"))

    # RED-on-HEAD: static stem overwrites -> only ONE file
    assert len(pid_files) == 2, f"Expected exactly 2 pid files, found {len(pid_files)}"

    contents = {f.read_text(encoding="utf-8").strip() for f in pid_files}
    assert contents == {"111111", "222222"}


def test_no_clock_component():
    src_brief = inspect.getsource(ad._escalate_to_autobrief)
    src_inactivity = inspect.getsource(ad._escalate_inactivity)

    for src in [src_brief, src_inactivity]:
        for line in src.splitlines():
            if "_write_pidfile" in line:
                assert "time" not in line.lower()
                assert "now" not in line.lower()
                assert "datetime" not in line.lower()
