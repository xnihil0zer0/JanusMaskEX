import os
import subprocess
import time
import pytest
import sys
from hypothesis import given, settings, strategies as st
from harness.sandbox import Sandbox, SandboxConfig, _safe_close_proc

def count_open_fds():
    try:
        return len(os.listdir('/proc/self/fd'))
    except OSError:
        return 0

def test_sandbox_execute_closes_pipes_on_success():
    baseline = count_open_fds()
    sb = Sandbox()
    res = sb.execute("def f(): return 42", "f")
    assert res.success is True
    assert count_open_fds() <= baseline + 5

def test_sandbox_execute_closes_pipes_on_timeout(monkeypatch):
    original_comm = subprocess.Popen.communicate
    def mock_comm(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="mock", timeout=0.01)
    monkeypatch.setattr(subprocess.Popen, "communicate", mock_comm)
    
    baseline = count_open_fds()
    sb = Sandbox(config=SandboxConfig(timeout_per_input_ms=50))
    res = sb.execute("import time\ndef f():\n while True: time.sleep(0.01)", "f")
    assert res.timed_out is True
    
    try:
        pid, status = os.waitpid(-1, os.WNOHANG)
    except ChildProcessError:
        pass
        
    assert count_open_fds() <= baseline + 5

def test_sandbox_execute_closes_pipes_on_exception(monkeypatch):
    baseline = count_open_fds()
    sb = Sandbox()
    
    import json
    def mock_load(*args, **kwargs):
        raise ValueError("Corrupt file")
    monkeypatch.setattr(json, "load", mock_load)
    
    res = sb.execute("def f(): return 42", "f")
    assert res.success is False
    assert "Corrupt" in res.exception_message
    
    assert count_open_fds() <= baseline + 5

def test_safe_close_proc_handles_none_pipes():
    proc = subprocess.Popen([sys.executable, "-c", "pass"], stdout=None, stderr=None)
    proc.wait()
    _safe_close_proc(proc)

def test_high_volume_timeout_stress_no_fd_leak(monkeypatch):
    original_comm = subprocess.Popen.communicate
    def mock_comm(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="mock", timeout=0.01)
    monkeypatch.setattr(subprocess.Popen, "communicate", mock_comm)

    baseline = count_open_fds()
    sb = Sandbox(config=SandboxConfig(timeout_per_input_ms=10))
    for _ in range(500):
        res = sb.execute("import time\ndef f():\n while True: time.sleep(0.01)", "f")
        assert res.timed_out is True
    final_count = count_open_fds()
    assert final_count <= baseline + 10

@settings(deadline=None, max_examples=20)
@given(st.integers(min_value=1, max_value=100))
def test_fd_count_stable_across_random_timeouts(timeout_ms):
    mp = pytest.MonkeyPatch()
    def mock_comm(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="mock", timeout=0.01)
    mp.setattr(subprocess.Popen, "communicate", mock_comm)
    
    try:
        baseline = count_open_fds()
        sb = Sandbox(config=SandboxConfig(timeout_per_input_ms=timeout_ms))
        res = sb.execute("import time\ndef f():\n time.sleep(0.5)", "f")
        assert res.timed_out is True
        assert count_open_fds() <= baseline + 5
    finally:
        mp.undo()

def test_critique_section_1_3_fd_leak_fixed(monkeypatch):
    def mock_comm(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="mock", timeout=0.01)
    monkeypatch.setattr(subprocess.Popen, "communicate", mock_comm)
    
    baseline = count_open_fds()
    sb = Sandbox(config=SandboxConfig(timeout_per_input_ms=10))
    for _ in range(50):
        res = sb.execute("import time\ndef f():\n while True: time.sleep(0.01)", "f")
        assert res.timed_out is True
    assert count_open_fds() <= baseline + 10
