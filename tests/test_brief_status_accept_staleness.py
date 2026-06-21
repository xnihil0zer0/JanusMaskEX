"""RED oracle for stale-acceptance invalidation in
``harness.brief_status.compute_brief_status``.

These tests are hermetic and offline. Each test builds a minimal synthetic repo
in ``tmp_path``:

    repo/brief_hooks_<slug>.md      -- the brief
    repo/plan_hooks_<slug>.json     -- the plan (lists task_ids)
    state/impl_progress.jsonl       -- the acceptance ledger

and uses ``os.utime`` to control file mtimes precisely so the
acceptance-timestamp-vs-plan-mtime staleness comparison can be exercised
deterministically.

The plan is always stamped with the brief's sha256 (``source_brief_sha256``) so
the pre-existing *plan* staleness check (which compares that stamp to the brief
content, falling back to a brief/plan mtime comparison) never fires. That keeps
each test focused on the *acceptance* staleness behaviour under test rather than
the unrelated plan-staleness path.

Expected behaviour (per spec):
  * acceptance_ts_epoch <  plan_mtime  -> STALE  -> task re-opened
        (added to ``remaining`` + ``unstaged_task_ids``, removed from ``accepted``)
  * acceptance_ts_epoch >= plan_mtime  -> FRESH  -> stays accepted
  * touching the brief with identical content does not advance plan_mtime and
    must not re-open
  * a missing or non-numeric ts is undetermined and must not re-open
"""
import hashlib
import json
import os
from pathlib import Path
import pytest
from harness.brief_status import compute_brief_status
BASE_MTIME = 1000000.0

def _sha256_path(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def _set_mtime(path: Path, mtime: float) -> None:
    os.utime(path, (mtime, mtime))

def _dirs(tmp_path: Path):
    repo_root = tmp_path / 'repo'
    state_dir = tmp_path / 'state'
    repo_root.mkdir()
    state_dir.mkdir()
    return (repo_root, state_dir)

def _write_brief(repo_root: Path, slug: str, content: str='# brief hooks\nbody\n') -> Path:
    p = repo_root / f'brief_hooks_{slug}.md'
    p.write_text(content, encoding='utf-8')
    return p

def _write_plan(repo_root: Path, slug: str, task_ids, brief_path: Path) -> Path:
    plan = {'tasks': [{'task_id': t} for t in task_ids], 'source_brief_sha256': _sha256_path(brief_path)}
    p = repo_root / f'plan_hooks_{slug}.json'
    p.write_text(json.dumps(plan), encoding='utf-8')
    return p

def _write_ledger(state_dir: Path, rows) -> Path:
    p = state_dir / 'impl_progress.jsonl'
    with open(p, 'w', encoding='utf-8') as f:
        for row in rows:
            f.write(json.dumps(row) + '\n')
    return p

def _accept_row(task_id: str, ts=None, commit_sha: str='deadbeefcafe'):
    """An acceptance ledger row. ``ts=None`` omits the 'ts' key entirely."""
    row = {'phase': 'accepted', 'event': 'auto_commit', 'task_id': task_id, 'commit_sha': commit_sha}
    if ts is not None:
        row['ts'] = ts
    return row

def _record_for(records, slug):
    matches = [r for r in records if r['slug'] == slug]
    assert matches, f'expected a brief-status record for slug {slug!r}, got slugs {[r['slug'] for r in records]!r}'
    return matches[0]

def _accepted_ids(record):
    return {a['task_id'] for a in record['accepted']}

def test_stale_acceptance_reopened(tmp_path):
    """acceptance_ts < plan_mtime -> task is re-opened (remaining + unstaged, not accepted)."""
    repo_root, state_dir = _dirs(tmp_path)
    slug, tid = ('alpha', 'alpha-task-1')
    brief = _write_brief(repo_root, slug)
    _set_mtime(brief, BASE_MTIME - 5000)
    plan = _write_plan(repo_root, slug, [tid], brief)
    _set_mtime(plan, BASE_MTIME)
    plan_mtime = plan.stat().st_mtime
    _write_ledger(state_dir, [_accept_row(tid, ts=plan_mtime - 1000)])
    records = compute_brief_status(repo_root, state_dir)
    rec = _record_for(records, slug)
    assert tid not in _accepted_ids(rec), 'stale acceptance must be removed from accepted'
    assert tid in rec['remaining'], 'stale acceptance must be re-opened into remaining'
    assert tid in rec['unstaged_task_ids'], 're-opened task must appear in unstaged_task_ids'

def test_fresh_acceptance_not_reopened(tmp_path):
    """acceptance_ts >= plan_mtime -> task stays accepted."""
    repo_root, state_dir = _dirs(tmp_path)
    slug, tid = ('bravo', 'bravo-task-1')
    brief = _write_brief(repo_root, slug)
    _set_mtime(brief, BASE_MTIME - 5000)
    plan = _write_plan(repo_root, slug, [tid], brief)
    _set_mtime(plan, BASE_MTIME)
    plan_mtime = plan.stat().st_mtime
    _write_ledger(state_dir, [_accept_row(tid, ts=plan_mtime + 1000)])
    records = compute_brief_status(repo_root, state_dir)
    rec = _record_for(records, slug)
    assert tid in _accepted_ids(rec), 'fresh acceptance must stay accepted'
    assert tid not in rec['remaining'], 'fresh acceptance must not be re-opened'
    assert tid not in rec['unstaged_task_ids'], 'fresh accepted task must not be unstaged'

def test_identical_content_touch_not_reopened(tmp_path):
    """Touching the brief with identical content must not advance plan_mtime or reopen."""
    repo_root, state_dir = _dirs(tmp_path)
    slug, tid = ('charlie', 'charlie-task-1')
    content = '# charlie brief\nstable body\n'
    brief = _write_brief(repo_root, slug, content=content)
    _set_mtime(brief, BASE_MTIME - 5000)
    plan = _write_plan(repo_root, slug, [tid], brief)
    _set_mtime(plan, BASE_MTIME)
    plan_mtime = plan.stat().st_mtime
    _write_ledger(state_dir, [_accept_row(tid, ts=plan_mtime + 1000)])
    brief.write_text(content, encoding='utf-8')
    _set_mtime(brief, BASE_MTIME + 100000)
    assert _sha256_path(brief) == json.loads(plan.read_text(encoding='utf-8'))['source_brief_sha256']
    records = compute_brief_status(repo_root, state_dir)
    rec = _record_for(records, slug)
    assert tid in _accepted_ids(rec), 'identical-content touch must not reopen the acceptance'
    assert tid not in rec['remaining'], 'identical-content touch must not re-open into remaining'
    assert rec['plan_stale'] is False, 'identical content must not mark the plan stale'

def test_missing_or_invalid_ts_stays_accepted(tmp_path):
    """A missing or non-numeric acceptance ts is undetermined and must not reopen."""
    repo_root, state_dir = _dirs(tmp_path)
    slug = 'delta'
    t_missing, t_invalid = ('delta-missing-ts', 'delta-invalid-ts')
    brief = _write_brief(repo_root, slug)
    _set_mtime(brief, BASE_MTIME - 5000)
    plan = _write_plan(repo_root, slug, [t_missing, t_invalid], brief)
    _set_mtime(plan, BASE_MTIME)
    _write_ledger(state_dir, [_accept_row(t_missing, ts=None), _accept_row(t_invalid, ts='not-an-epoch')])
    records = compute_brief_status(repo_root, state_dir)
    rec = _record_for(records, slug)
    accepted = _accepted_ids(rec)
    assert t_missing in accepted, 'missing ts must not cause reopen'
    assert t_invalid in accepted, 'invalid ts must not cause reopen'
    assert t_missing not in rec['remaining'], 'missing ts must not be re-opened'
    assert t_invalid not in rec['remaining'], 'invalid ts must not be re-opened'

def test_equal_ts_acceptance_not_reopened(tmp_path):
    """Boundary: acceptance_ts == plan_mtime is fresh (staleness is strict <)."""
    repo_root, state_dir = _dirs(tmp_path)
    slug, tid = ('echo', 'echo-task-1')
    brief = _write_brief(repo_root, slug)
    _set_mtime(brief, BASE_MTIME - 5000)
    plan = _write_plan(repo_root, slug, [tid], brief)
    _set_mtime(plan, BASE_MTIME)
    plan_mtime = plan.stat().st_mtime
    _write_ledger(state_dir, [_accept_row(tid, ts=plan_mtime)])
    records = compute_brief_status(repo_root, state_dir)
    rec = _record_for(records, slug)
    assert tid in _accepted_ids(rec), 'ts == plan_mtime must remain accepted (strict <)'
    assert tid not in rec['remaining'], 'ts == plan_mtime must not be re-opened'

def test_stale_acceptance_state_queued(tmp_path):
    """Re-opening the sole task flips brief state away from 'complete' to 'queued'."""
    repo_root, state_dir = _dirs(tmp_path)
    slug, tid = ('foxtrot', 'foxtrot-task-1')
    brief = _write_brief(repo_root, slug)
    _set_mtime(brief, BASE_MTIME - 5000)
    plan = _write_plan(repo_root, slug, [tid], brief)
    _set_mtime(plan, BASE_MTIME)
    plan_mtime = plan.stat().st_mtime
    _write_ledger(state_dir, [_accept_row(tid, ts=plan_mtime - 1000)])
    records = compute_brief_status(repo_root, state_dir)
    rec = _record_for(records, slug)
    assert tid in rec['remaining'], 'stale task must be re-opened into remaining'
    assert rec['state'] != 'complete', "a re-opened task must not leave the brief 'complete'"
    assert rec['state'] == 'queued', "re-opened, unstaged task should make the brief 'queued'"