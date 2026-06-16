"""Adversarial regression bar for the brief-vs-plan staleness gate in
``harness.brief_status.compute_brief_status``.

A plan stamps the sha256 of the brief it was generated from in
``source_brief_sha256``. If the brief is later edited, the stamped sha no
longer matches the current brief and the plan is stale -- the brief must be
re-planned, so ``has_plan`` flips to False, ``plan_stale`` is recorded True,
and the brief is reported as ``unplanned``. Legacy plans that predate the
stamp fall back to an mtime comparison (plan older than brief == stale).
The gate degrades gracefully (no crash, ``plan_stale`` False) when the plan
is corrupted or the brief is unreadable.
"""
from __future__ import annotations
import hashlib
import json
import os
import pathlib
import pytest
from harness.brief_status import compute_brief_status

def _mk_dirs(tmp_path: pathlib.Path):
    repo_root = tmp_path / 'repo'
    repo_root.mkdir()
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    return (repo_root, state_dir)

def _write_brief(repo_root: pathlib.Path, slug: str, content: str='brief content'):
    p = repo_root / f'brief_hooks_{slug}.md'
    p.write_text(content, encoding='utf-8')
    return p

def _write_plan(repo_root: pathlib.Path, slug: str, plan: dict):
    p = repo_root / f'plan_hooks_{slug}.json'
    p.write_text(json.dumps(plan), encoding='utf-8')
    return p

def test_stale_by_sha(tmp_path: pathlib.Path) -> None:
    """Stamped sha != current brief sha -> stale, has_plan False, unplanned."""
    repo_root, state_dir = _mk_dirs(tmp_path)
    _write_brief(repo_root, 's1', 'the current brief body')
    _write_plan(repo_root, 's1', {'source_brief_sha256': '0' * 64, 'tasks': [{'task_id': 't1'}]})
    rows = compute_brief_status(repo_root, state_dir)
    assert len(rows) == 1
    assert rows[0]['plan_stale'] is True
    assert rows[0]['has_plan'] is False
    assert rows[0]['plan_filename'] is None
    assert rows[0]['state'] == 'unplanned'

def test_fresh_by_sha(tmp_path: pathlib.Path) -> None:
    """Stamped sha == current brief sha -> fresh, plan honored."""
    repo_root, state_dir = _mk_dirs(tmp_path)
    content = 'a perfectly fresh brief'
    _write_brief(repo_root, 's2', content)
    sha = hashlib.sha256(content.encode('utf-8')).hexdigest()
    _write_plan(repo_root, 's2', {'source_brief_sha256': sha, 'tasks': [{'task_id': 't1'}]})
    rows = compute_brief_status(repo_root, state_dir)
    assert len(rows) == 1
    assert rows[0]['plan_stale'] is False
    assert rows[0]['has_plan'] is True
    assert rows[0]['task_ids'] == ['t1']

def test_legacy_no_sha_older_mtime(tmp_path: pathlib.Path) -> None:
    """Legacy plan (no sha) older than its brief -> stale via mtime fallback."""
    repo_root, state_dir = _mk_dirs(tmp_path)
    plan_p = _write_plan(repo_root, 's3', {'tasks': [{'task_id': 't1'}]})
    brief_p = _write_brief(repo_root, 's3', 'edited later')
    os.utime(plan_p, (1000, 1000))
    os.utime(brief_p, (2000, 2000))
    rows = compute_brief_status(repo_root, state_dir)
    assert len(rows) == 1
    assert rows[0]['plan_stale'] is True
    assert rows[0]['has_plan'] is False
    assert rows[0]['state'] == 'unplanned'

def test_legacy_no_sha_newer_mtime(tmp_path: pathlib.Path) -> None:
    """Legacy plan (no sha) newer than its brief -> fresh via mtime fallback."""
    repo_root, state_dir = _mk_dirs(tmp_path)
    plan_p = _write_plan(repo_root, 's4', {'tasks': [{'task_id': 't1'}]})
    brief_p = _write_brief(repo_root, 's4', 'older brief')
    os.utime(plan_p, (3000, 3000))
    os.utime(brief_p, (2000, 2000))
    rows = compute_brief_status(repo_root, state_dir)
    assert len(rows) == 1
    assert rows[0]['plan_stale'] is False
    assert rows[0]['has_plan'] is True
    assert rows[0]['task_ids'] == ['t1']

def test_corrupted_plan_safe_degradation(tmp_path: pathlib.Path) -> None:
    """A corrupt (non-JSON) plan degrades to existing behavior: has_plan False,
    plan_stale False, no crash."""
    repo_root, state_dir = _mk_dirs(tmp_path)
    _write_brief(repo_root, 's5', 'brief')
    (repo_root / 'plan_hooks_s5.json').write_text('{ this is not valid json', encoding='utf-8')
    rows = compute_brief_status(repo_root, state_dir)
    assert len(rows) == 1
    assert rows[0]['plan_stale'] is False
    assert rows[0]['has_plan'] is False
    assert rows[0]['state'] == 'unplanned'

def test_unreadable_brief_safe_degradation(tmp_path: pathlib.Path) -> None:
    """If the brief cannot be read to compute its sha, the staleness gate
    swallows the error and degrades to existing behavior (plan honored)."""
    repo_root, state_dir = _mk_dirs(tmp_path)
    brief_p = _write_brief(repo_root, 's6', 'secret body')
    _write_plan(repo_root, 's6', {'source_brief_sha256': 'f' * 64, 'tasks': [{'task_id': 't1'}]})
    os.chmod(brief_p, 0)
    try:
        if os.access(brief_p, os.R_OK):
            pytest.skip('brief still readable (likely running as root)')
        rows = compute_brief_status(repo_root, state_dir)
    finally:
        os.chmod(brief_p, 420)
    assert len(rows) == 1
    assert rows[0]['plan_stale'] is False
    assert rows[0]['has_plan'] is True

def test_plan_stale_key_in_records(tmp_path: pathlib.Path) -> None:
    """Every record carries the 'plan_stale' key; default is False."""
    repo_root, state_dir = _mk_dirs(tmp_path)
    _write_brief(repo_root, 's7')
    _write_plan(repo_root, 's7', {'tasks': [{'task_id': 't1'}]})
    rows = compute_brief_status(repo_root, state_dir)
    assert len(rows) == 1
    assert 'plan_stale' in rows[0]
    assert rows[0]['plan_stale'] is False

def test_legacy_empty_sha_string(tmp_path: pathlib.Path) -> None:
    """An empty source_brief_sha256 string is treated as missing and falls back
    to the mtime comparison."""
    repo_root, state_dir = _mk_dirs(tmp_path)
    plan_p = _write_plan(repo_root, 's8', {'source_brief_sha256': '', 'tasks': [{'task_id': 't1'}]})
    brief_p = _write_brief(repo_root, 's8', 'edited later')
    os.utime(plan_p, (1000, 1000))
    os.utime(brief_p, (2000, 2000))
    rows = compute_brief_status(repo_root, state_dir)
    assert len(rows) == 1
    assert rows[0]['plan_stale'] is True
    assert rows[0]['has_plan'] is False

def test_empty_brief_safe_degradation(tmp_path: pathlib.Path) -> None:
    """An empty brief file still hashes cleanly; a plan stamped with the sha of
    empty content is fresh, with no crash."""
    repo_root, state_dir = _mk_dirs(tmp_path)
    _write_brief(repo_root, 's9', '')
    empty_sha = hashlib.sha256(b'').hexdigest()
    _write_plan(repo_root, 's9', {'source_brief_sha256': empty_sha, 'tasks': [{'task_id': 't1'}]})
    rows = compute_brief_status(repo_root, state_dir)
    assert len(rows) == 1
    assert rows[0]['plan_stale'] is False
    assert rows[0]['has_plan'] is True

def test_missing_tasks_in_plan_preserves_staleness(tmp_path: pathlib.Path) -> None:
    """A plan without a 'tasks' list is still subject to the staleness gate."""
    repo_root, state_dir = _mk_dirs(tmp_path)
    _write_brief(repo_root, 's10', 'current brief content')
    _write_plan(repo_root, 's10', {'source_brief_sha256': 'a' * 64})
    rows = compute_brief_status(repo_root, state_dir)
    assert len(rows) == 1
    assert rows[0]['plan_stale'] is True
    assert rows[0]['has_plan'] is False
    assert rows[0]['task_ids'] == []

def test_mtime_precision_boundary(tmp_path: pathlib.Path) -> None:
    """Equal plan/brief mtimes are NOT stale (the gate uses a strict <)."""
    repo_root, state_dir = _mk_dirs(tmp_path)
    plan_p = _write_plan(repo_root, 's11', {'tasks': [{'task_id': 't1'}]})
    brief_p = _write_brief(repo_root, 's11', 'x')
    os.utime(plan_p, (1500, 1500))
    os.utime(brief_p, (1500, 1500))
    rows = compute_brief_status(repo_root, state_dir)
    assert len(rows) == 1
    assert rows[0]['plan_stale'] is False
    assert rows[0]['has_plan'] is True