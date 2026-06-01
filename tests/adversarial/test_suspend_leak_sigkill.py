"""Adversarial oracle for PHASE_SUSPEND_LEAK (DAEMON-SUSPEND-LEAK, REV17 §3 item 6).

Drives the REAL sequential-worker watchdog loop inside
``harness.autowork_daemon._iteration`` (modeled on the existing
``test_watchdog_timeout_reads_config`` in tests/test_autowork_daemon.py).

Test A (RED on HEAD a4fbbab, GREEN after fix): an over-aged (>300s) suspended
pid must be sent signal.SIGKILL (not signal.SIGTERM) by the watchdog, because a
T-stopped process never delivers a queued SIGTERM and the pid is then discarded
from _suspended_pids (so it would never get a later SIGCONT). RED today because
HEAD sends SIGTERM.

Test B (positive control, GREEN before and after): a suspended pid whose
suspension age is < 300s is NOT signalled by the watchdog; it stays in
_suspended_pids and is later SIGCONT'd by resume_parallel_workers.
"""
import pathlib
import signal
import subprocess
import pytest
import harness.autowork_daemon as ad


def _drive_watchdog_once(tmp_path: pathlib.Path, monkeypatch, suspended: dict[int, float], now: float = 100000.0) -> list[tuple[int, int]]:
    """Run _iteration's sequential branch far enough to execute the watchdog
    loop exactly once with the given suspended pids/start-times, capturing every
    (pid, signal) sent via the daemon's os.kill. NO real process spawn."""
    # one dispatchable task -> sequential (requires_claude) branch
    monkeypatch.setattr(ad, '_decide', lambda *args: ([{'task_id': 'test-task', 'files_touched': []}], False, 1))

    # MockProc: poll() returns None on the first call (enter loop body once),
    # then non-None to exit the watchdog loop on the next iteration.
    poll_calls = {'n': 0}

    class MockProc:
        pid = 12345

        def poll(self):
            poll_calls['n'] += 1
            return None if poll_calls['n'] <= 1 else 0

        def wait(self):
            return 0

    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **kw: MockProc())
    monkeypatch.setattr(ad, '_kill_process_group', lambda sd, tid, proc: None)
    monkeypatch.setattr(ad, '_write_pidfile', lambda *a: None)
    monkeypatch.setattr(ad, '_auto_promote', lambda *a, **kw: {})
    monkeypatch.setattr(ad, '_watch_rebuild_jobs', lambda *a, **kw: None)
    monkeypatch.setattr(ad, '_emit_telemetry', lambda *a, **kw: None)

    # Record (and no-op) every os.kill the daemon issues.
    killed: list[tuple[int, int]] = []
    monkeypatch.setattr(ad.os, 'kill', lambda pid, sig: killed.append((pid, sig)))

    # Frozen clock so now - seq_start == 0 (no timeout) but now - start > 300 for aged pids.
    monkeypatch.setattr(ad.time, 'time', lambda: now)
    monkeypatch.setattr(ad.time, 'sleep', lambda *a: None)

    # Pre-populate the real module globals (suspend_parallel_workers no-ops on an
    # empty state_dir/running, leaving these intact; resume runs in the finally).
    ad._suspended_pids.clear()
    ad._suspension_start_times.clear()
    for spid, start in suspended.items():
        ad._suspended_pids.add(spid)
        ad._suspension_start_times[spid] = start

    repo_root = tmp_path / 'repo'
    state_dir = tmp_path / 'state'
    repo_root.mkdir()
    state_dir.mkdir()

    config = {'synthesis': {'active_agents': ['claude'], 'timeout_seconds': 900}}
    try:
        ad._iteration(repo_root, state_dir, 4, dry_run=False, config=config)
    finally:
        ad._suspended_pids.clear()
        ad._suspension_start_times.clear()
    return killed


def test_suspend_leak_sigkill_aged_pid(tmp_path: pathlib.Path, monkeypatch) -> None:
    """Test A: RED on HEAD (SIGTERM sent), GREEN after fix (SIGKILL sent)."""
    SPID_OLD = 99991
    now = 100000.0
    killed = _drive_watchdog_once(tmp_path, monkeypatch, {SPID_OLD: now - 400.0}, now=now)

    # Over-aged suspended pid must be SIGKILL'd, never SIGTERM'd, by the watchdog.
    assert (SPID_OLD, signal.SIGKILL) in killed, "aged suspended pid should be SIGKILL'd"
    assert (SPID_OLD, signal.SIGTERM) not in killed, "aged suspended pid must NOT be SIGTERM'd (deferred for T-state)"


def test_suspend_leak_nonaged_pid_untouched_by_watchdog(tmp_path: pathlib.Path, monkeypatch) -> None:
    """Test B (positive control): GREEN before and after.

    A suspended pid younger than 300s gets neither SIGTERM nor SIGKILL from the
    watchdog; it survives in _suspended_pids and is SIGCONT'd at resume time."""
    SPID_NEW = 99992
    now = 100000.0
    killed = _drive_watchdog_once(tmp_path, monkeypatch, {SPID_NEW: now - 10.0}, now=now)

    assert (SPID_NEW, signal.SIGKILL) not in killed, "non-aged pid must NOT be SIGKILL'd by watchdog"
    assert (SPID_NEW, signal.SIGTERM) not in killed, "non-aged pid must NOT be SIGTERM'd by watchdog"
    # resume_parallel_workers (real, runs in the finally block) SIGCONTs it.
    assert (SPID_NEW, signal.SIGCONT) in killed, "non-aged pid should be SIGCONT'd during resume"
