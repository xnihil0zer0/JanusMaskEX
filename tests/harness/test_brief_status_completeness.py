"""RED oracle for harness.brief_status completeness.

Pins the desired post-fix behaviour of ``compute_brief_status`` and
``compute_epic_status``:

* an exhausted-but-unaccepted task (``tasks/blocked/<tid>.exhausted`` only) reads
  ``blocked``;
* a self-heal-evicted task (``control/autowork/selfheal_skip/<tid>`` only) reads
  ``blocked``;
* an accepted task with a *stale* ``.exhausted`` stays ``complete`` (the
  not-accepted gate prevents a false ``blocked``);
* an epic whose child has a self-heal marker but no brief does NOT roll up as
  ``complete``;
* the existing ``tasks/blocked/<tid>.json`` path keeps blocking;
* markers for task ids that are not in the brief's plan are ignored.

Every test builds its own hermetic ``tmp_path`` repo_root + state_dir and never
touches the live repository ``state/`` directory. Plans are stamped with a FRESH
``source_brief_sha256`` so they are not treated as stale and dropped.
"""
import hashlib
import json
from pathlib import Path
import pytest
from harness.brief_status import compute_brief_status, compute_epic_status

def _make_roots(tmp_path: Path):
    repo_root = tmp_path / 'repo'
    state_dir = tmp_path / 'state'
    repo_root.mkdir()
    state_dir.mkdir()
    return (repo_root, state_dir)

def _ensure_state_dirs(state_dir: Path) -> None:
    (state_dir / 'tasks' / 'blocked').mkdir(parents=True, exist_ok=True)
    (state_dir / 'control' / 'autowork' / 'selfheal_skip').mkdir(parents=True, exist_ok=True)

def _write_brief_and_plan(repo_root: Path, slug: str, task_ids, plan_kind='leaf'):
    """Write brief_hooks_<slug>.md + a FRESH plan_hooks_<slug>.json."""
    brief_text = f'# Brief {slug}\n\nbody for {slug}\n'
    brief_bytes = brief_text.encode('utf-8')
    brief_path = repo_root / f'brief_hooks_{slug}.md'
    brief_path.write_bytes(brief_bytes)
    fresh_sha = hashlib.sha256(brief_bytes).hexdigest()
    plan = {'plan_kind': plan_kind, 'slug': slug, 'source_brief_sha256': fresh_sha, 'tasks': [{'task_id': tid} for tid in task_ids]}
    plan_path = repo_root / f'plan_hooks_{slug}.json'
    plan_path.write_text(json.dumps(plan), encoding='utf-8')
    return (brief_path, plan_path)

def _write_epic_plan(repo_root: Path, epic_slug: str, child_slugs):
    plan = {'plan_kind': 'epic', 'epic_slug': epic_slug, 'child_slugs': list(child_slugs)}
    plan_path = repo_root / f'plan_hooks_{epic_slug}.json'
    plan_path.write_text(json.dumps(plan), encoding='utf-8')
    return plan_path

def _write_ledger(state_dir: Path, rows) -> None:
    path = state_dir / 'impl_progress.jsonl'
    with open(path, 'w', encoding='utf-8') as f:
        for row in rows:
            f.write(json.dumps(row) + '\n')

def _accept_row(tid, ts=100):
    return {'task_id': tid, 'phase': 'accepted', 'event': 'auto_commit', 'commit_sha': f'sha-{tid}', 'ts': ts}

def _mark_exhausted(state_dir: Path, tid: str) -> None:
    (state_dir / 'tasks' / 'blocked' / f'{tid}.exhausted').write_text('', encoding='utf-8')

def _mark_blocked_json(state_dir: Path, tid: str) -> None:
    (state_dir / 'tasks' / 'blocked' / f'{tid}.json').write_text('{}', encoding='utf-8')

def _mark_selfheal(state_dir: Path, tid: str) -> None:
    (state_dir / 'control' / 'autowork' / 'selfheal_skip' / tid).write_text('', encoding='utf-8')

def _mark_queued(state_dir: Path, tid: str) -> None:
    (state_dir / 'tasks' / f'{tid}.json').write_text('{}', encoding='utf-8')

def _record_for(records, slug):
    for r in records:
        if r['slug'] == slug:
            return r
    raise AssertionError(f'no brief record for slug {slug!r}; got {[r['slug'] for r in records]}')

def _epic_record_for(records, epic_slug):
    for r in records:
        if r['epic_slug'] == epic_slug:
            return r
    raise AssertionError(f'no epic record for {epic_slug!r}; got {[r['epic_slug'] for r in records]}')

def test_exhausted_not_accepted_reads_blocked(tmp_path):
    repo_root, state_dir = _make_roots(tmp_path)
    slug = 'c1'
    _write_brief_and_plan(repo_root, slug, ['t1', 't2'])
    _ensure_state_dirs(state_dir)
    _mark_exhausted(state_dir, 't1')
    record = _record_for(compute_brief_status(repo_root, state_dir), slug)
    assert 't1' in record['blocked']
    assert record['state'] == 'blocked'

def test_selfheal_skip_marker_only_reads_blocked(tmp_path):
    repo_root, state_dir = _make_roots(tmp_path)
    slug = 'c2'
    _write_brief_and_plan(repo_root, slug, ['t1', 't2'])
    _ensure_state_dirs(state_dir)
    _mark_selfheal(state_dir, 't1')
    record = _record_for(compute_brief_status(repo_root, state_dir), slug)
    assert 't1' in record['blocked']
    assert record['state'] == 'blocked'

def test_accepted_with_stale_exhausted_stays_complete(tmp_path):
    repo_root, state_dir = _make_roots(tmp_path)
    slug = 'c3'
    _write_brief_and_plan(repo_root, slug, ['t1'])
    _ensure_state_dirs(state_dir)
    _write_ledger(state_dir, [_accept_row('t1')])
    _mark_exhausted(state_dir, 't1')
    record = _record_for(compute_brief_status(repo_root, state_dir), slug)
    assert 't1' not in record['blocked']
    assert record['state'] == 'complete'

def test_epic_absent_brief_child_marker_not_complete(tmp_path):
    repo_root, state_dir = _make_roots(tmp_path)
    epic_slug = 'epic_alpha'
    child_slug = 'child_x'
    _write_epic_plan(repo_root, epic_slug, [child_slug])
    _ensure_state_dirs(state_dir)
    _mark_selfheal(state_dir, child_slug)
    record = _epic_record_for(compute_epic_status(repo_root, state_dir), epic_slug)
    assert record['state'] != 'complete'
    assert record['state'] == 'blocked'

def test_both_blocked_json_and_exhausted_reads_blocked(tmp_path):
    repo_root, state_dir = _make_roots(tmp_path)
    slug = 'c5'
    _write_brief_and_plan(repo_root, slug, ['t1', 't2'])
    _ensure_state_dirs(state_dir)
    _mark_blocked_json(state_dir, 't1')
    _mark_exhausted(state_dir, 't1')
    record = _record_for(compute_brief_status(repo_root, state_dir), slug)
    assert 't1' in record['blocked']
    assert record['state'] == 'blocked'

def test_non_plan_marker_ignored(tmp_path):
    repo_root, state_dir = _make_roots(tmp_path)
    slug = 'c6'
    _write_brief_and_plan(repo_root, slug, ['t1'])
    _ensure_state_dirs(state_dir)
    _mark_queued(state_dir, 't1')
    _mark_selfheal(state_dir, 't_outside')
    _mark_exhausted(state_dir, 't_outside')
    record = _record_for(compute_brief_status(repo_root, state_dir), slug)
    assert 't_outside' not in record['blocked']
    assert record['state'] != 'blocked'
    assert record['state'] == 'in_flight'

def test_accepted_with_stale_exhausted_stays_complete_regression(tmp_path):
    repo_root, state_dir = _make_roots(tmp_path)
    slug = 'r7'
    _write_brief_and_plan(repo_root, slug, ['t1'])
    _ensure_state_dirs(state_dir)
    _write_ledger(state_dir, [{'task_id': 't1', 'phase': 'impl', 'event': 'task_blocked', 'ts': 1}, _accept_row('t1', ts=2)])
    _mark_exhausted(state_dir, 't1')
    _mark_selfheal(state_dir, 't1')
    record = _record_for(compute_brief_status(repo_root, state_dir), slug)
    assert 't1' not in record['blocked']
    assert record['state'] == 'complete'

def test_existing_blocked_json_path_still_blocks(tmp_path):
    repo_root, state_dir = _make_roots(tmp_path)
    slug = 'r8'
    _write_brief_and_plan(repo_root, slug, ['t1', 't2'])
    _ensure_state_dirs(state_dir)
    _mark_blocked_json(state_dir, 't1')
    record = _record_for(compute_brief_status(repo_root, state_dir), slug)
    assert 't1' in record['blocked']
    assert record['state'] == 'blocked'

def test_marker_for_unplanned_task_does_not_flip_state(tmp_path):
    repo_root, state_dir = _make_roots(tmp_path)
    slug = 'r9'
    _write_brief_and_plan(repo_root, slug, ['t1'])
    _ensure_state_dirs(state_dir)
    _write_ledger(state_dir, [_accept_row('t1')])
    _mark_selfheal(state_dir, 't_ghost')
    _mark_exhausted(state_dir, 't_ghost')
    record = _record_for(compute_brief_status(repo_root, state_dir), slug)
    assert 't_ghost' not in record['blocked']
    assert 't1' not in record['blocked']
    assert record['state'] == 'complete'