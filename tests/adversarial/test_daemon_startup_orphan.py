"""Adversarial oracle for PHASE_DAEMON_STARTUP_ORPHAN
(DAEMON-STARTUP-ORPHAN, REV18 §3 Phase 1 item 3).

Intended in-repo dest: tests/adversarial/test_daemon_startup_orphan.py
"""
import os
import pathlib
import signal
import pytest
import harness.autowork_daemon as ad


def test_resume_or_kill_orphaned_workers_direct(tmp_path, monkeypatch):
    # Ensure the helper exists. On HEAD, this will raise AttributeError (RED).
    helper = getattr(ad, '_resume_or_kill_orphaned_workers')

    state_dir = tmp_path / 'state'
    rdir = ad._running_dir(state_dir)
    rdir.mkdir(parents=True)

    # Seed pidfile for a LIVE pid
    live_pid = 12345
    live_file = rdir / 'task_live.pid'
    live_file.write_text(str(live_pid), encoding='utf-8')

    # Seed pidfile for a DEAD pid
    dead_pid = 67890
    dead_file = rdir / 'task_dead.pid'
    dead_file.write_text(str(dead_pid), encoding='utf-8')

    # Seed pidfile for an INVALID pid file (e.g. empty or non-numeric)
    invalid_file = rdir / 'task_invalid.pid'
    invalid_file.write_text("not_a_pid", encoding='utf-8')

    kill_calls = []
    telemetry_calls = []

    def mock_kill(pid, sig):
        kill_calls.append((pid, sig))
        if sig == 0:
            if pid == live_pid:
                return None  # live
            raise ProcessLookupError()  # dead
        elif sig == signal.SIGCONT:
            if pid == live_pid:
                return None
        return None

    monkeypatch.setattr(os, 'kill', mock_kill)
    monkeypatch.setattr(ad, '_emit_telemetry', lambda sd, tid, ev, det='': telemetry_calls.append((tid, ev, det)))

    # Call the helper
    helper(state_dir, {})

    # Check assertions
    assert (live_pid, 0) in kill_calls
    assert (live_pid, signal.SIGCONT) in kill_calls
    assert (dead_pid, 0) in kill_calls
    assert live_file.exists()
    assert not dead_file.exists()
    assert not invalid_file.exists()
    
    # Assert telemetry was emitted for the resumed orphan
    assert ('task_live', 'resume_orphan', f'pid={live_pid}') in telemetry_calls or \
           ('task_live', 'resume', f'pid={live_pid}') in telemetry_calls


def test_run_daemon_integration(tmp_path, monkeypatch):
    # This verifies that run_daemon actually invokes the sweep on startup.
    # On HEAD, this will not run the sweep, so the dead pid file will not be deleted,
    # and the live pid file will not be resumed.
    
    state_dir = tmp_path / 'state'
    repo_root = tmp_path / 'repo'
    repo_root.mkdir()
    state_dir.mkdir()
    
    rdir = ad._running_dir(state_dir)
    rdir.mkdir(parents=True)

    # Seed pidfile for a LIVE pid
    live_pid = 22222
    live_file = rdir / 'task_live.pid'
    live_file.write_text(str(live_pid), encoding='utf-8')

    # Seed pidfile for a DEAD pid
    dead_pid = 33333
    dead_file = rdir / 'task_dead.pid'
    dead_file.write_text(str(dead_pid), encoding='utf-8')

    kill_calls = []
    def mock_kill(pid, sig):
        kill_calls.append((pid, sig))
        if sig == 0:
            if pid == live_pid:
                return None
            raise ProcessLookupError()
        return None

    monkeypatch.setattr(os, 'kill', mock_kill)
    
    # We must ensure that run_daemon exits immediately when it enters the loop.
    # We write the full_stop sentinel.
    full_stop = state_dir / 'control' / 'autowork' / 'full_stop'
    full_stop.parent.mkdir(parents=True, exist_ok=True)
    full_stop.write_text('', encoding='utf-8')

    # We also mock other side effects during run_daemon startup to make it fast & safe
    monkeypatch.setattr(ad, '_install_sigterm_handler', lambda: None)
    monkeypatch.setattr(ad, '_drain_running', lambda *a, **kw: 0)

    # We want to check the state of the pidfiles right as the loop starts,
    # before any shutdown/cleanup runs. We monkeypatch _full_stop_path.
    orig_full_stop_path = ad._full_stop_path
    checked = []
    def mock_full_stop_path(sd):
        # This runs at the start of the while loop in run_daemon
        checked.append(True)
        assert not dead_file.exists()
        assert live_file.exists()
        assert (live_pid, signal.SIGCONT) in kill_calls
        return orig_full_stop_path(sd)
        
    monkeypatch.setattr(ad, '_full_stop_path', mock_full_stop_path)

    # Check if run_daemon imports successfully and runs.
    # On HEAD, this will either raise AttributeError/NameError,
    # or the assertions in mock_full_stop_path will fail.
    ad.run_daemon(repo_root, state_dir, {})
    
    assert checked == [True]
