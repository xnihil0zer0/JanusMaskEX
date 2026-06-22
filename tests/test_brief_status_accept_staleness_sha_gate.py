"""RED oracle for the content-driven *accept-time-brief-sha* staleness gate in
``harness.brief_status.compute_brief_status`` (and the producer that stamps it).

This file is the single paired oracle that pins the replacement of the broken
plan-mtime ``accept_ts < plan_mtime`` acceptance guard with a CONTENT-DRIVEN
gate: an accepted ``auto_commit`` ledger row now carries the brief-content sha
(``source_brief_sha256``) recorded at acceptance time, and a task is re-opened
iff that recorded sha DIFFERS from the brief sha the accepting plan is stamped
with.  Equality (or an absent legacy key) keeps the task accepted -- regardless
of file mtimes.

These tests are hermetic and offline (no network, no real planner CLI, no
adversarial battery).  Each builds a minimal synthetic repo in ``tmp_path``::

    repo/brief_hooks_<slug>.md      -- the brief
    repo/plan_hooks_<slug>.json     -- the plan (lists task_ids + source_brief_sha256)
    state/impl_progress.jsonl       -- the acceptance ledger

The plan is ALWAYS stamped with the brief's own sha256 (``source_brief_sha256``)
so the pre-existing *plan*-staleness machinery (brief_status.py:89-108) never
fires (``plan_stale`` stays False) -- isolating the *accept*-sha gate under test
from the unrelated plan-staleness path.

The consumer tests construct SYNTHETIC ledger rows that carry
``source_brief_sha256`` directly, so they do NOT depend on the producer having
run; ``test_producer_records_accept_brief_sha`` separately pins the producer
writing the field.  ``os.utime`` is used purely as a CONTROL to prove the gate
is immune to mtime (the ``integrate``/``git stash pop`` mtime bump) -- the
staleness SIGNAL asserted on is the content sha, never the mtime.

RED on HEAD (HEAD keeps the corrected-brief task accepted and wrongly re-queues
the mtime-bumped same-sha task); GREEN once the producer + consumer fixes land.
"""
import hashlib
import json
import os
from pathlib import Path
import pytest
from harness.brief_status import compute_brief_status
BASE_MTIME = 1000000.0
PLAN_FUTURE_MTIME = 4000000000.0
DIFFERENT_SHA = hashlib.sha256(b'a superseded brief body that was never the corrected source').hexdigest()
_OMIT = object()

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

def _write_brief(repo_root: Path, slug: str, content: str='# brief hooks (acshasum)\nbody\n') -> Path:
    p = repo_root / f'brief_hooks_{slug}.md'
    p.write_text(content, encoding='utf-8')
    return p

def _write_plan(repo_root: Path, slug: str, task_ids, brief_path: Path) -> Path:
    """Plan stamped with the brief's CURRENT sha so plan_stale stays False."""
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

def _accept_row(task_id: str, ts=None, commit_sha: str='deadbeefcafe', source_brief_sha256=_OMIT):
    """An accepted/auto_commit ledger row.

    ``ts=None`` omits the 'ts' key entirely; ``source_brief_sha256=_OMIT``
    (default) omits the 'source_brief_sha256' key entirely (legacy row).
    """
    row = {'phase': 'accepted', 'event': 'auto_commit', 'task_id': task_id, 'commit_sha': commit_sha}
    if ts is not None:
        row['ts'] = ts
    if source_brief_sha256 is not _OMIT:
        row['source_brief_sha256'] = source_brief_sha256
    return row

def _accepted_ids(record):
    return [a['task_id'] for a in record['accepted']]

def _plan_sha(plan_path: Path) -> str:
    return json.loads(plan_path.read_text(encoding='utf-8'))['source_brief_sha256']

def test_corrected_brief_reopens_accepted(tmp_path):
    """Accepted sha != plan-stamped (current) sha -> the acceptance is stale and
    the task is re-opened (remaining + unstaged, dropped from accepted)."""
    repo_root, state_dir = _dirs(tmp_path)
    slug, tid = ('acshasum', 'oracle_1')
    brief = _write_brief(repo_root, slug)
    _set_mtime(brief, BASE_MTIME - 5000)
    plan = _write_plan(repo_root, slug, [tid], brief)
    _set_mtime(plan, BASE_MTIME)
    plan_sha = _plan_sha(plan)
    assert plan_sha == _sha256_path(brief)
    accept_sha = DIFFERENT_SHA
    assert accept_sha != plan_sha
    assert len(accept_sha) == 64 and all((c in '0123456789abcdef' for c in accept_sha))
    _write_ledger(state_dir, [_accept_row(tid, ts=BASE_MTIME + 1000, source_brief_sha256=accept_sha)])
    rows = compute_brief_status(repo_root, state_dir)
    assert rows[0]['plan_stale'] is False
    assert tid not in [a['task_id'] for a in rows[0]['accepted']], 'corrected-brief acceptance (different content sha) must drop from accepted'
    assert tid in rows[0]['remaining'], 'stale acceptance must re-open into remaining'
    assert tid in rows[0]['unstaged_task_ids'], 're-opened task must appear in unstaged_task_ids'

def test_landed_same_sha_kept(tmp_path):
    """Accepted sha == plan-stamped sha -> stays accepted EVEN when the plan file
    mtime is bumped newer than the acceptance ts (mtime immunity)."""
    repo_root, state_dir = _dirs(tmp_path)
    slug, tid = ('acshasum', 'oracle_1')
    brief = _write_brief(repo_root, slug)
    _set_mtime(brief, BASE_MTIME - 5000)
    plan = _write_plan(repo_root, slug, [tid], brief)
    plan_sha = _plan_sha(plan)
    _set_mtime(plan, PLAN_FUTURE_MTIME)
    assert plan.stat().st_mtime > BASE_MTIME + 1000
    _write_ledger(state_dir, [_accept_row(tid, ts=BASE_MTIME, source_brief_sha256=plan_sha)])
    rows = compute_brief_status(repo_root, state_dir)
    assert rows[0]['plan_stale'] is False
    assert tid in [a['task_id'] for a in rows[0]['accepted']], 'same-sha acceptance must stay accepted despite a newer plan mtime'
    assert tid not in rows[0]['unstaged_task_ids'], 'same-sha accepted task must not be unstaged'
    assert tid not in rows[0]['remaining'], 'same-sha acceptance must not be re-opened'

def test_missing_accept_sha_kept(tmp_path):
    """Legacy accepted row with NO source_brief_sha256 key at all -> stays
    accepted (the gate fires only on a recorded sha that DIFFERS)."""
    repo_root, state_dir = _dirs(tmp_path)
    slug, tid = ('acshasum', 'oracle_1')
    brief = _write_brief(repo_root, slug)
    _set_mtime(brief, BASE_MTIME - 5000)
    plan = _write_plan(repo_root, slug, [tid], brief)
    _set_mtime(plan, BASE_MTIME)
    ledger = _write_ledger(state_dir, [_accept_row(tid, ts=BASE_MTIME + 1000)])
    written = json.loads(ledger.read_text(encoding='utf-8').strip())
    assert 'source_brief_sha256' not in written, 'legacy row must omit the key entirely (not None)'
    rows = compute_brief_status(repo_root, state_dir)
    assert rows[0]['plan_stale'] is False
    assert tid in [a['task_id'] for a in rows[0]['accepted']], 'legacy acceptance without source_brief_sha256 must stay accepted'
    assert tid not in rows[0]['unstaged_task_ids'], 'legacy accepted task must not be re-listed as unstaged'
    assert tid not in rows[0]['remaining'], 'legacy acceptance must not be re-opened'

def test_corrected_brief_state_queued(tmp_path):
    """Re-opening the sole corrected-brief task flips the brief state away from
    'complete' to 'queued' (state roll-up consequence of the sha gate)."""
    repo_root, state_dir = _dirs(tmp_path)
    slug, tid = ('acshasum', 'oracle_1')
    brief = _write_brief(repo_root, slug)
    _set_mtime(brief, BASE_MTIME - 5000)
    plan = _write_plan(repo_root, slug, [tid], brief)
    _set_mtime(plan, BASE_MTIME)
    plan_sha = _plan_sha(plan)
    assert DIFFERENT_SHA != plan_sha
    _write_ledger(state_dir, [_accept_row(tid, ts=BASE_MTIME + 1000, source_brief_sha256=DIFFERENT_SHA)])
    rows = compute_brief_status(repo_root, state_dir)
    assert rows[0]['plan_stale'] is False
    assert tid in rows[0]['remaining'], 'stale acceptance must be re-opened into remaining'
    assert rows[0]['state'] != 'complete', 'a re-opened task must not leave the brief complete'
    assert rows[0]['state'] == 'queued', 're-opened, unstaged task should make the brief queued'

def test_landed_same_sha_state_complete(tmp_path):
    """Same-sha acceptance (mtime bumped newer) keeps the brief 'complete' --
    the mtime bump must not flip state, only a differing content sha would."""
    repo_root, state_dir = _dirs(tmp_path)
    slug, tid = ('acshasum', 'oracle_1')
    brief = _write_brief(repo_root, slug)
    _set_mtime(brief, BASE_MTIME - 5000)
    plan = _write_plan(repo_root, slug, [tid], brief)
    plan_sha = _plan_sha(plan)
    _set_mtime(plan, PLAN_FUTURE_MTIME)
    assert plan.stat().st_mtime > BASE_MTIME
    _write_ledger(state_dir, [_accept_row(tid, ts=BASE_MTIME, source_brief_sha256=plan_sha)])
    rows = compute_brief_status(repo_root, state_dir)
    assert rows[0]['plan_stale'] is False
    assert tid in [a['task_id'] for a in rows[0]['accepted']], 'same-sha acceptance must stay accepted'
    assert rows[0]['remaining'] == [], 'no task should remain when the only task stays accepted'
    assert rows[0]['state'] == 'complete', 'same-sha acceptance (newer plan mtime) must keep the brief complete'

def test_producer_records_accept_brief_sha(tmp_path):
    """The producer ``harness.orchestrator._auto_commit_accepted`` must stamp the
    accepted/auto_commit ledger row with source_brief_sha256 resolved from the
    accepting plan_hooks_<slug>.json.

    A full ``_auto_commit_accepted`` drive is not hermetically feasible offline
    (it performs git worktree + commit + subprocess verification), so this pins
    the producer's behaviour by asserting the field is recorded by the producer
    itself.  Absent on HEAD (RED); present once the producer fix lands (GREEN).
    """
    import inspect
    import harness.orchestrator as orch