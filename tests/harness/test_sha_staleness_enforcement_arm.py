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

def _setup(tmp_path: pathlib.Path):
    """Return (repo_root, state_dir, running) freshly scaffolded under tmp_path."""
    repo_root = tmp_path / 'repo'
    repo_root.mkdir()
    state_dir = tmp_path / 'state'
    (state_dir / 'tasks' / 'processed').mkdir(parents=True)
    (state_dir / 'tasks' / 'processing').mkdir(parents=True)
    (state_dir / 'tasks' / 'blocked').mkdir(parents=True)
    (state_dir / 'control' / 'autowork').mkdir(parents=True)
    running = tmp_path / 'running'
    running.mkdir()
    return (repo_root, state_dir, running)

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

def _mk_workdir(running: pathlib.Path, task_id: str) -> pathlib.Path:
    d = running / task_id
    d.mkdir(parents=True, exist_ok=True)
    (d / 'inbox').mkdir(exist_ok=True)
    (d / 'meta.json').write_text('{}', encoding='utf-8')
    return d

def _invert_mtimes(brief: pathlib.Path, plan: pathlib.Path) -> None:
    """Make the plan look NEWER than the brief so an mtime-only check would
    (wrongly) treat the plan as fresh -- the sha arm must still archive."""
    base = time.time()
    os.utime(brief, (base - 1000, base - 1000))
    os.utime(plan, (base + 1000, base + 1000))

def _active_slugs(repo_root: pathlib.Path, state_dir: pathlib.Path) -> set[str]:
    return {r['slug'] for r in compute_brief_status(repo_root, state_dir)}

def test_calls_three_arg_signature_red_on_head(tmp_path: pathlib.Path) -> None:
    repo_root, state_dir, running = _setup(tmp_path)
    result = _reclaim_zombie_briefs(repo_root, state_dir, running)
    assert result is None or isinstance(result, dict)

def test_planned_stale_brief_archived_sha_only_not_mtime(tmp_path: pathlib.Path) -> None:
    repo_root, state_dir, running = _setup(tmp_path)
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
    _reclaim_zombie_briefs(repo_root, state_dir, running)
    assert not (repo_root / f'brief_hooks_{slug}.md').exists()
    assert slug not in _active_slugs(repo_root, state_dir)

def test_landed_plan_not_archived_even_when_sha_stale(tmp_path: pathlib.Path) -> None:
    repo_root, state_dir, running = _setup(tmp_path)
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
    _reclaim_zombie_briefs(repo_root, state_dir, running)
    assert (repo_root / f'brief_hooks_{slug}.md').exists()
    assert slug in _active_slugs(repo_root, state_dir)

def test_throttle_marker_gates_repeat_archival(tmp_path: pathlib.Path) -> None:
    repo_root, state_dir, running = _setup(tmp_path)
    a_brief = _write_brief(repo_root, 'thr_a', '# throttle a\n')
    a_plan = _write_plan(repo_root, 'thr_a', ['ta'], source_brief_sha256=_STALE_SHA)
    _invert_mtimes(a_brief, a_plan)
    _reclaim_zombie_briefs(repo_root, state_dir, running)
    assert not (repo_root / 'brief_hooks_thr_a.md').exists()
    b_brief = _write_brief(repo_root, 'thr_b', '# throttle b\n')
    b_plan = _write_plan(repo_root, 'thr_b', ['tb'], source_brief_sha256=_STALE_SHA)
    _invert_mtimes(b_brief, b_plan)
    _reclaim_zombie_briefs(repo_root, state_dir, running)
    assert (repo_root / 'brief_hooks_thr_b.md').exists()
    assert 'thr_b' in _active_slugs(repo_root, state_dir)

def test_orphaned_plan_globbed_and_exact_task_id_workdir_reaped(tmp_path: pathlib.Path) -> None:
    repo_root, state_dir, running = _setup(tmp_path)
    live_brief = _write_brief(repo_root, 'alpha', '# live brief\n')
    _write_plan(repo_root, 'alpha', ['foo-impl'], source_brief_sha256=_stamp_correct(live_brief))
    _write_plan(repo_root, 'beta', ['orphan-task'])
    assert not (repo_root / 'brief_hooks_beta.md').exists()
    assert 'beta' not in _active_slugs(repo_root, state_dir)
    wd_orphan = _mk_workdir(running, 'orphan-task')
    wd_live = _mk_workdir(running, 'foo-impl')
    wd_substr = _mk_workdir(running, 'foo')
    _reclaim_zombie_briefs(repo_root, state_dir, running)
    assert not wd_orphan.exists(), 'exact orphaned task_id workdir was not reaped'
    assert wd_live.exists(), 'live task_id workdir was wrongly reaped'
    assert wd_substr.exists(), 'substring task_id workdir was wrongly reaped'

def test_sha_gate_read_only_brief_bytes_and_mtime_unchanged(tmp_path: pathlib.Path) -> None:
    repo_root, state_dir, running = _setup(tmp_path)
    slug = 'readonly'
    brief = _write_brief(repo_root, slug, '# read-only invariant body\nline2\n')
    plan = _write_plan(repo_root, slug, ['ro1'], source_brief_sha256=_STALE_SHA)
    _invert_mtimes(brief, plan)
    _accept(state_dir, 'ro1')
    before_bytes = brief.read_bytes()
    before_mtime_ns = brief.stat().st_mtime_ns
    _reclaim_zombie_briefs(repo_root, state_dir, running)
    assert brief.exists()
    assert brief.read_bytes() == before_bytes
    assert brief.stat().st_mtime_ns == before_mtime_ns

def test_substring_task_id_never_reaped_only_exact_equality(tmp_path: pathlib.Path) -> None:
    repo_root, state_dir, running = _setup(tmp_path)
    live_brief = _write_brief(repo_root, 'svc', '# svc brief\n')
    _write_plan(repo_root, 'svc', ['process-data'], source_brief_sha256=_stamp_correct(live_brief))
    _write_plan(repo_root, 'orph', ['data-cleanup'])
    exact_orphan = _mk_workdir(running, 'data-cleanup')
    survivors = [_mk_workdir(running, 'process'), _mk_workdir(running, 'data'), _mk_workdir(running, 'cleanup'), _mk_workdir(running, 'process-data')]
    _reclaim_zombie_briefs(repo_root, state_dir, running)
    assert not exact_orphan.exists(), 'exact orphaned workdir was not reaped'
    for wd in survivors:
        assert wd.exists(), f'substring/live workdir {wd.name!r} was wrongly reaped'

def test_existing_zombie_reclamation_still_quarantines_zombie_brief(tmp_path: pathlib.Path) -> None:
    repo_root, state_dir, running = _setup(tmp_path)
    slug = 'zomb'
    brief = _write_brief(repo_root, slug, '# zombie brief\n')
    _write_plan(repo_root, slug, ['zt1'], source_brief_sha256=_stamp_correct(brief))
    (state_dir / 'tasks' / 'processed' / 'zt1.json').write_text('{}', encoding='utf-8')
    recs = compute_brief_status(repo_root, state_dir)
    rec = next((r for r in recs if r['slug'] == slug))
    assert rec['state'] == 'zombie', f'precondition: expected zombie, got {rec['state']!r}'
    _reclaim_zombie_briefs(repo_root, state_dir, running)
    assert not (repo_root / f'brief_hooks_{slug}.md').exists()
    quarantined = state_dir / 'control' / 'autowork' / 'quarantine' / f'brief_hooks_{slug}.md'
    assert quarantined.exists(), 'zombie brief was not quarantined'
    assert not (state_dir / 'tasks' / 'processed' / 'zt1.json').exists()

def test_sweep_is_best_effort_never_raises_on_malformed_plan(tmp_path: pathlib.Path) -> None:
    repo_root, state_dir, running = _setup(tmp_path)
    _write_brief(repo_root, 'bad', '# malformed-plan brief\n')
    (repo_root / 'plan_hooks_bad.json').write_text('{ this is : not, valid json', encoding='utf-8')
    _write_plan(repo_root, 'orphan2', ['dead-task'])
    _mk_workdir(running, 'dead-task')
    result = _reclaim_zombie_briefs(repo_root, state_dir, running)
    assert result is None or isinstance(result, dict)