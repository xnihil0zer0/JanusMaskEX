import os
import signal
import subprocess
import sys
import threading
import time
import textwrap

import pytest
from hypothesis import given, settings, strategies as st

from harness.sandbox import Sandbox, SandboxConfig, WallDeadlineWatchdog, kill_process_group

def spawn_sleeper(sleep_time: float) -> subprocess.Popen:
    code = textwrap.dedent(f"""
        import time
        try:
            time.sleep({sleep_time})
        except BaseException as e:
            time.sleep(0.5) # ignore sigterm temporarily to force sigkill if needed
            raise
    """)
    return subprocess.Popen([sys.executable, "-c", code], start_new_session=True)

def test_watchdog_fires_on_expire_for_live_child():
    called = []
    def on_expire(pid):
        called.append(pid)
        kill_process_group(pid, grace_sec=0.1)

    proc = spawn_sleeper(2.0)
    wd = WallDeadlineWatchdog(proc.pid, 0.2, on_expire)
    
    start = time.time()
    proc.wait()
    elapsed = time.time() - start
    
    wd.thread.join()
    assert len(called) == 1
    assert called[0] == proc.pid
    # The kill-proof is the returncode assert below (natural exit => rc 0).
    # This bound only asserts the watchdog killed BEFORE the 2.0s natural
    # sleep would end; nominal kill path is ~0.25s, so 1.8 tolerates heavy
    # full-suite load while still discriminating from natural exit.
    assert elapsed < 1.8
    assert proc.returncode in (-signal.SIGTERM, -signal.SIGKILL, 9, 15)

def test_watchdog_cancel_before_expire():
    called = []
    def on_expire(pid):
        called.append(pid)
        
    proc = spawn_sleeper(0.5)
    wd = WallDeadlineWatchdog(proc.pid, 10.0, on_expire)
    time.sleep(0.05)
    wd.cancel()
    
    wd.thread.join(timeout=0.1)
    assert not wd.thread.is_alive()
    assert len(called) == 0
    proc.kill()
    proc.wait()

def test_kill_process_group_sigterm_then_sigkill():
    # A child that ignores SIGTERM
    code = textwrap.dedent("""
        import signal, time
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        while True:
            time.sleep(0.1)
    """)
    proc = subprocess.Popen([sys.executable, "-c", code], start_new_session=True)
    time.sleep(0.1) # wait for signal handler setup
    
    start = time.time()
    kill_process_group(proc.pid, grace_sec=0.2)
    proc.wait()
    elapsed = time.time() - start
    
    assert elapsed >= 0.2
    assert proc.returncode in (-signal.SIGKILL, 9)

def test_kill_process_group_handles_missing_pgrp():
    proc = spawn_sleeper(0.1)
    proc.kill()
    proc.wait()
    # Now it's missing/dead
    # Should not raise
    kill_process_group(proc.pid, grace_sec=0.1)

def test_sandbox_execute_with_sleeping_code():
    sb = Sandbox(SandboxConfig(timeout_per_input_ms=500))
    code = textwrap.dedent("""
        import time
        def f():
            time.sleep(30)
            return 1
    """)
    start = time.time()
    result = sb.execute(code, "f")
    elapsed = time.time() - start
    
    assert result.timed_out is True
    # Discriminates timeout enforcement (bounded) from waiting out the 30s
    # sleep. This execute goes through sandbox_child_env, so the autocompiler
    # determinism layer's per-child startup cost lands here: measured 2.51s in
    # ISOLATION with determinism ON — the old 3.0 bound was a guaranteed flake
    # under load. 10.0 is >> nominal and << the 30s regression.
    assert elapsed < 10.0
    
    # check for zombies
    try:
        pid, status = os.waitpid(-1, os.WNOHANG)
        assert pid == 0, f"Found unexpected child process {pid}"
    except ChildProcessError:
        pass # No children at all

@settings(max_examples=5, deadline=None)
@given(st.integers(min_value=1, max_value=5))
def test_watchdog_never_leaves_zombies(n_fires):
    procs = []
    wds = []
    for _ in range(n_fires):
        p = spawn_sleeper(10.0)
        procs.append(p)
        wds.append(WallDeadlineWatchdog(p.pid, 0.1))
        
    for p in procs:
        p.wait()
        
    for w in wds:
        w.thread.join()
        
    try:
        pid, status = os.waitpid(-1, os.WNOHANG)
        assert pid == 0, f"Found zombie child process {pid}"
    except ChildProcessError:
        pass # OK

def test_rlimit_cpu_unaffected_by_watchdog():
    # CPU bound code that runs for 5s of CPU time
    sb = Sandbox(SandboxConfig(cpu_time_limit_seconds=1, timeout_per_input_ms=10000))
    code = textwrap.dedent("""
        def f():
            while True:
                pass
    """)
    result = sb.execute(code, "f")
    assert result.success is False
    assert result.timed_out is True
    assert "killed by CPU time limit" in result.exception_message

def test_cancel_is_thread_safe():
    called = []
    def on_expire(pid):
        called.append(pid)
        
    proc = spawn_sleeper(10.0)
    wd = WallDeadlineWatchdog(proc.pid, 5.0, on_expire)
    
    def cancel_worker():
        wd.cancel()
        
    threads = [threading.Thread(target=cancel_worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
        
    wd.thread.join()
    assert len(called) == 0
    proc.kill()
    proc.wait()
