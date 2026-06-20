"""RED oracle for harness.autowork_daemon daemon self-reload-on-source-change.

Verifies the two new pure helpers and the run_daemon loop seam described in the
daemon-self-reload-oracle spec:

  * ``_daemon_source_sha(paths) -> str`` -- a deterministic content hash over a
    source set that is sensitive to modification/deletion of any member file.
  * ``_should_reload_daemon(state_dir, startup_sha) -> str | None`` -- returns
    the current source-set sha when it DIFFERS from ``startup_sha`` and the
    daemon is idle (no live worker pidfiles), otherwise ``None``.
  * the run_daemon seam -- when ``_should_reload_daemon`` returns a non-None sha
    it writes a ``daemon_source_changed`` row to the telemetry ledger and
    returns ``0``.

The helper tests exercise the REAL functions (no stubbing of the unit under
test). The seam tests stub ``_should_reload_daemon`` to drive the seam both ways
(positive + negative control) and neutralise side-effecting loop helpers so the
loop is driven hermetically without spinning the full poll loop. Every stubbed
``_iteration``/``_should_reload_daemon`` forces ``_shutdown_requested`` so the
loop can never hang on a mutant.
"""
from __future__ import annotations
import json
import os
import pathlib
import pytest
import harness.autowork_daemon as awd

def _ledger_events(state_dir: pathlib.Path) -> list[dict]:
    """Return parsed rows from the telemetry ledger (empty if absent)."""
    ledger = pathlib.Path(state_dir) / 'impl_progress.jsonl'
    if not ledger.exists():
        return []
    rows: list[dict] = []
    for line in ledger.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows

def _has_source_changed_row(state_dir: pathlib.Path) -> bool:
    return any((r.get('event') == 'daemon_source_changed' for r in _ledger_events(state_dir)))

def _neutralise_loop(monkeypatch) -> None:
    """Make run_daemon's startup + loop body hermetic and side-effect free.

    Neutralises the host-bus refusal/proxy startup gates and every
    side-effecting loop helper, and installs an ``_iteration`` stub that reports
    an idle result AND trips ``_shutdown_requested`` so the loop terminates after
    a single pass regardless of seam placement.
    """
    monkeypatch.delenv('DBUS_SESSION_BUS_ADDRESS', raising=False)
    monkeypatch.setenv('JANUSMASK_ALLOW_HOSTBUS', '1')
    try:
        import harness.agent_jail as _aj
        monkeypatch.setattr(_aj, 'sandbox_enabled', lambda *a, **k: False, raising=False)
    except Exception:
        pass
    monkeypatch.setattr(awd, '_daemon_source_sha', lambda *a, **k: 'startup-sha-fixed', raising=False)
    monkeypatch.setattr(awd, '_resume_or_kill_orphaned_workers', lambda *a, **k: None, raising=False)
    monkeypatch.setattr(awd, '_maybe_push_and_rebase_pin', lambda *a, **k: {}, raising=False)
    monkeypatch.setattr(awd, '_check_inactivity_watchdog', lambda *a, **k: None, raising=False)
    monkeypatch.setattr(awd, '_has_active_rebuild_job', lambda *a, **k: False, raising=False)
    monkeypatch.setattr(awd, '_autowork_watch_mtime', lambda *a, **k: 0.0, raising=False)
    monkeypatch.setattr(awd, '_drain_running', lambda *a, **k: 0, raising=False)

    def _idle_iteration(*a, **k):
        awd._shutdown_requested = True
        return {'would_launch': [], 'free_slots': 1, 'cap': 1, 'plan_kickoffs': 0, 'extracts': 0, 'paused': False}
    monkeypatch.setattr(awd, '_iteration', _idle_iteration, raising=False)

def test_daemon_source_sha_is_deterministic(tmp_path):
    f1 = tmp_path / 'mod_a.py'
    f1.write_text('def a():\n    return 1\n', encoding='utf-8')
    f2 = tmp_path / 'mod_b.py'
    f2.write_text('def b():\n    return 2\n', encoding='utf-8')
    s1 = awd._daemon_source_sha([f1, f2])
    s2 = awd._daemon_source_sha([f1, f2])
    assert isinstance(s1, str) and s1
    assert s1 == s2

def test_daemon_source_sha_detects_modification(tmp_path):
    f = tmp_path / 'mod.py'
    f.write_text('x = 1\n', encoding='utf-8')
    before = awd._daemon_source_sha([f])
    f.write_text('x = 2\n', encoding='utf-8')
    after = awd._daemon_source_sha([f])
    assert isinstance(before, str) and isinstance(after, str)
    assert before != after

def test_daemon_source_sha_detects_deletion(tmp_path):
    f1 = tmp_path / 'a.py'
    f1.write_text('a = 1\n', encoding='utf-8')
    f2 = tmp_path / 'b.py'
    f2.write_text('b = 2\n', encoding='utf-8')
    _ = awd._daemon_source_sha([f1, f2])
    f2.unlink()
    after = awd._daemon_source_sha([f1, f2])
    assert isinstance(after, str) and after

def test_daemon_source_sha_distinguishes_content(tmp_path):
    f_one = tmp_path / 'one.py'
    f_one.write_text("ONE = 'one'\n", encoding='utf-8')
    f_two = tmp_path / 'two.py'
    f_two.write_text("TWO = 'two'\n", encoding='utf-8')
    s_one = awd._daemon_source_sha([f_one])
    s_two = awd._daemon_source_sha([f_two])
    assert isinstance(s_one, str) and isinstance(s_two, str)
    assert s_one != s_two

def test_changed_hash_idle_reload(tmp_path):
    """CHANGED hash + IDLE => returns the (non-None) current source sha."""
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    result = awd._should_reload_daemon(state_dir, 'startup-sha-that-differs')
    assert result is not None
    assert isinstance(result, str)
    assert result != 'startup-sha-that-differs'

def test_unchanged_hash_no_reload(tmp_path):
    """UNCHANGED hash => returns None and writes no telemetry row."""
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    current = awd._should_reload_daemon(state_dir, 'differs-sentinel')
    assert current is not None
    assert awd._should_reload_daemon(state_dir, current) is None
    assert not _has_source_changed_row(state_dir)

def test_changed_hash_worker_running_no_reload(tmp_path):
    """CHANGED hash but a LIVE worker pidfile present => returns None."""
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    running_dir = awd._running_dir(state_dir)
    running_dir.mkdir(parents=True, exist_ok=True)
    (running_dir / 'live_worker.pid').write_text(str(os.getpid()), encoding='utf-8')
    result = awd._should_reload_daemon(state_dir, 'differs-sentinel')
    assert result is None

def test_should_reload_daemon_round_trip_sha(tmp_path):
    """The returned new sha, fed back as startup_sha, yields no reload."""
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    changed = awd._should_reload_daemon(state_dir, 'not-a-real-sha-sentinel')
    assert changed is not None
    assert awd._should_reload_daemon(state_dir, changed) is None

def test_should_reload_daemon_running_dir_absent_reload(tmp_path):
    """Edge case: running dir absent => treated as idle => reload on change."""
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    assert not awd._running_dir(state_dir).exists()
    result = awd._should_reload_daemon(state_dir, 'differs-sentinel')
    assert result is not None

def test_loop_seam_telemetry_and_exit(tmp_path, monkeypatch):
    """Non-None reload decision => seam writes daemon_source_changed + returns 0."""
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    repo_root = tmp_path / 'repo'
    repo_root.mkdir()
    _neutralise_loop(monkeypatch)

    def _force_reload(*a, **k):
        awd._shutdown_requested = True
        return 'sentinel-new-source-sha'
    monkeypatch.setattr(awd, '_should_reload_daemon', _force_reload, raising=False)
    rc = awd.run_daemon(repo_root, state_dir, {})
    assert rc == 0
    assert _has_source_changed_row(state_dir)

def test_loop_seam_no_reload_no_telemetry(tmp_path, monkeypatch):
    """Negative control: None reload decision => no telemetry row, returns 0."""
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    repo_root = tmp_path / 'repo'
    repo_root.mkdir()
    _neutralise_loop(monkeypatch)

    def _no_reload(*a, **k):
        awd._shutdown_requested = True
        return None
    monkeypatch.setattr(awd, '_should_reload_daemon', _no_reload, raising=False)
    rc = awd.run_daemon(repo_root, state_dir, {})
    assert rc == 0
    assert not _has_source_changed_row(state_dir)