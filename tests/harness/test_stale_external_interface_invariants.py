"""RED oracle for ``harness.state_reconciler.prepare_workspace(root)``.

``prepare_workspace`` is the fail-closed EXTERNAL entrypoint / alias over
:func:`harness.state_reconciler.cleanup_state`. It is ABSENT on HEAD, so this
oracle is correctly RED on HEAD (every test errors at the
``prepare_workspace`` call) and is GREEN once the impl lands; it is also
non-vacuous against the declared ``harness.state_reconciler`` mutant.

Contract pinned by this oracle (the impl conforms to it):

``prepare_workspace(root, *, mode='apply') -> WorkspaceStatus``

  Enforces, in order, four INDEPENDENT fail-closed gates BEFORE any
  reclamation or any ``cleanup_state`` work:

    1. ownership  -- module-level predicate ``is_owned(root)`` is consulted;
       a non-owned root is REFUSED (no reclamation, no rmtree).
    2. allowlist  -- module-level predicate ``is_allowlisted(root)``; a
       non-allowlisted root is REFUSED.
    3. dirty (FAIL-CLOSED) -- a root that is NOT a git repository is treated
       as DIRTY and REFUSED *regardless* of what ``target_bootstrap._is_dirty``
       answers (it answers clean/False for a non-git tree -- prepare_workspace
       must NOT trust that). For a git root the gate consults
       ``target_bootstrap._is_dirty(root)``.
    4. STAGED_UNMERGED -- module-level predicate
       ``has_staged_or_unmerged(root)``; staged/unmerged entries are REFUSED
       (escalate, never delete).

  A REFUSED workspace returns a ``WorkspaceStatus`` with ``ready is False``,
  performs NO scoped reclamation, never calls ``cleanup_state`` and leaves
  the tree untouched.

  Once all gates pass it acquires the ONE shared ``state_reconcile.lock``
  (via :func:`state_reconcile_lock`) around the reconcile and performs SCOPED
  staging-worktree reclamation: it verifies siblings are still registered
  (via :func:`git_worktree_list`) and NEVER issues a bare ``git worktree
  prune`` -- a still-registered sibling survives. It then delegates to
  ``cleanup_state(root, mode=mode)`` and returns that ``WorkspaceStatus``
  (report-vs-apply respected).

All tests are hermetic: each builds its own git / non-git roots under
``tmp_path`` with no live ``state/`` and no network.
"""
import contextlib
import os
import subprocess
import types
import pytest
import harness.state_reconciler as sr

def _has_git():
    try:
        subprocess.run(['git', '--version'], capture_output=True)
        return True
    except OSError:
        return False
requires_git = pytest.mark.skipif(not _has_git(), reason='git is not available')

def _same(a, b):
    return os.path.realpath(str(a)) == os.path.realpath(str(b))

def _make_git_root(base, name='repo'):
    """Create a genuinely-clean (committed, no untracked) git root."""
    root = base / name
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(['git', 'init', '-q', str(root)], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(root), 'config', 'user.email', 't@example.invalid'], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(root), 'config', 'user.name', 'tester'], check=True, capture_output=True)
    (root / 'README').write_text('seed\n', encoding='utf-8')
    subprocess.run(['git', '-C', str(root), 'add', 'README'], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(root), 'commit', '-q', '-m', 'init'], check=True, capture_output=True)
    return root

def _pass_all_gates(monkeypatch, *, dirty=False):
    """Make every gate predicate answer 'pass'."""
    monkeypatch.setattr(sr, 'is_owned', lambda root: True, raising=False)
    monkeypatch.setattr(sr, 'is_allowlisted', lambda root: True, raising=False)
    monkeypatch.setattr(sr, 'has_staged_or_unmerged', lambda root: False, raising=False)
    fake_tb = types.SimpleNamespace(_is_dirty=lambda root: dirty)
    monkeypatch.setattr(sr, 'target_bootstrap', fake_tb, raising=False)

def _spy_cleanup_state(monkeypatch):
    """Replace cleanup_state with a recording spy returning a sentinel status."""
    calls = []
    sentinel = sr.WorkspaceStatus(root='SENTINEL', mode='sentinel', products=[])

    def spy(root, *, mode='report'):
        calls.append((str(root), mode))
        return sentinel
    monkeypatch.setattr(sr, 'cleanup_state', spy)
    return (calls, sentinel)

def _spy_lock(monkeypatch):
    """Wrap the real state_reconcile_lock to record acquisition."""
    acquired = []
    real = sr.state_reconcile_lock

    @contextlib.contextmanager
    def wrapper(state_dir, **kw):
        acquired.append(str(state_dir))
        with real(state_dir, **kw) as held:
            yield held
    monkeypatch.setattr(sr, 'state_reconcile_lock', wrapper)
    return acquired

def _spy_subprocess(monkeypatch):
    """Record every argv passed to subprocess.run (delegating to the real run)."""
    calls = []
    real_run = subprocess.run

    def spy(args, *a, **k):
        try:
            calls.append(list(args))
        except TypeError:
            calls.append([args])
        return real_run(args, *a, **k)
    monkeypatch.setattr(subprocess, 'run', spy)
    return calls

def _has_bare_prune(calls):
    for argv in calls:
        if 'worktree' in argv and 'prune' in argv:
            return True
    return False

@requires_git
def test_prepare_workspace_aliases_cleanup_state_behind_gates(tmp_path, monkeypatch):
    root = _make_git_root(tmp_path, 'repo')
    _pass_all_gates(monkeypatch, dirty=False)
    monkeypatch.setattr(sr, 'git_worktree_list', lambda r: [], raising=False)
    calls, sentinel = _spy_cleanup_state(monkeypatch)
    status = sr.prepare_workspace(root, mode='report')
    assert status is sentinel
    assert len(calls) == 1
    captured_root, captured_mode = calls[0]
    assert _same(captured_root, root)
    assert captured_mode == 'report'
    status2 = sr.prepare_workspace(root, mode='apply')
    assert status2 is sentinel
    assert calls[-1][1] == 'apply'

@requires_git
def test_ownership_gate_refuses_non_owned_root_fail_closed(tmp_path, monkeypatch):
    root = _make_git_root(tmp_path, 'repo')
    sentinel_file = root / '_keep_me'
    sentinel_file.write_text('untouched', encoding='utf-8')
    _pass_all_gates(monkeypatch, dirty=False)
    monkeypatch.setattr(sr, 'is_owned', lambda r: False, raising=False)
    monkeypatch.setattr(sr, 'git_worktree_list', lambda r: [], raising=False)
    calls, _ = _spy_cleanup_state(monkeypatch)
    git_calls = _spy_subprocess(monkeypatch)
    status = sr.prepare_workspace(root, mode='apply')
    assert status.ready is False
    assert calls == []
    assert sentinel_file.exists()
    assert not (root / '_autowork_archive').exists()
    assert not _has_bare_prune(git_calls)

@requires_git
def test_allowlist_gate_refuses_non_allowlisted_root(tmp_path, monkeypatch):
    root = _make_git_root(tmp_path, 'repo')
    sentinel_file = root / '_keep_me'
    sentinel_file.write_text('untouched', encoding='utf-8')
    _pass_all_gates(monkeypatch, dirty=False)
    monkeypatch.setattr(sr, 'is_owned', lambda r: True, raising=False)
    monkeypatch.setattr(sr, 'is_allowlisted', lambda r: False, raising=False)
    monkeypatch.setattr(sr, 'git_worktree_list', lambda r: [], raising=False)
    calls, _ = _spy_cleanup_state(monkeypatch)
    git_calls = _spy_subprocess(monkeypatch)
    status = sr.prepare_workspace(root, mode='apply')
    assert status.ready is False
    assert calls == []
    assert sentinel_file.exists()
    assert not (root / '_autowork_archive').exists()
    assert not _has_bare_prune(git_calls)

@requires_git
def test_dirty_gate_fail_closed_non_git_root_treated_dirty_and_refused(tmp_path, monkeypatch):
    nongit = tmp_path / 'plain'
    nongit.mkdir()
    keep = nongit / 'keep'
    keep.write_text('x', encoding='utf-8')
    _pass_all_gates(monkeypatch, dirty=False)
    monkeypatch.setattr(sr, 'git_worktree_list', lambda r: [], raising=False)
    calls, _ = _spy_cleanup_state(monkeypatch)
    status = sr.prepare_workspace(nongit, mode='apply')
    assert status.ready is False
    assert calls == []
    assert keep.exists()
    gitroot = _make_git_root(tmp_path, 'repo')
    status2 = sr.prepare_workspace(gitroot, mode='apply')
    assert calls, 'clean git root should pass the dirty gate and reach cleanup_state'
    assert _same(calls[-1][0], gitroot)
    assert status2 is not None

@requires_git
def test_staged_unmerged_gate_refuses_and_no_reclamation(tmp_path, monkeypatch):
    root = _make_git_root(tmp_path, 'repo')
    _pass_all_gates(monkeypatch, dirty=False)
    monkeypatch.setattr(sr, 'has_staged_or_unmerged', lambda r: True, raising=False)
    monkeypatch.setattr(sr, 'git_worktree_list', lambda r: [], raising=False)
    calls, _ = _spy_cleanup_state(monkeypatch)
    git_calls = _spy_subprocess(monkeypatch)
    status = sr.prepare_workspace(root, mode='apply')
    assert status.ready is False
    assert calls == []
    assert not _has_bare_prune(git_calls)
    assert not (root / '_autowork_archive').exists()

@requires_git
def test_acquires_shared_state_reconcile_lock_and_scoped_reclamation_no_bare_prune(tmp_path, monkeypatch):
    root = _make_git_root(tmp_path, 'repo')
    staging = sr.external_staging_root(root)
    staging.mkdir(parents=True, exist_ok=True)
    sibling = staging / 'sibling-worktree'
    sibling.mkdir()
    (sibling / 'marker').write_text('alive', encoding='utf-8')
    _pass_all_gates(monkeypatch)
    monkeypatch.setattr(sr, 'git_worktree_list', lambda r: [str(sibling)], raising=False)
    _spy_cleanup_state(monkeypatch)
    acquired = _spy_lock(monkeypatch)
    git_calls = _spy_subprocess(monkeypatch)
    sr.prepare_workspace(root, mode='apply')
    assert acquired, 'state_reconcile.lock was not acquired'
    assert _same(acquired[0], root / 'state')
    assert not _has_bare_prune(git_calls), git_calls
    assert sibling.exists() and (sibling / 'marker').exists()

@requires_git
def test_clean_owned_allowlisted_git_root_passes_all_gates(tmp_path, monkeypatch):
    root = _make_git_root(tmp_path, 'repo')
    _pass_all_gates(monkeypatch, dirty=False)
    monkeypatch.setattr(sr, 'git_worktree_list', lambda r: [], raising=False)
    calls, sentinel = _spy_cleanup_state(monkeypatch)
    status = sr.prepare_workspace(root, mode='apply')
    assert status is sentinel
    assert len(calls) == 1
    assert _same(calls[0][0], root)
    assert calls[0][1] == 'apply'

@requires_git
def test_registered_sibling_worktree_survives_scoped_reclamation(tmp_path, monkeypatch):
    root = _make_git_root(tmp_path, 'repo')
    staging = sr.external_staging_root(root)
    staging.mkdir(parents=True, exist_ok=True)
    sibling = staging / 'still-registered'
    sibling.mkdir()
    (sibling / 'keep').write_text('x', encoding='utf-8')
    _pass_all_gates(monkeypatch)
    monkeypatch.setattr(sr, 'git_worktree_list', lambda r: [str(sibling)], raising=False)
    git_calls = _spy_subprocess(monkeypatch)
    sr.prepare_workspace(root, mode='apply')
    assert sibling.exists() and (sibling / 'keep').exists()
    assert not _has_bare_prune(git_calls)

@requires_git
def test_prepare_workspace_idempotent_second_run_no_change(tmp_path, monkeypatch):
    root = _make_git_root(tmp_path, 'repo')
    staging = sr.external_staging_root(root)
    staging.mkdir(parents=True, exist_ok=True)
    sibling = staging / 'reg'
    sibling.mkdir()
    (sibling / 'k').write_text('x', encoding='utf-8')
    _pass_all_gates(monkeypatch)
    monkeypatch.setattr(sr, 'git_worktree_list', lambda r: [str(sibling)], raising=False)
    s1 = sr.prepare_workspace(root, mode='apply')
    s2 = sr.prepare_workspace(root, mode='apply')
    assert isinstance(s1, sr.WorkspaceStatus)
    assert isinstance(s2, sr.WorkspaceStatus)
    assert s1.ready == s2.ready
    assert sibling.exists() and (sibling / 'k').exists()