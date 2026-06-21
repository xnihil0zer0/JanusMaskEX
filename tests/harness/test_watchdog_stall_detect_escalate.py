"""Pre-commit RED oracle for the daemon stall watchdog in
``harness.state_reconciler``.

This is a TEST FILE (a verification oracle), authored *before* the watchdog
implementation lands (the TDD red phase). It pins the observable contract of
the new ``harness.state_reconciler.detect_and_heal_stalls`` entry point and its
live wiring into ``reap_orphaned_workdirs``. Until the implementation exists
these tests are RED (the symbol is absent / the behaviour is not wired); once
the watchdog is implemented to this contract they go GREEN, and any mutant that
breaks detection, self-heal, escalation, the wiring edge, or the fail-safe
default-off gate turns them RED again.

Assumed contract (the spec this oracle enforces)
------------------------------------------------
* Running pidfiles live under
  ``<root>/state/control/autowork/running/<task_id>.pid`` (the canonical
  ``_running_dir``) and hold a single integer pid.
* Progress is recorded in the shared JSONL ledger
  ``<root>/state/impl_progress.jsonl``; each row is a JSON object carrying a
  string ``task_id`` and an ISO-8601 ``ts`` (``%Y-%m-%dT%H:%M:%SZ``).
* A *live_idle stall* is confirmed for ``task_id`` iff a running pidfile names a
  LIVE pid (``os.kill(pid, 0)`` does not raise ``ESRCH``; ``EPERM`` counts as
  live -- fail-closed) AND the newest parseable ledger row for that task is
  older than the idle grace. Absent that evidence -- a missing ledger,
  unparseable rows, or only fresh rows -- the watchdog is fail-safe and takes NO
  action.
* ``detect_and_heal_stalls(root, *, now=None)`` is gated OFF by default and is
  only armed when the environment variable ``JM_WATCHDOG_ENABLED`` is truthy
  (``"1"``). Disabled, it is a pure no-op (touches no files).
* Self-heal clears the stalled running pidfile (the processing claim) so
  dispatch can re-pick the task; the progress ledger itself is preserved.
* After a bounded number of recurring stall/heal retries the watchdog escalates
  by writing a JSON marker at
  ``<root>/state/control/autowork/watchdog/escalation_<task_id>.json``.
* ``reap_orphaned_workdirs`` invokes the module-global ``detect_and_heal_stalls``
  as part of its sweep (the live wiring edge), so it can be substituted in
  tests.
"""
import datetime
import errno
import json
import os
import time
from pathlib import Path
import pytest
state_reconciler = pytest.importorskip('harness.state_reconciler')
WATCHDOG_ENV = 'JM_WATCHDOG_ENABLED'
STALE_AGE = 10 * 365 * 24 * 3600
MAX_ESCALATION_CYCLES = 16

def _running_dir(root):
    return Path(root) / 'state' / 'control' / 'autowork' / 'running'

def _watchdog_dir(root):
    return Path(root) / 'state' / 'control' / 'autowork' / 'watchdog'

def _ledger_path(root):
    return Path(root) / 'state' / 'impl_progress.jsonl'

def _escalation_path(root, task_id):
    return _watchdog_dir(root) / ('escalation_%s.json' % (task_id,))

def _iso(epoch):
    return datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

def _write_pidfile(root, task_id, pid):
    rd = _running_dir(root)
    rd.mkdir(parents=True, exist_ok=True)
    p = rd / ('%s.pid' % (task_id,))
    p.write_text(str(pid), encoding='utf-8')
    return p

def _ledger_row(task_id, ts_epoch, **extra):
    row = {'task_id': task_id, 'ts': _iso(ts_epoch), 'phase': 'impl', 'event': 'progress'}
    row.update(extra)
    return row

def _write_ledger(root, rows):
    lp = _ledger_path(root)
    lp.parent.mkdir(parents=True, exist_ok=True)
    lp.write_text(''.join((json.dumps(r) + '\n' for r in rows)), encoding='utf-8')
    return lp

def _make_stall(root, task_id, now, *, pid=None):
    """Synthesize a confirmed live_idle stall: live pidfile + stale ledger row."""
    pid = os.getpid() if pid is None else pid
    pidfile = _write_pidfile(root, task_id, pid)
    ledger = _write_ledger(root, [_ledger_row(task_id, now - STALE_AGE)])
    return (pidfile, ledger)

def _enable(monkeypatch):
    monkeypatch.setenv(WATCHDOG_ENV, '1')

def _disable(monkeypatch):
    monkeypatch.delenv(WATCHDOG_ENV, raising=False)

def _heal_ids(result):
    """Best-effort extraction of the set of task ids the sweep reported acting on.

    Used only as an *additional* (conditional) signal -- the load-bearing
    assertions in every test are real on-disk side effects, not this return
    value -- so a differently shaped return cannot make a test vacuously pass.
    """
    ids = set()
    if result is None:
        return ids
    if isinstance(result, dict):
        for key in ('healed', 'requeued', 'cleared', 'stalled', 'detected'):
            val = result.get(key)
            if isinstance(val, (list, tuple, set)):
                ids.update((str(v) for v in val))
    elif isinstance(result, (list, tuple, set)):
        ids.update((str(v) for v in result))
    return ids

@pytest.fixture
def root(tmp_path, monkeypatch):
    """Isolated workspace root with the canonical running-pidfile dir present.

    The root is a child of ``tmp_path`` so the sibling agent-workroot the reaper
    derives also lands inside the tmp sandbox. The watchdog gate is forced to its
    default-off baseline here; any test that needs it armed must opt in via
    ``_enable``.
    """
    r = tmp_path / 'repo'
    _running_dir(r).mkdir(parents=True, exist_ok=True)
    monkeypatch.delenv(WATCHDOG_ENV, raising=False)
    return r

def test_detects_live_idle_stall(root, monkeypatch):
    _enable(monkeypatch)
    now = time.time()
    stall_pid = _write_pidfile(root, 'stall-task', os.getpid())
    fresh_pid = _write_pidfile(root, 'fresh-task', os.getpid())
    _write_ledger(root, [_ledger_row('stall-task', now - STALE_AGE), _ledger_row('fresh-task', now)])
    result = state_reconciler.detect_and_heal_stalls(root, now=now)
    assert not stall_pid.exists(), 'live_idle stall must be detected and cleared'
    assert fresh_pid.exists(), 'a live task with fresh progress is not a stall'
    healed = _heal_ids(result)
    if healed:
        assert 'stall-task' in healed
        assert 'fresh-task' not in healed

def test_self_heals_requeues(root, monkeypatch):
    _enable(monkeypatch)
    now = time.time()
    pidfile, ledger = _make_stall(root, 'heal-task', now)
    assert pidfile.exists()
    state_reconciler.detect_and_heal_stalls(root, now=now)
    assert not pidfile.exists(), 'self-heal must clear the running pidfile claim'
    assert ledger.exists(), 'self-heal must not destroy the progress ledger'
    assert not _escalation_path(root, 'heal-task').exists()

def test_escalates_after_bounded_retries(root, monkeypatch):
    _enable(monkeypatch)
    now = time.time()
    tid = 'escalate-task'
    marker = _escalation_path(root, tid)
    escalated_on = None
    for cycle in range(MAX_ESCALATION_CYCLES):
        _write_pidfile(root, tid, os.getpid())
        _write_ledger(root, [_ledger_row(tid, now - STALE_AGE)])
        state_reconciler.detect_and_heal_stalls(root, now=now)
        if marker.exists():
            escalated_on = cycle
            break
    assert marker.exists(), 'recurring live_idle stalls must escalate after bounded retries'
    assert escalated_on is not None and escalated_on >= 1
    assert marker.parent == _watchdog_dir(root)
    data = json.loads(marker.read_text(encoding='utf-8'))
    assert isinstance(data, dict)
    assert tid in json.dumps(data), 'escalation marker must reference the task id'

def test_reap_orphaned_workdirs_wiring_edge(root, monkeypatch):
    monkeypatch.setattr(state_reconciler, 'git_worktree_list', lambda *a, **k: [], raising=True)
    aw = state_reconciler.agent_workroot(root)
    aw.mkdir(parents=True, exist_ok=True)
    calls = []

    def _spy(*args, **kwargs):
        calls.append((args, kwargs))
        return {'healed': [], 'escalated': []}
    monkeypatch.setattr(state_reconciler, 'detect_and_heal_stalls', _spy, raising=False)
    state_reconciler.reap_orphaned_workdirs(root)
    assert calls, 'reap_orphaned_workdirs must invoke detect_and_heal_stalls (wiring edge)'
    passed = calls[0][0][0] if calls[0][0] else calls[0][1].get('root')
    assert passed is not None
    assert os.path.realpath(str(passed)) == os.path.realpath(str(root))

def test_failsafe_default_off(root, monkeypatch):
    _disable(monkeypatch)
    now = time.time()
    tid = 'failsafe-task'
    pidfile, ledger = _make_stall(root, tid, now)
    state_reconciler.detect_and_heal_stalls(root, now=now)
    assert pidfile.exists(), 'disabled watchdog must not clear the claim'
    assert ledger.exists()
    assert not _escalation_path(root, tid).exists()
    _enable(monkeypatch)
    state_reconciler.detect_and_heal_stalls(root, now=now)
    assert not pidfile.exists(), 'armed watchdog must clear the stalled claim'

def test_detect_and_heal_stalls_ignores_fresh_progress(root, monkeypatch):
    _enable(monkeypatch)
    now = time.time()
    pidfile = _write_pidfile(root, 'busy-task', os.getpid())
    _write_ledger(root, [_ledger_row('busy-task', now)])
    state_reconciler.detect_and_heal_stalls(root, now=now)
    assert pidfile.exists(), 'a live task with fresh progress is not idle'
    assert not _escalation_path(root, 'busy-task').exists()

def test_detect_and_heal_stalls_missing_ledger_failsafe(root, monkeypatch):
    _enable(monkeypatch)
    now = time.time()
    pidfile = _write_pidfile(root, 'noledger-task', os.getpid())
    assert not _ledger_path(root).exists()
    state_reconciler.detect_and_heal_stalls(root, now=now)
    assert pidfile.exists(), 'missing ledger must not trigger a destructive heal'
    assert not _escalation_path(root, 'noledger-task').exists()

def test_detect_and_heal_stalls_corrupted_ledger_failsafe(root, monkeypatch):
    _enable(monkeypatch)
    now = time.time()
    pidfile = _write_pidfile(root, 'corrupt-task', os.getpid())
    lp = _ledger_path(root)
    lp.parent.mkdir(parents=True, exist_ok=True)
    lp.write_text('{not valid json\nnot-json-at-all\n[]\n', encoding='utf-8')
    state_reconciler.detect_and_heal_stalls(root, now=now)
    assert pidfile.exists(), 'corrupted ledger must not trigger a destructive heal'
    assert not _escalation_path(root, 'corrupt-task').exists()

def test_detect_and_heal_stalls_permission_error_failclosed(root, monkeypatch):
    _enable(monkeypatch)
    now = time.time()
    tid = 'eperm-task'
    fake_pid = 987654
    pidfile = _write_pidfile(root, tid, fake_pid)
    _write_ledger(root, [_ledger_row(tid, now - STALE_AGE)])
    real_kill = os.kill

    def _fake_kill(pid, sig, *a, **k):
        if int(pid) == fake_pid:
            raise PermissionError(errno.EPERM, 'Operation not permitted')
        return real_kill(pid, sig, *a, **k)
    monkeypatch.setattr(os, 'kill', _fake_kill, raising=True)
    state_reconciler.detect_and_heal_stalls(root, now=now)
    assert not pidfile.exists(), 'EPERM must count as live and the stall must heal'

def test_detect_and_heal_stalls_dead_pid_not_healed(root, monkeypatch):
    _enable(monkeypatch)
    now = time.time()
    tid = 'dead-task'
    fake_pid = 987655
    pidfile = _write_pidfile(root, tid, fake_pid)
    _write_ledger(root, [_ledger_row(tid, now - STALE_AGE)])
    real_kill = os.kill

    def _fake_kill(pid, sig, *a, **k):
        if int(pid) == fake_pid:
            raise ProcessLookupError(errno.ESRCH, 'No such process')
        return real_kill(pid, sig, *a, **k)
    monkeypatch.setattr(os, 'kill', _fake_kill, raising=True)
    state_reconciler.detect_and_heal_stalls(root, now=now)
    assert not _escalation_path(root, tid).exists(), 'a dead task must not escalate'
    assert pidfile.exists(), 'a dead-pid claim is not a live_idle stall'

def test_detect_and_heal_stalls_idempotent_concurrent_sweeps(root, monkeypatch):
    _enable(monkeypatch)
    now = time.time()
    tid = 'race-task'
    pidfile, _ledger = _make_stall(root, tid, now)
    state_reconciler.detect_and_heal_stalls(root, now=now)
    assert not pidfile.exists()
    marker_after_first = _escalation_path(root, tid).exists()
    state_reconciler.detect_and_heal_stalls(root, now=now)
    assert _escalation_path(root, tid).exists() == marker_after_first, 'an idempotent re-sweep must not change escalation state'