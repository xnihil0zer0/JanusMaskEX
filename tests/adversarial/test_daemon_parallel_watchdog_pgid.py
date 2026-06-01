"""Adversarial oracle for PHASE_DAEMON_PARALLEL_WATCHDOG_PGID
(DAEMON-STARTUP-ORPHAN/PARALLEL-WORKER-WATCHDOG/PGID, REV18 §3 Phase 1 item 3 --
the (a)PGID + (b)parallel-watchdog + (d)path-alignment subset; the (c)
startup-orphan sweep is a deferred follow-on).

Intended in-repo dest: tests/adversarial/test_daemon_parallel_watchdog_pgid.py

Drives the REAL functions in harness.autowork_daemon and asserts observable
behavior. All three tests are RED on HEAD (87f6346) for the right reasons:

  test_parallel_spawn_worker_start_new_session  -- RED: _spawn_worker's Popen
      lacks start_new_session=True, so a parallel worker does NOT lead its own
      process group and _kill_process_group cannot group-kill it.

  test_parallel_hang_watchdog_sigkills_aged_pidfile -- RED: the parallel branch
      has NO watchdog; a hung/suspended parallel worker (pidfile mtime older than
      the hang threshold, pid still live) is never reaped.

  test_suspend_uses_running_dir_not_state_dir_running -- RED: suspend_parallel_workers
      reads `state_dir / 'running'` but pidfiles live under
      _running_dir(state_dir) == state_dir/control/autowork/running, so it
      SIGSTOPs nothing when pidfiles are placed in the real location.
"""
import os
import pathlib
import signal
import subprocess

import pytest

import harness.autowork_daemon as ad


# ---------------------------------------------------------------------------
# (a) PGID: parallel _spawn_worker Popen must pass start_new_session=True
# ---------------------------------------------------------------------------
def test_parallel_spawn_worker_start_new_session(tmp_path, monkeypatch):
    captured = {}

    class _FakeProc:
        pid = 4242

    def _fake_popen(cmd, *args, **kwargs):
        captured['cmd'] = cmd
        captured['kwargs'] = kwargs
        return _FakeProc()

    monkeypatch.setattr(subprocess, 'Popen', _fake_popen)
    monkeypatch.setattr(ad, '_emit_telemetry', lambda *a, **kw: None)

    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    pid = ad._spawn_worker(state_dir, 'T-parallel')

    assert pid == 4242
    assert captured.get('kwargs', {}).get('start_new_session') is True, (
        "parallel _spawn_worker Popen must pass start_new_session=True so the "
        "worker leads its own process group (so _kill_process_group can group-kill it)"
    )


# ---------------------------------------------------------------------------
# (b) parallel watchdog: a hung parallel worker (aged pidfile, still alive)
#     must be SIGKILL'd and its pidfile removed by an _iteration sweep
# ---------------------------------------------------------------------------
def test_parallel_hang_watchdog_sigkills_aged_pidfile(tmp_path, monkeypatch):
    repo_root = tmp_path / 'repo'
    state_dir = tmp_path / 'state'
    repo_root.mkdir()
    state_dir.mkdir()

    rdir = ad._running_dir(state_dir)
    rdir.mkdir(parents=True)

    HUNG_PID = 777001
    pidfile = rdir / 'T-hung.pid'
    pidfile.write_text(str(HUNG_PID), encoding='utf-8')
    # Age the pidfile well past any plausible hang threshold (1 hour).
    old = pidfile.stat().st_mtime - 3600
    os.utime(pidfile, (old, old))

    killed = []

    def _fake_kill(pid, sig):
        killed.append((pid, sig))
        # liveness probe (signal 0) must succeed for a "live but hung" worker
        if sig == 0:
            return None
        return None

    monkeypatch.setattr(ad.os, 'kill', _fake_kill)
    # Keep _iteration from doing real dispatch work / spawning anything.
    monkeypatch.setattr(ad, '_reap_running', lambda sd: set())
    monkeypatch.setattr(ad, '_reclaim_orphan_processing', lambda *a, **kw: None)
    monkeypatch.setattr(ad, '_auto_promote', lambda *a, **kw: {})
    monkeypatch.setattr(ad, '_watch_rebuild_jobs', lambda *a, **kw: None)
    monkeypatch.setattr(ad, '_decide', lambda *a: ([], False, 0))
    monkeypatch.setattr(ad, '_emit_telemetry', lambda *a, **kw: None)

    ad._iteration(repo_root, state_dir, 4, dry_run=False, config={})

    assert (HUNG_PID, signal.SIGKILL) in killed, (
        "a parallel worker whose pidfile mtime exceeds the hang threshold (and "
        "whose pid is still alive) must be SIGKILL'd by the _iteration sweep"
    )
    assert not pidfile.exists(), "the hung worker's pidfile must be unlinked after the SIGKILL"


# ---------------------------------------------------------------------------
# (d) path alignment: suspend_parallel_workers must read _running_dir(state_dir)
# ---------------------------------------------------------------------------
def test_suspend_uses_running_dir_not_state_dir_running(tmp_path, monkeypatch):
    state_dir = tmp_path / 'state'
    rdir = ad._running_dir(state_dir)
    rdir.mkdir(parents=True)

    # pidfiles placed in the REAL running dir (_running_dir), where _write_pidfile
    # actually writes them -- NOT the mismatched state_dir/'running'.
    (rdir / 'T-a.pid').write_text('30001', encoding='utf-8')
    (rdir / 'T-b.pid').write_text('30002', encoding='utf-8')

    stopped = []
    monkeypatch.setattr(ad.os, 'kill', lambda pid, sig: stopped.append((pid, sig)))
    monkeypatch.setattr(ad.os, 'getpid', lambda: 99999)
    monkeypatch.setattr(ad, '_emit_telemetry', lambda *a, **kw: None)

    ad._suspended_pids.clear()
    ad._suspension_start_times.clear()
    try:
        # exclude one of the two; the other must be SIGSTOP'd from the real dir.
        ad.suspend_parallel_workers(state_dir, exclude_pid=30001)
    finally:
        cleanup = list(ad._suspended_pids)
        ad._suspended_pids.clear()
        ad._suspension_start_times.clear()

    assert (30002, signal.SIGSTOP) in stopped, (
        "suspend_parallel_workers must read pidfiles from _running_dir(state_dir) "
        "(state_dir/control/autowork/running), where _write_pidfile writes them"
    )
    assert (30001, signal.SIGSTOP) not in stopped
    assert 30002 in cleanup
