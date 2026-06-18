"""RED oracle for the disk reapers of ``harness.state_reconciler``.

This is a *test-authoring* oracle. The disk reapers (orphaned-workdir rmtree,
``impl_progress.jsonl`` compaction, log/drain age-out, ``_autowork_archive``
retention prune) do NOT yet exist on HEAD, so every test below is RED on HEAD
*by design* and turns GREEN only once the reapers land. The suite is also
non-vacuous against the declared ``harness.state_reconciler`` mutant: each test
ties its assertions to a concrete, observable on-disk effect, so a reaper that
drops the path guard, ignores the liveness gate, wipes the ledger, or holds
``git_commit.lock`` across the slow op makes the suite FAIL.

The oracle drives the reapers exclusively through the public
``cleanup_state(root, *, mode='report'|'apply') -> WorkspaceStatus`` surface
over a synthesized ``agent_workroot()`` / state directory in pytest ``tmp_path``
(no live ``state/``, no network). It is hermetic per test.

CONTRACT the implementation must honor (the layout this oracle synthesizes):

* ``agent_workroot(root) -> Path`` -- root under which ``<agent>/<workdir>``
  session dirs live (default convention ``<root>/agent_work``).
* ``external_staging_root(root) -> Path`` -- a PEER dir under
  ``agent_workroot()`` that is NEVER swept (default ``<agent_workroot>/_external_staging``).
* ``list_git_worktrees(root) -> list[str]`` -- registered ``git worktree list``
  paths; a workdir present here is NEVER rmtree'd. (Monkeypatched here.)
* state directory is ``<root>/state`` with ``running/<task_id>.pid`` live-pids,
  ``impl_progress.jsonl`` ledger, ``logs/`` log/drain files; archive is
  ``<root>/_autowork_archive``.
* In ``mode='apply'`` the slow rmtree/compaction runs while holding
  ``state_reconcile.lock`` and NEVER while holding ``git_commit.lock``.
"""
import importlib
import json
import os
import shutil
import time
from pathlib import Path
import pytest
swr = importlib.import_module('harness.state_reconciler')
UUID8 = 'abcd1234'
PAST = 90 * 24 * 3600
FRESH = 0
_GRACE_NAMES = ('WORKDIR_REAP_GRACE_SEC', '_WORKDIR_REAP_GRACE_SEC', 'ORPHAN_GRACE_SEC', '_ORPHAN_GRACE_SEC', 'REAP_GRACE_SEC')
_LOG_NAMES = ('LOG_AGEOUT_SEC', '_LOG_AGEOUT_SEC', 'LOG_AGE_OUT_SEC', 'DRAIN_AGEOUT_SEC', '_DRAIN_AGEOUT_SEC')
_ARCHIVE_AGE_NAMES = ('ARCHIVE_RETENTION_SEC', '_ARCHIVE_RETENTION_SEC', 'AUTOWORK_ARCHIVE_RETENTION_SEC')
_ARCHIVE_MAX_NAMES = ('ARCHIVE_RETENTION_MAX', '_ARCHIVE_RETENTION_MAX', 'AUTOWORK_ARCHIVE_RETENTION_MAX')
_WORKTREE_NAMES = ('list_git_worktrees', '_list_git_worktrees', 'git_worktree_list', '_git_worktree_list', 'registered_worktrees', '_registered_worktrees', '_worktree_list', 'list_worktrees')

def _agent_workroot(root):
    fn = getattr(swr, 'agent_workroot', None)
    if callable(fn):
        return Path(fn(str(root)))
    return Path(root) / 'agent_work'

def _external_staging_root(root):
    fn = getattr(swr, 'external_staging_root', None)
    if callable(fn):
        return Path(fn(str(root)))
    return _agent_workroot(root) / '_external_staging'

def _state_dir(root):
    return Path(root) / 'state'

def _running_dir(root):
    return _state_dir(root) / 'control' / 'autowork' / 'running'

def _ledger_path(root):
    return _state_dir(root) / 'impl_progress.jsonl'

def _slug(agent, task_id, n=1, uuid=UUID8):
    """A session slug ``<agent>-r<n>-<task_id>-<uuid8>`` parseable by the module."""
    return '%s-r%d-%s-%s' % (agent, n, task_id, uuid)

def _mkworkdir(parent, agent, task_id, *, age):
    """Create ``<parent>/<slug>`` with a marker, then stamp its mtime last."""
    d = parent / _slug(agent, task_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / 'workspace_marker').write_text('x', encoding='utf-8')
    t = time.time() - age
    os.utime(d, (t, t))
    return d

def _write_live_pid(root, task_id):
    rd = _running_dir(root)
    rd.mkdir(parents=True, exist_ok=True)
    (rd / ('%s.pid' % task_id)).write_text(str(os.getpid()), encoding='utf-8')

def _ensure_state(root):
    _running_dir(root).mkdir(parents=True, exist_ok=True)

def _patch_windows(monkeypatch):
    for name in _GRACE_NAMES:
        monkeypatch.setattr(swr, name, 3600.0, raising=False)
    for name in _LOG_NAMES:
        monkeypatch.setattr(swr, name, 3600.0, raising=False)
    for name in _ARCHIVE_AGE_NAMES:
        monkeypatch.setattr(swr, name, 3600.0, raising=False)
    for name in _ARCHIVE_MAX_NAMES:
        monkeypatch.setattr(swr, name, 2, raising=False)

def _patch_worktrees(monkeypatch, paths):
    registered = [str(p) for p in paths]
    for name in _WORKTREE_NAMES:
        monkeypatch.setattr(swr, name, lambda *a, **k: list(registered), raising=False)

def _apply(root):
    return swr.cleanup_state(str(root), mode='apply')

def _read_rows(path):
    rows = []
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        rows.append(obj)
    return rows

def _task_ids(rows):
    return {r.get('task_id') for r in rows if isinstance(r, dict)}

def test_orphaned_workdir_rmtreed_when_no_live_pid_and_mtime_past_grace(tmp_path, monkeypatch):
    """The ONE true delete: an orphaned, past-grace workdir with no exact live
    pid is rmtree'd under apply mode."""
    root = tmp_path / 'ws'
    awr = _agent_workroot(root)
    agent = awr / 'claude'
    orphan = _mkworkdir(agent, 'claude', 'orphantask', age=PAST)
    _ensure_state(root)
    _patch_windows(monkeypatch)
    _patch_worktrees(monkeypatch, [])
    assert orphan.exists()
    _apply(root)
    assert not orphan.exists(), "a past-grace orphan workdir with no exact live running/*.pid must be rmtree'd by the disk reaper"

def test_external_staging_root_and_worktree_listed_dirs_never_rmtreed(tmp_path, monkeypatch):
    """Path guard: dirs at/under external_staging_root() and dirs registered in
    `git worktree list` survive; a plain orphan (positive control) is deleted."""
    root = tmp_path / 'ws'
    awr = _agent_workroot(root)
    esr = _external_staging_root(root)
    staged = _mkworkdir(esr, 'claude', 'stagedtask', age=PAST)
    wt = _mkworkdir(awr / 'claude', 'claude', 'wttask', age=PAST)
    orphan = _mkworkdir(awr / 'claude', 'claude', 'controlorphan', age=PAST)
    _ensure_state(root)
    _patch_windows(monkeypatch)
    _patch_worktrees(monkeypatch, [wt])
    _apply(root)
    assert orphan.exists() is False, 'positive control: plain orphan must be reaped'
    assert staged.exists(), "a dir at/under external_staging_root() must NEVER be rmtree'd"
    assert wt.exists(), "a dir present in `git worktree list` must NEVER be rmtree'd"

def test_exact_task_id_pid_match_and_within_grace_block_delete(tmp_path, monkeypatch):
    """Liveness + grace gate: an exact-task_id live pid match and a
    within-grace mtime each BLOCK deletion; a control orphan is still reaped."""
    root = tmp_path / 'ws'
    agent = _agent_workroot(root) / 'claude'
    blocked = _mkworkdir(agent, 'claude', 'blockedtask', age=PAST)
    fresh = _mkworkdir(agent, 'claude', 'freshtask', age=FRESH)
    control = _mkworkdir(agent, 'claude', 'goneorphan', age=PAST)
    _ensure_state(root)
    _write_live_pid(root, 'blockedtask')
    _patch_windows(monkeypatch)
    _patch_worktrees(monkeypatch, [])
    _apply(root)
    assert control.exists() is False, 'positive control: plain orphan must be reaped'
    assert blocked.exists(), 'a workdir whose parsed task_id EXACTLY equals a live running/*.pid must NOT be deleted'
    assert fresh.exists(), 'a workdir within the grace window (mtime <= grace) must NOT be deleted'

def test_impl_progress_compaction_locked_atomic_never_wiped(tmp_path, monkeypatch):
    """Ledger compaction keeps consumer-allowlist + unrelated rows, drops a
    malformed line, rewrites atomically (temp + os.replace => new inode), and
    NEVER wipes the ledger."""
    root = tmp_path / 'ws'
    _ensure_state(root)
    ledger = _ledger_path(root)
    lines = [json.dumps({'phase': 'accepted', 'task_id': 'keepacc', 'commit_sha': 'deadbeef'}), 'THIS_IS_NOT_JSON_AT_ALL{', json.dumps({'event': 'task_blocked', 'task_id': 'keepblock'}), json.dumps({'event': 'note', 'task_id': 'unrelated'})]
    ledger.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    ino_before = os.stat(str(ledger)).st_ino
    _patch_windows(monkeypatch)
    _patch_worktrees(monkeypatch, [])
    _apply(root)
    assert ledger.exists(), 'compaction must NEVER delete the ledger'
    text = ledger.read_text(encoding='utf-8')
    assert text.strip(), 'compaction must NEVER wipe the ledger to empty'
    assert 'THIS_IS_NOT_JSON_AT_ALL' not in text, 'malformed line must be dropped'
    ids = _task_ids(_read_rows(ledger))
    assert {'keepacc', 'keepblock', 'unrelated'} <= ids, 'consumer-allowlist rows AND preexisting unrelated rows must survive compaction'
    assert os.stat(str(ledger)).st_ino != ino_before, 'compaction must be temp-file + os.replace atomic (inode must change), not an in-place truncating write'

def test_log_ageout_and_autowork_archive_retention_prune(tmp_path, monkeypatch):
    """log/drain age-out removes only logs older than the window; archive
    retention prune removes only stale archive entries, keeping the rest."""
    root = tmp_path / 'ws'
    _ensure_state(root)
    logs_dir = _state_dir(root) / 'logs'
    logs_dir.mkdir(parents=True, exist_ok=True)
    old_log = logs_dir / 'old.log'
    new_log = logs_dir / 'new.log'
    old_log.write_text('old', encoding='utf-8')
    new_log.write_text('new', encoding='utf-8')
    os.utime(str(old_log), (time.time() - PAST, time.time() - PAST))
    os.utime(str(new_log), (time.time(), time.time()))
    archive = Path(root) / '_autowork_archive'
    archive.mkdir(parents=True, exist_ok=True)
    stale_entries = []
    for i in range(3):
        p = archive / ('stale_%d.json' % i)
        p.write_text('{}', encoding='utf-8')
        os.utime(str(p), (time.time() - PAST, time.time() - PAST))
        stale_entries.append(p)
    fresh_entries = []
    for i in range(2):
        p = archive / ('fresh_%d.json' % i)
        p.write_text('{}', encoding='utf-8')
        os.utime(str(p), (time.time(), time.time()))
        fresh_entries.append(p)
    _patch_windows(monkeypatch)
    _patch_worktrees(monkeypatch, [])
    _apply(root)
    assert not old_log.exists(), 'a log older than the age-out window must be removed'
    assert new_log.exists(), 'a log within the age-out window must be kept'
    assert all((not p.exists() for p in stale_entries)), 'archive entries beyond the retention bound must be pruned'
    assert all((p.exists() for p in fresh_entries)), 'archive entries within the retention bound must be kept'

def test_slow_op_under_state_reconcile_lock_never_git_commit_lock(tmp_path, monkeypatch):
    """The slow rmtree runs while holding state_reconcile.lock and NEVER while
    holding git_commit.lock (FAILS the mutant that drops/inverts the guard)."""
    root = tmp_path / 'ws'
    agent = _agent_workroot(root) / 'claude'
    orphan = _mkworkdir(agent, 'claude', 'lockorphan', age=PAST)
    _ensure_state(root)
    _patch_windows(monkeypatch)
    _patch_worktrees(monkeypatch, [])
    state_lock = _state_dir(root) / swr.LOCK_FILENAME
    records = []
    real_rmtree = shutil.rmtree

    def _spy_rmtree(path, *args, **kwargs):
        held_reconcile = os.path.exists(str(state_lock))
        git_commit_locks = [str(p) for p in Path(root).rglob('git_commit*.lock')]
        records.append((str(path), held_reconcile, git_commit_locks))
        return real_rmtree(path, *args, **kwargs)
    monkeypatch.setattr(shutil, 'rmtree', _spy_rmtree)
    _apply(root)
    orphan_calls = [r for r in records if 'lockorphan' in r[0]]
    assert orphan_calls, 'the reaper must perform the slow rmtree of the orphan workdir'
    for path, held_reconcile, git_commit_locks in orphan_calls:
        assert held_reconcile, 'the slow rmtree must run while holding state_reconcile.lock'
        assert not git_commit_locks, 'the slow rmtree must NEVER run while holding git_commit.lock'

def test_substring_task_id_not_exact_still_eligible_for_delete(tmp_path, monkeypatch):
    """A workdir task_id that is only a SUBSTRING (not exact) of a live pid's
    task_id is still eligible for reaping (gating is exact equality)."""
    root = tmp_path / 'ws'
    agent = _agent_workroot(root) / 'claude'
    sub = _mkworkdir(agent, 'claude', 't1', age=PAST)
    _ensure_state(root)
    _write_live_pid(root, 't12')
    _patch_windows(monkeypatch)
    _patch_worktrees(monkeypatch, [])
    _apply(root)
    assert not sub.exists(), "task_id 't1' must NOT be shielded by a live pid for 't12' -- the liveness gate is exact-task_id equality, not substring"

def test_malformed_ledger_line_skipped_fail_closed_not_wiped(tmp_path, monkeypatch):
    """A malformed / non-dict ledger line is skipped fail-closed; compaction
    still completes and the ledger is never wiped."""
    root = tmp_path / 'ws'
    _ensure_state(root)
    ledger = _ledger_path(root)
    lines = [json.dumps({'phase': 'accepted', 'task_id': 'survivor_a', 'commit_sha': 'cafe'}), '{not valid json', '[1, 2, 3]', json.dumps({'event': 'note', 'task_id': 'survivor_b'})]
    ledger.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    ino_before = os.stat(str(ledger)).st_ino
    _patch_windows(monkeypatch)
    _patch_worktrees(monkeypatch, [])
    _apply(root)
    assert ledger.exists()
    text = ledger.read_text(encoding='utf-8')
    assert text.strip(), 'a malformed line must NOT cause the ledger to be wiped'
    assert '{not valid json' not in text, 'malformed line must be skipped'
    rows = _read_rows(ledger)
    assert all((isinstance(r, dict) for r in rows)), 'non-dict rows must be dropped'
    assert {'survivor_a', 'survivor_b'} <= _task_ids(rows), 'unrelated valid rows must survive even when a malformed line is present'
    assert os.stat(str(ledger)).st_ino != ino_before, 'compaction must still complete atomically (inode change) despite the bad line'

def test_reaper_idempotent_second_run_no_change(tmp_path, monkeypatch):
    """A second apply over already-reaped state is a no-op: deleted workdirs
    stay gone, survivors stay, and the compacted ledger is unchanged."""
    root = tmp_path / 'ws'
    agent = _agent_workroot(root) / 'claude'
    orphan = _mkworkdir(agent, 'claude', 'idemorphan', age=PAST)
    survivor = _mkworkdir(agent, 'claude', 'idemfresh', age=FRESH)
    _ensure_state(root)
    ledger = _ledger_path(root)
    ledger.write_text('\n'.join([json.dumps({'phase': 'accepted', 'task_id': 'idemkeep', 'commit_sha': 'feed'}), 'NOT_JSON_LINE', json.dumps({'event': 'note', 'task_id': 'idemnote'})]) + '\n', encoding='utf-8')
    _patch_windows(monkeypatch)
    _patch_worktrees(monkeypatch, [])
    _apply(root)
    assert not orphan.exists(), 'first apply must reap the orphan'
    assert survivor.exists(), 'first apply must keep the within-grace survivor'
    text_after_first = ledger.read_text(encoding='utf-8')
    assert 'NOT_JSON_LINE' not in text_after_first
    _apply(root)
    assert not orphan.exists(), 'second apply must not resurrect or error on the deleted orphan'
    assert survivor.exists(), 'second apply must still keep the survivor'
    assert ledger.read_text(encoding='utf-8') == text_after_first, 'a second apply over an already-compacted ledger must produce no further change'