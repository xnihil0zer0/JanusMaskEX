"""Adversarial security test for SEC-ENV-DAEMON.

Verifies that _escalate_to_autobrief and _escalate_inactivity in
harness.autowork_daemon scrub their environment via an allowlist, preventing
the leakage of host secrets (e.g., GITHUB_TOKEN, AWS_*) while preserving
required system variables (PATH, HOME, DBUS_SESSION_BUS_ADDRESS) and task-specific keys.

RED on HEAD: both self-heal escalation functions build `env = dict(os.environ)`
and pass it to subprocess.Popen(env=...), so a seeded host secret leaks into the
captured env. GREEN once each `dict(os.environ)` is replaced by the same explicit
allowlist used by orchestrator._build_agent_env.
"""
from __future__ import annotations

import json
import os
import pathlib
import pytest
import subprocess

import harness.autowork_daemon as dae


class FakePopen:
    """Mock subprocess.Popen to capture kwargs['env'] without running a command."""
    def __init__(self, cmd, **kwargs):
        self.cmd = cmd
        self.kwargs = kwargs
        self.pid = 99999
        self.returncode = 0
        # Capture the environment copy passed to Popen
        FakePopen.captured_envs.append(kwargs.get("env", {}))

    def poll(self):
        return 0

    def wait(self, timeout=None):
        return 0


# Registry for captured environments
FakePopen.captured_envs = []


def test_sec_env_daemon_allowlist(tmp_path, monkeypatch):
    # Reset captured environment list
    FakePopen.captured_envs.clear()

    # 1. Monkeypatch os.environ to add secrets and required variables
    monkeypatch.setenv("JM_TEST_SHOULD_NOT_LEAK", "secret")
    monkeypatch.setenv("GITHUB_TOKEN", "ghtok")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "awssecret")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("HOME", "/home/user")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/tmp/dbus")
    # A vendor-prefix auth var that MUST survive the allowlist filter (XDG_).
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")

    # Set the agent workroot outside the repo tree to avoid ValueError in agent_workroot()
    agent_workroot_dir = tmp_path / "agent_workroot"
    agent_workroot_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("JANUSMASK_AGENT_WORKROOT", str(agent_workroot_dir))

    # 2. Monkeypatch subprocess.Popen to capture kwargs['env']. Both escalation
    # functions do a function-local `import subprocess`, which resolves to the
    # cached top-level module object, so patching the real subprocess.Popen is
    # what they actually see at spawn time.
    monkeypatch.setattr(subprocess, "Popen", FakePopen)

    # 3. Monkeypatch _contain_selfheal to pass cmd through (the env build under
    # test lives in the escalation functions, not in _contain_selfheal).
    monkeypatch.setattr(dae, "_contain_selfheal", lambda cmd, env, work_dir, state_dir, config, agent="": cmd)

    # Prepare directories
    state_dir = tmp_path / "state"
    tasks_dir = state_dir / "tasks"
    blocked_dir = tasks_dir / "blocked"
    blocked_dir.mkdir(parents=True, exist_ok=True)

    # 4. Drive _escalate_to_autobrief with a seeded blocked task (objective+files)
    task_id = "test_task_brief"
    task_json_path = blocked_dir / f"{task_id}.json"
    task_data = {
        "task_id": task_id,
        "objective": "Diagnose and repair the issue",
        "files_touched": ["lib/core.py"]
    }
    task_json_path.write_text(json.dumps(task_data), encoding="utf-8")

    dae._escalate_to_autobrief(state_dir, task_id, "synthesis_or_ast_failed")

    # Drive _escalate_inactivity with a seeded auto_promote.allowlist
    control_dir = state_dir / "control" / "autowork"
    control_dir.mkdir(parents=True, exist_ok=True)
    allowlist_path = control_dir / "auto_promote.allowlist"
    allowlist_path.write_text("some_task_slug\n", encoding="utf-8")

    dae._escalate_inactivity(state_dir, {})

    # Verify that we captured environments from both escalation spawns
    assert len(FakePopen.captured_envs) == 2

    # 5. Asserts the captured envs do NOT contain the seeded host secrets, but DO
    # contain PATH, HOME, DBUS_SESSION_BUS_ADDRESS, the vendor-prefix auth var, and
    # the expected JANUSMASK_* keys the function sets after the filtered base.
    for idx, env in enumerate(FakePopen.captured_envs):
        # Assert expected task identification is present (overlaid after the filter)
        assert env.get("JANUSMASK_MODE") == "planning"
        if idx == 0:
            assert env.get("JANUSMASK_TASK_ID") == "test_task_brief"
        else:
            assert env.get("JANUSMASK_TASK_ID") == "daemon_inactivity_stuck"
        assert "JANUSMASK_WORK_DIR" in env

        # Assert required / auth variables are preserved
        assert "PATH" in env
        assert env["PATH"] == "/usr/bin:/bin"
        assert "HOME" in env
        assert env["HOME"] == "/home/user"
        assert "DBUS_SESSION_BUS_ADDRESS" in env
        assert env["DBUS_SESSION_BUS_ADDRESS"] == "unix:path=/tmp/dbus"
        # vendor-prefix auth var (XDG_) MUST survive or self-heal auth breaks
        assert env.get("XDG_RUNTIME_DIR") == "/run/user/1000"

        # Assert secrets do NOT leak (RED on the current source which copies all of os.environ)
        assert "JM_TEST_SHOULD_NOT_LEAK" not in env
        assert "GITHUB_TOKEN" not in env
        assert "AWS_SECRET_ACCESS_KEY" not in env
