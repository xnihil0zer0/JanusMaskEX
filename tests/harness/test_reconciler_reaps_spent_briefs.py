"""Executable oracle pinning the self-healing archive-on-integrate behaviour
in :func:`harness.state_reconciler.reap_stale_disk`.

The reconciler sweep must REAP spent-but-unarchived briefs: when every task in
a ``plan_hooks_<slug>.json`` has an ``accepted`` row in the impl_progress
ledger, that plan and its companion ``brief_hooks_<slug>.md`` are fully
integrated and must be relocated under
``_autowork_archive/<iso-date>/reconciled/`` -- end-to-end via
``reap_stale_disk`` itself. Partially-integrated hooks must remain at the repo
root, and the sweep must be fail-safe / idempotent on empty or already-reaped
roots.

This file is a verification oracle (pytest TEST file), not an implementation.
"""
import json
import datetime
from pathlib import Path
from harness.state_reconciler import reap_stale_disk, reap_spent_briefs, cleanup_state, agent_workroot, external_staging_root

def _write_plan(root: Path, slug: str, task_ids) -> Path:
    """Write a ``plan_hooks_<slug>.json`` with the given task ids at ``root``."""
    plan_data = {'tasks': [{'task_id': tid} for tid in task_ids]}
    plan_path = root / ('plan_hooks_%s.json' % slug)
    plan_path.write_text(json.dumps(plan_data), encoding='utf-8')
    return plan_path

def _write_brief(root: Path, slug: str) -> Path:
    """Write a companion ``brief_hooks_<slug>.md`` at ``root``."""
    brief_path = root / ('brief_hooks_%s.md' % slug)
    brief_path.write_text('# Demo Brief\n', encoding='utf-8')
    return brief_path

def _write_ledger(state_dir: Path, accepted_task_ids) -> Path:
    """Write an impl_progress.jsonl with an ``accepted`` row per task id."""
    ledger_path = state_dir / 'impl_progress.jsonl'
    with open(ledger_path, 'w', encoding='utf-8') as f:
        for tid in accepted_task_ids:
            f.write(json.dumps({'task_id': tid, 'phase': 'accepted'}) + '\n')
    return ledger_path

def test_reconciler_reaps_spent_briefs_fully_integrated(tmp_path):
    """(a) Every plan task accepted -> brief+plan archived under
    _autowork_archive/<today>/reconciled/ and 'spent_briefs' lists the slug."""
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    plan_path = _write_plan(tmp_path, 'demo', ['demo-task-1', 'demo-task-2'])
    brief_path = _write_brief(tmp_path, 'demo')
    _write_ledger(state_dir, ['demo-task-1', 'demo-task-2'])
    res = reap_stale_disk(tmp_path)
    assert 'spent_briefs' in res
    assert res['spent_briefs'] == ['demo']
    today = datetime.date.today().isoformat()
    archive_dir = tmp_path / '_autowork_archive' / today / 'reconciled'
    assert not plan_path.exists()
    assert not brief_path.exists()
    assert (archive_dir / 'plan_hooks_demo.json').exists()
    assert (archive_dir / 'brief_hooks_demo.md').exists()
    res2 = reap_stale_disk(tmp_path)
    assert 'spent_briefs' in res2
    assert res2['spent_briefs'] == []

def test_reconciler_reaps_spent_briefs_partially_integrated(tmp_path):
    """(b) Only one of two plan tasks accepted -> brief+plan remain at root."""
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    plan_path = _write_plan(tmp_path, 'demo', ['demo-task-1', 'demo-task-2'])
    brief_path = _write_brief(tmp_path, 'demo')
    _write_ledger(state_dir, ['demo-task-2'])
    res = reap_stale_disk(tmp_path)
    assert 'spent_briefs' in res
    assert res['spent_briefs'] == []
    assert plan_path.exists()
    assert brief_path.exists()
    today = datetime.date.today().isoformat()
    archive_dir = tmp_path / '_autowork_archive' / today / 'reconciled'
    assert not (archive_dir / 'plan_hooks_demo.json').exists()
    assert not (archive_dir / 'brief_hooks_demo.md').exists()

def test_reconciler_reaps_spent_briefs_wiring_end_to_end(tmp_path):
    """(c) The archival is performed BY reap_stale_disk itself: files sit at the
    root before the call and only move once reap_stale_disk runs."""
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    plan_path = _write_plan(tmp_path, 'demo', ['demo-task-1'])
    brief_path = _write_brief(tmp_path, 'demo')
    _write_ledger(state_dir, ['demo-task-1'])
    today = datetime.date.today().isoformat()
    archive_dir = tmp_path / '_autowork_archive' / today / 'reconciled'
    assert plan_path.exists()
    assert brief_path.exists()
    assert not archive_dir.exists()
    res = reap_stale_disk(tmp_path)
    assert res.get('spent_briefs') == ['demo']
    assert not plan_path.exists()
    assert not brief_path.exists()
    assert (archive_dir / 'plan_hooks_demo.json').exists()
    assert (archive_dir / 'brief_hooks_demo.md').exists()

def test_reconciler_reaps_spent_briefs_empty_root(tmp_path):
    """(d) Fail-safe: a root with no plans or ledger returns cleanly with an
    empty 'spent_briefs' and does not raise; a re-run is also clean."""
    res = reap_stale_disk(tmp_path)
    assert 'spent_briefs' in res
    assert res['spent_briefs'] == []
    res2 = reap_stale_disk(tmp_path)
    assert 'spent_briefs' in res2
    assert res2['spent_briefs'] == []
    standalone = reap_spent_briefs(tmp_path)
    assert list(standalone) == []

def test_state_reconciler_clutter_scan_passes(tmp_path):
    """Regression / positive control: the advisory clutter scan still surfaces
    an idle planning dump (detect-only, never moved)."""
    planning_dir = tmp_path / 'state' / 'planning'
    planning_dir.mkdir(parents=True)
    (planning_dir / 'merged_plan.json').write_text(json.dumps({'tasks': []}), encoding='utf-8')
    dump_path = planning_dir / 'plan_foo.json'
    dump_path.write_text(json.dumps({'tasks': [{'task_id': 'x'}]}), encoding='utf-8')
    status = cleanup_state(tmp_path, mode='report')
    reasons = {c['reason'] for c in status.clutter_candidates}
    paths = {c['path'] for c in status.clutter_candidates}
    assert 'planning_dump_idle' in reasons
    assert 'state/planning/plan_foo.json' in paths
    assert dump_path.exists()

def test_state_reconciler_path_correctness_passes(tmp_path):
    """Regression / positive control: the agent-workroot / external-staging path
    derivation pins the sibling _agentwork layout the reaper depends on."""
    repo = tmp_path / 'repo'
    repo.mkdir()
    aw = agent_workroot(repo)
    staging = external_staging_root(repo)
    assert Path(aw) == tmp_path / 'repo_agentwork'
    assert Path(staging) == tmp_path / 'repo_agentwork' / 'external_staging'
    assert Path(staging).parent == Path(aw)