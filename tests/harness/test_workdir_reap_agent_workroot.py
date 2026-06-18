"""RED oracle pinning the post-fix agent_workroot() orphaned-workdir reap
behaviour of harness.autowork_daemon._reclaim_zombie_briefs.

The DESIRED post-fix model: ARM 2 of _reclaim_zombie_briefs (gated DEFAULT-OFF
behind autowork.state_reconcile) delegates the orphaned-workdir reap to
harness.state_reconciler, scanning agent_workroot() -- NOT the dead
running/<tid> model. ``running`` arrives as a set[str] (the live call site in
_iteration passes the post-reap live-task-id set), so the HEAD code -- which
treats ``running`` as a directory path and leaves ``running_dir`` None when it
is a set -- never reaps anything. These tests are therefore RED on HEAD and
GREEN once the delegation lands.

The oracle imports and exercises harness.autowork_daemon._reclaim_zombie_briefs
directly (non-vacuity witness). The three sr location functions
(agent_workroot, external_staging_root, git_worktree_list) are monkeypatched on
the harness.state_reconciler module to hermetic tmp dirs; parse_session_slug
and task_id_has_live_pidfile run REAL against <root>/state/running/*.pid.
"""
from __future__ import annotations
import os
import time
import pathlib
import pytest
import harness.autowork_daemon as awd
import harness.state_reconciler as sr
try:
    import yaml as _yaml_probe
except Exception:
    _yaml_probe = None
_requires_yaml = pytest.mark.skipif(_yaml_probe is None, reason='pyyaml required for _reclaim_zombie_briefs to enable the autowork.state_reconcile gate')
_GATE_ON = 'autowork:\n  state_reconcile: true\n'
_GATE_OFF = 'autowork:\n  state_reconcile: false\n'
_RUNNING_SET = {'some_other_live_tid'}

def _make_root(tmp_path):
    """Hermetic tmp root with <root>/state/ and a SEPARATE agent_workroot dir."""
    root = tmp_path / 'repo'
    (root / 'state').mkdir(parents=True, exist_ok=True)
    (root / 'harness').mkdir(parents=True, exist_ok=True)
    aw = tmp_path / 'aw'
    aw.mkdir(parents=True, exist_ok=True)
    staging = tmp_path / 'staging'
    staging.mkdir(parents=True, exist_ok=True)
    return (root, root / 'state', aw, staging)

def _patch_locations(monkeypatch, aw, staging):
    """Monkeypatch the three sr location fns to hermetic tmp dirs.

    parse_session_slug and task_id_has_live_pidfile are deliberately left REAL.
    """
    monkeypatch.setattr(sr, 'agent_workroot', lambda r: pathlib.Path(aw))
    monkeypatch.setattr(sr, 'external_staging_root', lambda r: pathlib.Path(staging))
    monkeypatch.setattr(sr, 'git_worktree_list', lambda r: [])

def _enable_gate(root):
    (root / 'harness').mkdir(parents=True, exist_ok=True)
    (root / 'harness' / 'config.yaml').write_text(_GATE_ON, encoding='utf-8')

def _disable_gate(root):
    (root / 'harness').mkdir(parents=True, exist_ok=True)
    (root / 'harness' / 'config.yaml').write_text(_GATE_OFF, encoding='utf-8')

def _age(path):
    """Age every node in the tree past the mtime grace guard via os.utime."""
    old = time.time() - 3600
    for p in pathlib.Path(path).rglob('*'):
        try:
            os.utime(p, (old, old))
        except OSError:
            pass
    try:
        os.utime(path, (old, old))
    except OSError:
        pass

def _plant_workdir(aw, task_id, agent='opus', age=True):
    """Plant aw/<agent>/<session_slug> with a real session_slug shape parseable
    by parse_session_slug: <agent>-r1-<task_id>-deadbeef."""
    slug = agent + '-r1-' + task_id + '-deadbeef'
    wd = pathlib.Path(aw) / agent / slug
    (wd / 'outbox').mkdir(parents=True, exist_ok=True)
    (wd / 'outbox' / 'submission.py').write_text('x = 1\n', encoding='utf-8')
    if age:
        _age(wd)
    return wd

def _write_live_pidfile(root, task_id):
    """Plant a LIVE <root>/state/running/<task_id>.pid containing os.getpid()."""
    rdir = pathlib.Path(root) / 'state' / 'running'
    rdir.mkdir(parents=True, exist_ok=True)
    pidfile = rdir / (task_id + '.pid')
    pidfile.write_text(str(os.getpid()), encoding='utf-8')
    return pidfile

def _reclaim(root):
    return awd._reclaim_zombie_briefs(root, root / 'state', running=set(_RUNNING_SET))

@_requires_yaml
def test_aged_orphan_workdir_reaped(tmp_path, monkeypatch):
    """AGED-ORPHAN REAPED -- the post-fix agent_workroot reap removes an aged
    orphan with no live pidfile. RED on HEAD (running is a set so the dead
    running/<tid> branch never arms running_dir)."""
    root, _state, aw, staging = _make_root(tmp_path)
    _enable_gate(root)
    _patch_locations(monkeypatch, aw, staging)
    wd = _plant_workdir(aw, 'task_orphaned')
    assert wd.exists()
    _reclaim(root)
    assert not wd.exists()

@_requires_yaml
def test_live_pidfile_workdir_kept(tmp_path, monkeypatch):
    """LIVE-PIDFILE KEPT -- an aged workdir whose parsed task_id has a live
    <root>/state/running/<tid>.pid (os.getpid()) survives the reap."""
    root, _state, aw, staging = _make_root(tmp_path)
    _enable_gate(root)
    _patch_locations(monkeypatch, aw, staging)
    wd = _plant_workdir(aw, 'task_live')
    _write_live_pidfile(root, 'task_live')
    assert wd.exists()
    _reclaim(root)
    assert wd.exists()

@_requires_yaml
def test_external_staging_workdir_kept(tmp_path, monkeypatch):
    """EXTERNAL-STAGING KEPT -- a workdir whose resolved path is at/under the
    monkeypatched external_staging_root() is refused (kept) even though it is an
    aged orphan with no live pidfile."""
    root, _state, aw, _staging = _make_root(tmp_path)
    _enable_gate(root)
    _patch_locations(monkeypatch, aw, aw)
    wd = _plant_workdir(aw, 'task_staged')
    assert wd.exists()
    _reclaim(root)
    assert wd.exists()

@_requires_yaml
def test_exact_match_not_substring_reaped(tmp_path, monkeypatch):
    """EXACT-MATCH NOT SUBSTRING -- a live pidfile task_live_long.pid does NOT
    protect an aged orphan parsing to task_live (a substring of task_live_long
    but not equal); only EXACT parsed-task_id equality protects, so the orphan
    is reaped. RED on HEAD (nothing reaps)."""
    root, _state, aw, staging = _make_root(tmp_path)
    _enable_gate(root)
    _patch_locations(monkeypatch, aw, staging)
    wd = _plant_workdir(aw, 'task_live')
    _write_live_pidfile(root, 'task_live_long')
    assert wd.exists()
    assert not (root / 'state' / 'running' / 'task_live.pid').exists()
    _reclaim(root)
    assert not wd.exists()

def test_gate_off_no_op_orphan_survives(tmp_path, monkeypatch):
    """GATE-OFF NO-OP regression -- with autowork.state_reconcile written FALSE
    the default-OFF gate short-circuits ARM 2, so an aged orphan survives."""
    root, _state, aw, staging = _make_root(tmp_path)
    _disable_gate(root)
    _patch_locations(monkeypatch, aw, staging)
    wd = _plant_workdir(aw, 'task_orphaned')
    assert wd.exists()
    _reclaim(root)
    assert wd.exists()

def test_best_effort_never_raises_on_empty_tree(tmp_path, monkeypatch):
    """BEST-EFFORT NEVER RAISES regression -- _reclaim_zombie_briefs returns
    None or a dict and never raises even when agent_workroot() points at an
    empty/absent tree, with the gate ON."""
    root, _state, _aw, staging = _make_root(tmp_path)
    _enable_gate(root)
    absent_tree = tmp_path / 'absent_workroot'
    _patch_locations(monkeypatch, absent_tree, staging)
    assert not absent_tree.exists()
    result = _reclaim(root)
    assert result is None or isinstance(result, dict)

@_requires_yaml
def test_reclaim_returns_dict_on_gate_on(tmp_path, monkeypatch):
    """Positive control on the return contract -- with the gate ON and a real
    (empty) tree the call returns the {'reclaimed': n, 'slugs': [...]} dict."""
    root, _state, aw, staging = _make_root(tmp_path)
    _enable_gate(root)
    _patch_locations(monkeypatch, aw, staging)
    result = _reclaim(root)
    assert isinstance(result, dict)
    assert 'reclaimed' in result
    assert 'slugs' in result

@_requires_yaml
def test_orphan_reaped_live_kept_together(tmp_path, monkeypatch):
    """An orphan and a live-pidfile workdir co-resident in the same
    agent_workroot are handled independently in one sweep: the orphan is reaped
    and the live one is kept. RED on HEAD (the orphan is not reaped)."""
    root, _state, aw, staging = _make_root(tmp_path)
    _enable_gate(root)
    _patch_locations(monkeypatch, aw, staging)
    orphan = _plant_workdir(aw, 'task_orphaned')
    live = _plant_workdir(aw, 'task_live')
    _write_live_pidfile(root, 'task_live')
    assert orphan.exists()
    assert live.exists()
    _reclaim(root)
    assert not orphan.exists()
    assert live.exists()

@_requires_yaml
def test_two_orphans_both_reaped(tmp_path, monkeypatch):
    """Multiple aged orphans (no live pidfiles) in one agent_workroot are all
    reaped in a single sweep. RED on HEAD (nothing reaps)."""
    root, _state, aw, staging = _make_root(tmp_path)
    _enable_gate(root)
    _patch_locations(monkeypatch, aw, staging)
    first = _plant_workdir(aw, 'task_orphaned')
    second = _plant_workdir(aw, 'task_another')
    assert first.exists()
    assert second.exists()
    _reclaim(root)
    assert not first.exists()
    assert not second.exists()