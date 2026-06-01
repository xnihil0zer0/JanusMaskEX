"""AGY2A oracle: reap zombie process after timeout killpg in spawn_agent.

RED on HEAD: the current timeout branch in spawn_agent does os.killpg but
does not call proc.kill() and proc.wait(), leaving a zombie process.

GREEN after the fix: the timeout branch in spawn_agent reaps the zombie
process by calling proc.kill() followed by proc.wait(timeout=5).
Any subprocess.TimeoutExpired or ProcessLookupError during wait is caught
and handled gracefully so it does not hang or crash the worker.
"""
from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path
import pytest

import harness.orchestrator as orch


class FakePopen:
    def __init__(self, cmd, **kwargs):
        self.cmd = cmd
        self.kwargs = kwargs
        self.pid = 9999
        self.returncode = None
        self.kill_called = False
        self.wait_called = False
        self.wait_timeout = None
        self.wait_timeout_expired = False
        self.wait_process_lookup_error = False

    def communicate(self, input=None, timeout=None):
        raise subprocess.TimeoutExpired(cmd=self.cmd, timeout=timeout)

    def kill(self):
        self.kill_called = True

    def wait(self, timeout=None):
        self.wait_called = True
        self.wait_timeout = timeout
        if self.wait_timeout_expired:
            raise subprocess.TimeoutExpired(cmd=self.cmd, timeout=timeout)
        if self.wait_process_lookup_error:
            raise ProcessLookupError()
        return 0


@pytest.fixture
def workroot(tmp_path, monkeypatch):
    root = tmp_path / "agentwork"
    monkeypatch.setenv("JANUSMASK_AGENT_WORKROOT", str(root))
    return root


def test_spawn_agent_timeout_reaps_zombie(workroot, tmp_path, monkeypatch):
    """Assert that spawn_agent's timeout path signals the process group and calls kill() and wait() to reap.

    RED on HEAD (assert proc.kill_called and proc.wait_called fail).
    """
    pgid_called_with = []
    killpg_called_with = []
    
    monkeypatch.setattr(orch.os, "getpgid", lambda pid: pgid_called_with.append(pid) or 12345)
    monkeypatch.setattr(orch.os, "killpg", lambda pgid, sig: killpg_called_with.append((pgid, sig)))
    monkeypatch.setattr(orch, "start_stream_threads", lambda *a, **k: ())
    monkeypatch.setenv("JANUSMASK_TASK_ID", "AGY2A_TEST")

    proc_instance = None

    class MockPopen(FakePopen):
        def __init__(self, cmd, **kwargs):
            nonlocal proc_instance
            super().__init__(cmd, **kwargs)
            proc_instance = self

    monkeypatch.setattr(orch.subprocess, "Popen", MockPopen)

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    config = {
        "state_dir": str(state_dir),
        "agents": {
            "gemini": {
                "command": "agy",
                "args": ["-p", "--sandbox"]
            }
        }
    }

    # Call spawn_agent, which will enter the agy timeout branch
    res = orch.spawn_agent("gemini", "dummy prompt", config, round_number=1)

    # Positive control: check that we returned the process object
    assert res is proc_instance
    assert proc_instance is not None

    # Assert that getpgid and killpg were called to signal the process group (pre-existing)
    assert 9999 in pgid_called_with
    assert (12345, signal.SIGKILL) in killpg_called_with

    # Assert that proc.kill() and proc.wait(timeout=5) were called (the fix)
    assert proc_instance.kill_called, "proc.kill() must be called to signal the process"
    assert proc_instance.wait_called, "proc.wait() must be called to reap the process"
    assert proc_instance.wait_timeout == 5, f"proc.wait() timeout must be 5, got {proc_instance.wait_timeout}"


def test_spawn_agent_timeout_wait_exception_is_suppressed(workroot, tmp_path, monkeypatch):
    """Assert that if proc.wait() raises TimeoutExpired or ProcessLookupError, the exception is caught and ignored."""
    pgid_called_with = []
    killpg_called_with = []
    
    monkeypatch.setattr(orch.os, "getpgid", lambda pid: pgid_called_with.append(pid) or 12345)
    monkeypatch.setattr(orch.os, "killpg", lambda pgid, sig: killpg_called_with.append((pgid, sig)))
    monkeypatch.setattr(orch, "start_stream_threads", lambda *a, **k: ())
    monkeypatch.setenv("JANUSMASK_TASK_ID", "AGY2A_TEST")

    proc_instance = None

    class MockPopen(FakePopen):
        def __init__(self, cmd, **kwargs):
            nonlocal proc_instance
            super().__init__(cmd, **kwargs)
            self.wait_timeout_expired = True
            proc_instance = self

    monkeypatch.setattr(orch.subprocess, "Popen", MockPopen)

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    config = {
        "state_dir": str(state_dir),
        "agents": {
            "gemini": {
                "command": "agy",
                "args": ["-p", "--sandbox"]
            }
        }
    }

    # Should not raise TimeoutExpired or ProcessLookupError
    res = orch.spawn_agent("gemini", "dummy prompt", config, round_number=1)
    assert res is proc_instance
    assert proc_instance.wait_called
    assert proc_instance.kill_called
