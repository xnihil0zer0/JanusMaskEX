"""Paired oracle for the stale ``selfheal_skip`` mtime gate in
``harness.brief_status.compute_brief_status``.

The gate under test: a ``state/control/autowork/selfheal_skip/<tid>`` marker only
blocks a task when its mtime is **>= the plan file mtime**. A *stale* marker
(mtime strictly older than the plan) must be ignored, so the task stays
unstaged/queued rather than blocked. The gate applies ONLY to ``selfheal_skip``
markers -- ``tasks/blocked/<tid>.exhausted`` blocks unconditionally.

This file is GREEN against the corrected implementation (which honours the gate)
and FAILS against the declared mutant (gate removed or inverted), because the
stale-ignored and fresh-blocks directions are asserted on the same marker path
with os.utime-controlled, wall-clock-independent mtimes.
"""
import hashlib
import json
import os
from pathlib import Path
import pytest
from harness.brief_status import compute_brief_status
SLUG = 'demoslug'
TID = 'task-0001'
PLAN_MTIME = 1600000000.0
DELTA = 100.0
EXPECTED_RECORD_KEYS = {'slug', 'brief_filename', 'brief_mtime', 'has_plan', 'plan_filename', 'plan_stale', 'task_ids', 'queued', 'processing', 'processed_unaccepted', 'accepted', 'blocked', 'remaining', 'state', 'unstaged_task_ids'}

def _build_repo(tmp_path: Path, *, task_id: str=TID, slug: str=SLUG, ledger_rows=None):
    """Build an isolated on-disk repo_root + state_dir.

    Stamps ``source_brief_sha256`` matching the brief bytes so the existing
    sha/mtime plan-staleness block keeps ``has_plan`` True regardless of the
    plan vs brief mtimes we manipulate for the marker gate.
    """
    repo_root = tmp_path / 'repo'
    state_dir = tmp_path / 'state'
    repo_root.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    brief_bytes = b'# brief hooks\n\nbody\n'
    brief_file = repo_root / f'brief_hooks_{slug}.md'
    brief_file.write_bytes(brief_bytes)
    plan = {'tasks': [{'task_id': task_id}], 'source_brief_sha256': hashlib.sha256(brief_bytes).hexdigest()}
    plan_file = repo_root / f'plan_hooks_{slug}.json'
    plan_file.write_text(json.dumps(plan), encoding='utf-8')
    ledger = state_dir / 'impl_progress.jsonl'
    if ledger_rows:
        ledger.write_text(''.join((json.dumps(r) + '\n' for r in ledger_rows)), encoding='utf-8')
    else:
        ledger.write_text('', encoding='utf-8')
    return (repo_root, state_dir, brief_file, plan_file)

def _make_selfheal_marker(state_dir: Path, task_id: str=TID) -> Path:
    """Create state/control/autowork/selfheal_skip/<tid> (parents first)."""
    marker = state_dir / 'control' / 'autowork' / 'selfheal_skip' / task_id
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text('', encoding='utf-8')
    return marker

def _make_exhausted(state_dir: Path, task_id: str=TID) -> Path:
    exhausted = state_dir / 'tasks' / 'blocked' / f'{task_id}.exhausted'
    exhausted.parent.mkdir(parents=True, exist_ok=True)
    exhausted.write_text('', encoding='utf-8')
    return exhausted

def _set_mtime(path: Path, mtime: float) -> None:
    os.utime(path, (mtime, mtime))

def _record_for(records, slug: str=SLUG) -> dict:
    for rec in records:
        if rec.get('slug') == slug:
            return rec
    raise AssertionError(f'no record for slug {slug!r} in {[r.get('slug') for r in records]}')

def test_stale_marker_older_than_plan_is_ignored(tmp_path):
    """Marker strictly older than the plan -> ignored: not blocked, unstaged."""
    repo_root, state_dir, _brief, plan_file = _build_repo(tmp_path)
    marker = _make_selfheal_marker(state_dir)
    _set_mtime(plan_file, PLAN_MTIME)
    _set_mtime(marker, PLAN_MTIME - DELTA)
    rec = _record_for(compute_brief_status(repo_root, state_dir))
    assert rec['state'] != 'blocked'
    assert TID not in rec['blocked']
    assert TID in rec['unstaged_task_ids']

def test_fresh_marker_newer_than_plan_blocks(tmp_path):
    """Marker newer than the plan -> blocks on the same marker path."""
    repo_root, state_dir, _brief, plan_file = _build_repo(tmp_path)
    marker = _make_selfheal_marker(state_dir)
    _set_mtime(plan_file, PLAN_MTIME)
    _set_mtime(marker, PLAN_MTIME + DELTA)
    rec = _record_for(compute_brief_status(repo_root, state_dir))
    assert rec['state'] == 'blocked'
    assert TID in rec['blocked']
    assert TID not in rec['unstaged_task_ids']

def test_marker_mtime_equal_to_plan_blocks_boundary(tmp_path):
    """Boundary: marker mtime == plan mtime -> blocks (gate is >=)."""
    repo_root, state_dir, _brief, plan_file = _build_repo(tmp_path)
    marker = _make_selfheal_marker(state_dir)
    _set_mtime(plan_file, PLAN_MTIME)
    _set_mtime(marker, PLAN_MTIME)
    rec = _record_for(compute_brief_status(repo_root, state_dir))
    assert rec['state'] == 'blocked'
    assert TID in rec['blocked']

def test_blocked_exhausted_unconditional_no_mtime_gate(tmp_path):
    """tasks/blocked/<tid>.exhausted blocks regardless of mtime (no gate)."""
    repo_root, state_dir, _brief, plan_file = _build_repo(tmp_path)
    exhausted = _make_exhausted(state_dir)
    _set_mtime(plan_file, PLAN_MTIME)
    _set_mtime(exhausted, PLAN_MTIME - DELTA)
    rec = _record_for(compute_brief_status(repo_root, state_dir))
    assert TID in rec['blocked']
    assert rec['state'] == 'blocked'

def test_no_marker_no_blocked_files_not_blocked(tmp_path):
    """No selfheal marker and no blocked/ files -> tid not blocked."""
    repo_root, state_dir, _brief, _plan = _build_repo(tmp_path)
    rec = _record_for(compute_brief_status(repo_root, state_dir))
    assert TID not in rec['blocked']
    assert rec['state'] != 'blocked'
    assert TID in rec['unstaged_task_ids']

def test_records_shape_unstaged_contains_tid_when_stale(tmp_path):
    """Integration: with a stale marker the record exposes tid as unstaged."""
    repo_root, state_dir, _brief, plan_file = _build_repo(tmp_path)
    marker = _make_selfheal_marker(state_dir)
    _set_mtime(plan_file, PLAN_MTIME)
    _set_mtime(marker, PLAN_MTIME - DELTA)
    rec = _record_for(compute_brief_status(repo_root, state_dir))
    assert EXPECTED_RECORD_KEYS.issubset(rec.keys())
    assert rec['has_plan'] is True
    assert rec['task_ids'] == [TID]
    assert TID in rec['unstaged_task_ids']
    assert TID not in rec['blocked']

def test_accepted_tid_never_blocked_even_with_fresh_marker(tmp_path):
    """Regression: an accepted tid is never blocked even with a fresh marker."""
    rows = [{'task_id': TID, 'phase': 'accepted', 'event': 'auto_commit', 'commit_sha': 'deadbeef', 'ts': 123.0}]
    repo_root, state_dir, _brief, plan_file = _build_repo(tmp_path, ledger_rows=rows)
    marker = _make_selfheal_marker(state_dir)
    _set_mtime(plan_file, PLAN_MTIME)
    _set_mtime(marker, PLAN_MTIME + DELTA)
    rec = _record_for(compute_brief_status(repo_root, state_dir))
    assert TID not in rec['blocked']
    assert rec['state'] != 'blocked'
    assert TID in {a['task_id'] for a in rec['accepted']}

def test_existing_brief_status_records_keys_present(tmp_path):
    """Regression: the record carries every documented key with sane types."""
    repo_root, state_dir, _brief, _plan = _build_repo(tmp_path)
    rec = _record_for(compute_brief_status(repo_root, state_dir))
    assert EXPECTED_RECORD_KEYS.issubset(rec.keys())
    assert rec['slug'] == SLUG
    assert isinstance(rec['blocked'], list)
    assert isinstance(rec['unstaged_task_ids'], list)
    assert isinstance(rec['task_ids'], list)
    assert rec['task_ids'] == [TID]