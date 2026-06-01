import os
import signal
import subprocess
import pytest
from harness.orchestrator import kill_agent

class FakePopen:
    def __init__(self):
        self.pid = 12345
        self.returncode = None
        self._stream_threads = None
        self.terminate_called = False
        self.kill_called = False
        self.wait_calls = []

    def poll(self):
        return None

    def wait(self, timeout=None):
        self.wait_calls.append(timeout)
        raise subprocess.TimeoutExpired(cmd='x', timeout=timeout)

    def terminate(self):
        self.terminate_called = True

    def kill(self):
        self.kill_called = True


def test_kill_reap_final_wait_timeout_is_swallowed(monkeypatch):
    def mock_killpg(pgid, sig):
        raise ProcessLookupError("No such process group")

    def mock_getpgid(pid):
        raise ProcessLookupError("No such process")

    monkeypatch.setattr("harness.orchestrator.os.killpg", mock_killpg)
    monkeypatch.setattr("harness.orchestrator.os.getpgid", mock_getpgid)

    fake = FakePopen()
    
    # Under current HEAD, this will raise subprocess.TimeoutExpired due to the final wait(3) being unguarded.
    kill_agent(fake, "claude", "handoff")

    # Assert it called wait with 5 and 3
    assert fake.wait_calls == [5, 3]
    # Assert it called terminate and kill as part of fallback
    assert fake.terminate_called is True
    assert fake.kill_called is True


def test_kill_reap_already_exited_returns_early():
    class AlreadyExitedFakePopen:
        def __init__(self):
            self.pid = 12345
            self.returncode = 0
            self._stream_threads = None
            self.wait_called = False

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            self.wait_called = True
            raise subprocess.TimeoutExpired(cmd='x', timeout=timeout)

        def terminate(self):
            pass

        def kill(self):
            pass

    fake = AlreadyExitedFakePopen()
    kill_agent(fake, "claude", "handoff")
    assert fake.wait_called is False
