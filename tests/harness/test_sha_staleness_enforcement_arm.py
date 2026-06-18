"""RED oracle for the sha-staleness enforcement arm of
``harness/autowork_daemon.py::_reclaim_zombie_briefs``.

This file pins the POST-FIX contract of ``_reclaim_zombie_briefs`` after it is
extended from the HEAD 2-arg signature ``(repo_root, state_dir)`` to the new
3-arg signature ``(repo_root, state_dir, running)`` with a sha-staleness
enforcement arm. Every test invokes the function with the new 3-positional-arg
signature, so the whole file is RED on HEAD by construction (the HEAD 2-arg
function raises ``TypeError`` on the extra positional argument), and GREEN only
once the implementation task lands.

All tests are fully hermetic: each builds its own ``tmp_path``-based
``repo_root`` / ``state_dir`` / ``running/`` tree. No live ``state/``, no
network, no live-daemon run.
"""
from __future__ import annotations
import hashlib
import json
import os
import time
import pathlib
from harness.autowork_daemon import _reclaim_zombie_briefs
from harness.brief_status import compute_brief_status

def _setup(tmp_path: pathlib.Path, monkeypatch) -> tuple:
    """Return (repo_root, state_dir, aw) freshly scaffolded under tmp_path.

    Scaffolds repo_root, state_dir=repo_root/'state' with
    tasks/{processed,processing,blocked} and control/autowork, writes the
    gate-ON repo_root/'harness'/'config.yaml' (autowork.state_reconcile: true),
    and monkeypatches the three sr locator functions to hermetic tmp dirs via
    monkeypatch.setattr (the B0 fix: NO raw harness.state_reconciler.<name> = ...
    assignment, which would leak process-wide).
    """
    import harness.state_reconciler as sr
    repo_root = tmp_path / 'repo'
    repo_root.mkdir()
    state_dir = repo_root / 'state'
    (state_dir / 'tasks' / 'processed').mkdir(parents=True)
    (state_dir / 'tasks' / 'processing').mkdir(parents=True)
    (state_dir / 'tasks' / 'blocked').mkdir(parents=True)
    (state_dir / 'control' / 'autowork').mkdir(parents=True)
    harness_dir = repo_root / 'harness'
    harness_dir.mkdir(parents=True, exist_ok=True)
    (harness_dir / 'config.yaml').write_text('autowork:\n  state_reconcile: true\n', encoding='utf-8')
    aw = tmp_path / 'aw'
    aw.mkdir(parents=True, exist_ok=True)
    staging = tmp_path / 'staging'
    staging.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(sr, 'agent_workroot', lambda r: aw, raising=False)
    monkeypatch.setattr(sr, 'external_staging_root', lambda r: staging, raising=False)
    monkeypatch.setattr(sr, 'git_worktree_list', lambda r: [], raising=False)
    return (repo_root, state_dir, aw)

def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def _write_brief(repo_root: pathlib.Path, slug: str, body: str) -> pathlib.Path:
    p = repo_root / f'brief_hooks_{slug}.md'
    p.write_text(body, encoding='utf-8')
    return p

def _write_plan(repo_root: pathlib.Path, slug: str, task_ids: list[str], source_brief_sha256: str | None=None) -> pathlib.Path:
    plan: dict = {'tasks': [{'task_id': t} for t in task_ids]}
    if source_brief_sha256 is not None:
        plan['source_brief_sha256'] = source_brief_sha256
    p = repo_root / f'plan_hooks_{slug}.json'
    p.write_text(json.dumps(plan), encoding='utf-8')
    return p

def _stamp_correct(brief_path: pathlib.Path) -> str:
    """A source_brief_sha256 that MATCHES the brief's current bytes (fresh)."""
    return _sha_bytes(brief_path.read_bytes())
_STALE_SHA = 'deadbeef' * 8

def _accept(state_dir: pathlib.Path, *task_ids: str) -> None:
    """Append accepted/auto_commit ledger rows so the tasks count as landed."""
    ledger = state_dir / 'impl_progress.jsonl'
    with open(ledger, 'a', encoding='utf-8') as f:
        for tid in task_ids:
            row = {'ts': time.time(), 'phase': 'accepted', 'event': 'auto_commit', 'task_id': tid, 'commit_sha': '0' * 40}
            f.write(json.dumps(row) + '\n')

def _mk_workdir(running: pathlib.Path, task_id: str, agent: str='opus') -> pathlib.Path:
    """Plant running/<agent>/<agent>-r1-<task_id>-deadbeef aged past the mtime
    grace guard via os.utime, with a real session_slug shape parseable by
    harness.state_reconciler.parse_session_slug."""
    slug = agent + '-r1-' + task_id + '-deadbeef'
    wd = pathlib.Path(running) / agent / slug
    (wd / 'outbox').mkdir(parents=True, exist_ok=True)
    (wd / 'outbox' / 'submission.py').write_text('x = 1\n', encoding='utf-8')
    old = time.time() - 100000.0
    for p in wd.rglob('*'):
        try:
            os.utime(p, (old, old))
        except OSError:
            pass
    try:
        os.utime(wd, (old, old))
    except OSError:
        pass
    return wd

def _invert_mtimes(brief: pathlib.Path, plan: pathlib.Path) -> None:
    """Make the plan look NEWER than the brief so an mtime-only check would
    (wrongly) treat the plan as fresh -- the sha arm must still archive."""
    base = time.time()
    os.utime(brief, (base - 1000, base - 1000))
    os.utime(plan, (base + 1000, base + 1000))

def _active_slugs(repo_root: pathlib.Path, state_dir: pathlib.Path) -> set[str]:
    return {r['slug'] for r in compute_brief_status(repo_root, state_dir)}

def test_calls_three_arg_signature_red_on_head(tmp_path: pathlib.Path, monkeypatch) -> None:
    repo_root, state_dir, aw = _setup(tmp_path, monkeypatch)
    result = _reclaim_zombie_briefs(repo_root, state_dir, set())
    assert result is None or isinstance(result, dict)

def test_planned_stale_brief_archived_sha_only_not_mtime(tmp_path: pathlib.Path, monkeypatch) -> None:
    repo_root, state_dir, aw = _setup(tmp_path, monkeypatch)
    slug = 'stalearm'
    brief = _write_brief(repo_root, slug, '# stale brief body\n')
    plan = _write_plan(repo_root, slug, ['t1'], source_brief_sha256=_STALE_SHA)
    _invert_mtimes(brief, plan)
    recs = compute_brief_status(repo_root, state_dir)
    rec = next((r for r in recs if r['slug'] == slug))
    assert rec['plan_stale'] is True
    assert rec['plan_filename'] is None
    raw = json.loads((repo_root / f'plan_hooks_{slug}.json').read_text(encoding='utf-8'))
    assert raw['source_brief_sha256'] != _sha_bytes(brief.read_bytes())
    assert slug in _active_slugs(repo_root, state_dir)
    _reclaim_zombie_briefs(repo_root, state_dir, set())
    assert not (repo_root / f'brief_hooks_{slug}.md').exists()
    assert slug not in _active_slugs(repo_root, state_dir)

def test_landed_plan_not_archived_even_when_sha_stale(tmp_path: pathlib.Path, monkeypatch) -> None:
    repo_root, state_dir, aw = _setup(tmp_path, monkeypatch)
    slug = 'landed'
    brief = _write_brief(repo_root, slug, '# landed brief body\n')
    plan = _write_plan(repo_root, slug, ['la', 'lb'], source_brief_sha256=_STALE_SHA)
    _invert_mtimes(brief, plan)
    _accept(state_dir, 'la', 'lb')
    recs = compute_brief_status(repo_root, state_dir)
    rec = next((r for r in recs if r['slug'] == slug))
    assert rec['plan_stale'] is True
    assert {a['task_id'] for a in rec['accepted']} == {'la', 'lb'}
    assert rec['remaining'] == []
    _reclaim_zombie_briefs(repo_root, state_dir, set())
    assert (repo_root / f'brief_hooks_{slug}.md').exists()
    assert slug in _active_slugs(repo_root, state_dir)

def test_throttle_marker_gates_repeat_archival(tmp_path: pathlib.Path, monkeypatch) -> None:
    repo_root, state_dir, aw = _setup(tmp_path, monkeypatch)
    a_brief = _write_brief(repo_root, 'thr_a', '# throttle a\n')
    a_plan = _write_plan(repo_root, 'thr_a', ['ta'], source_brief_sha256=_STALE_SHA)
    _invert_mtimes(a_brief, a_plan)
    _reclaim_zombie_briefs(repo_root, state_dir, set())
    assert not (repo_root / 'brief_hooks_thr_a.md').exists()
    b_brief = _write_brief(repo_root, 'thr_b', '# throttle b\n')
    b_plan = _write_plan(repo_root, 'thr_b', ['tb'], source_brief_sha256=_STALE_SHA)
    _invert_mtimes(b_brief, b_plan)
    _reclaim_zombie_briefs(repo_root, state_dir, set())
    assert (repo_root / 'brief_hooks_thr_b.md').exists()
    assert 'thr_b' in _active_slugs(repo_root, state_dir)

def test_orphaned_plan_globbed_and_exact_task_id_workdir_reaped(tmp_path: pathlib.Path, monkeypatch) -> None:
    """A live-pidfile workdir is KEPT; an aged orphan with no live pidfile is
    REAPED. RED on HEAD: ``running`` is a set, so the dead running/<tid> branch
    never arms running_dir and nothing is reaped."""
    repo_root, state_dir, aw = _setup(tmp_path, monkeypatch)
    wd_live = _mk_workdir(aw, 'foo_impl')
    _write_live_pid(state_dir, 'foo_impl')
    wd_orphan = _mk_workdir(aw, 'orphan_task')
    assert wd_live.exists()
    assert wd_orphan.exists()
    _reclaim_zombie_briefs(repo_root, state_dir, set())
    assert not wd_orphan.exists(), 'exact orphaned task_id workdir was not reaped'
    assert wd_live.exists(), 'live-pidfile task_id workdir was wrongly reaped'

def test_sha_gate_read_only_brief_bytes_and_mtime_unchanged(tmp_path: pathlib.Path, monkeypatch) -> None:
    repo_root, state_dir, aw = _setup(tmp_path, monkeypatch)
    slug = 'readonly'
    brief = _write_brief(repo_root, slug, '# read-only invariant body\nline2\n')
    plan = _write_plan(repo_root, slug, ['ro1'], source_brief_sha256=_STALE_SHA)
    _invert_mtimes(brief, plan)
    _accept(state_dir, 'ro1')
    before_bytes = brief.read_bytes()
    before_mtime_ns = brief.stat().st_mtime_ns
    _reclaim_zombie_briefs(repo_root, state_dir, set())
    assert brief.exists()
    assert brief.read_bytes() == before_bytes
    assert brief.stat().st_mtime_ns == before_mtime_ns

def test_substring_task_id_never_reaped_only_exact_equality(tmp_path: pathlib.Path, monkeypatch) -> None:
    """Only EXACT parsed-task_id equality with a live pidfile keeps a workdir: a
    live pidfile for a SUPERSET task_id (svc_long) does NOT protect the aged
    orphan parsing to svc, so svc is reaped while the exact-match workdir
    survives. RED on HEAD (nothing reaps)."""
    repo_root, state_dir, aw = _setup(tmp_path, monkeypatch)
    wd_exact = _mk_workdir(aw, 'process_data')
    _write_live_pid(state_dir, 'process_data')
    wd_substr = _mk_workdir(aw, 'svc')
    _write_live_pid(state_dir, 'svc_long')
    assert wd_exact.exists()
    assert wd_substr.exists()
    _reclaim_zombie_briefs(repo_root, state_dir, set())
    assert wd_exact.exists(), 'exact-pidfile-live workdir was wrongly reaped'
    assert not wd_substr.exists(), 'substring/no-exact-pidfile orphan was not reaped'

def test_existing_zombie_reclamation_still_quarantines_zombie_brief(tmp_path: pathlib.Path, monkeypatch) -> None:
    repo_root, state_dir, aw = _setup(tmp_path, monkeypatch)
    slug = 'zomb'
    brief = _write_brief(repo_root, slug, '# zombie brief\n')
    _write_plan(repo_root, slug, ['zt1'], source_brief_sha256=_stamp_correct(brief))
    (state_dir / 'tasks' / 'processed' / 'zt1.json').write_text('{}', encoding='utf-8')
    recs = compute_brief_status(repo_root, state_dir)
    rec = next((r for r in recs if r['slug'] == slug))
    assert rec['state'] == 'zombie', f'precondition: expected zombie, got {rec['state']!r}'
    _reclaim_zombie_briefs(repo_root, state_dir, set())
    assert not (repo_root / f'brief_hooks_{slug}.md').exists()
    quarantined = state_dir / 'control' / 'autowork' / 'quarantine' / f'brief_hooks_{slug}.md'
    assert quarantined.exists(), 'zombie brief was not quarantined'
    assert not (state_dir / 'tasks' / 'processed' / 'zt1.json').exists()

def test_sweep_is_best_effort_never_raises_on_malformed_plan(tmp_path: pathlib.Path, monkeypatch) -> None:
    repo_root, state_dir, aw = _setup(tmp_path, monkeypatch)
    _write_brief(repo_root, 'bad', '# malformed-plan brief\n')
    (repo_root / 'plan_hooks_bad.json').write_text('{ this is : not, valid json', encoding='utf-8')
    _write_plan(repo_root, 'orphan2', ['dead_task'])
    _mk_workdir(aw, 'dead_task')
    result = _reclaim_zombie_briefs(repo_root, state_dir, set())
    assert result is None or isinstance(result, dict)

def _write_live_pid(state_dir: pathlib.Path, task_id: str) -> pathlib.Path:
    """Plant a LIVE <state_dir>/control/autowork/running/<task_id>.pid (os.getpid())."""
    rdir = state_dir / 'control' / 'autowork' / 'running'
    rdir.mkdir(parents=True, exist_ok=True)
    pidfile = rdir / (task_id + '.pid')
    pidfile.write_text(str(os.getpid()), encoding='utf-8')
    return pidfile

def test_foreign_briefless_plan_with_tasks_list_left_in_place(tmp_path: pathlib.Path, monkeypatch) -> None:
    """A foreign brief-less plan carrying ONLY a tasks list (no
    source_brief_sha256, no sibling brief) is surfaced-not-moved (LEFT in place)
    while a provenance-bearing sibling plan (source_brief_sha256 present, no
    brief) IS archived in the SAME run -- non-vacuous predicate discrimination.
    RED on HEAD (the provenance plan is not archived)."""
    repo_root, state_dir, aw = _setup(tmp_path, monkeypatch)
    foreign = _write_plan(repo_root, 'foreign', ['x'])
    prov = _write_plan(repo_root, 'prov', ['y'], source_brief_sha256=_STALE_SHA)
    assert foreign.exists()
    assert prov.exists()
    _reclaim_zombie_briefs(repo_root, state_dir, set())
    assert (repo_root / 'plan_hooks_foreign.json').exists(), 'foreign brief-less tasks-only plan was wrongly moved'
    assert not (repo_root / 'plan_hooks_prov.json').exists(), 'provenance-bearing brief-less plan was not archived'
'RED oracle for the sha-staleness enforcement arm of\n``harness/autowork_daemon.py::_reclaim_zombie_briefs``.\n\nThis file pins the POST-FIX contract of ``_reclaim_zombie_briefs`` after its\norphaned-workdir reap is migrated from the dead ``running/<tid>`` model to the\n``agent_workroot()`` model delegated to ``harness.state_reconciler``. The three\nlocator functions (``agent_workroot`` / ``external_staging_root`` /\n``git_worktree_list``) are monkeypatched on the ``harness.state_reconciler``\nmodule via ``monkeypatch.setattr`` ONLY (the B0 fix -- a raw module-attribute\nassignment leaks process-wide and reds the capstone cross-contamination test).\n``parse_session_slug`` and ``task_id_has_live_pidfile`` run REAL against\n``<state_dir>/control/autowork/running/*.pid``.\n\nThe workdir-reap tests drive the function with ``running`` arriving as a set\n(the live call site passes the post-reap live-task-id set), so the HEAD code --\nwhich treats ``running`` as a directory path -- never reaps; those tests are RED\non HEAD and GREEN once the delegation lands.\n\nAll tests are fully hermetic: each builds its own ``tmp_path``-based\n``repo_root`` / ``state_dir`` tree with the gate-ON ``harness/config.yaml``. No\nlive ``state/``, no network, no live-daemon run.\n'