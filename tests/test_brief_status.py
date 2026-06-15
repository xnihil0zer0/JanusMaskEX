import json
import pytest
from harness.brief_status import compute_brief_status

def test_brief_no_plan_is_unplanned(tmp_path):
    repo_root = tmp_path / 'repo'
    repo_root.mkdir()
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    (repo_root / 'brief_hooks_test1.md').write_text('content')
    rows = compute_brief_status(repo_root, state_dir)
    assert len(rows) == 1
    assert rows[0]['state'] == 'unplanned'
    assert rows[0]['has_plan'] is False
    assert rows[0]['plan_filename'] is None
    assert rows[0]['slug'] == 'test1'

def test_brief_plan_no_queue_no_ledger_is_queued(tmp_path):
    repo_root = tmp_path / 'repo'
    repo_root.mkdir()
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    (repo_root / 'brief_hooks_test2.md').write_text('content')
    plan = {'tasks': [{'task_id': 'task_1'}, {'task_id': 'task_2'}]}
    (repo_root / 'plan_hooks_test2.json').write_text(json.dumps(plan))
    rows = compute_brief_status(repo_root, state_dir)
    assert len(rows) == 1
    assert rows[0]['state'] == 'queued'
    assert rows[0]['has_plan'] is True
    assert rows[0]['task_ids'] == ['task_1', 'task_2']

def test_brief_plan_all_accepted_is_complete(tmp_path):
    repo_root = tmp_path / 'repo'
    repo_root.mkdir()
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    (repo_root / 'brief_hooks_test3.md').write_text('content')
    plan = {'tasks': [{'task_id': 'task_1'}]}
    (repo_root / 'plan_hooks_test3.json').write_text(json.dumps(plan))
    ledger = {'phase': 'accepted', 'event': 'auto_commit', 'task_id': 'task_1', 'commit_sha': 'abc', 'ts': 123}
    (state_dir / 'impl_progress.jsonl').write_text(json.dumps(ledger) + '\n')
    rows = compute_brief_status(repo_root, state_dir)
    assert len(rows) == 1
    assert rows[0]['state'] == 'complete'
    assert rows[0]['remaining'] == []
    assert len(rows[0]['accepted']) == 1

def test_brief_one_accepted_one_queued_is_in_flight(tmp_path):
    repo_root = tmp_path / 'repo'
    repo_root.mkdir()
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    (state_dir / 'tasks').mkdir(parents=True)
    (repo_root / 'brief_hooks_test4.md').write_text('content')
    plan = {'tasks': [{'task_id': 'task_1'}, {'task_id': 'task_2'}]}
    (repo_root / 'plan_hooks_test4.json').write_text(json.dumps(plan))
    ledger = {'phase': 'accepted', 'event': 'auto_commit', 'task_id': 'task_1', 'commit_sha': 'abc', 'ts': 123}
    (state_dir / 'impl_progress.jsonl').write_text(json.dumps(ledger) + '\n')
    (state_dir / 'tasks' / 'task_2.json').write_text('{}')
    rows = compute_brief_status(repo_root, state_dir)
    assert len(rows) == 1
    assert rows[0]['state'] == 'in_flight'

def test_plan_with_empty_tasks_is_planned(tmp_path):
    repo_root = tmp_path / 'repo'
    repo_root.mkdir()
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    (repo_root / 'brief_hooks_test5.md').write_text('content')
    plan = {'tasks': []}
    (repo_root / 'plan_hooks_test5.json').write_text(json.dumps(plan))
    rows = compute_brief_status(repo_root, state_dir)
    assert len(rows) == 1
    assert rows[0]['state'] == 'planned'

def test_malformed_ledger_row_skipped_silently(tmp_path):
    repo_root = tmp_path / 'repo'
    repo_root.mkdir()
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    (repo_root / 'brief_hooks_test6.md').write_text('content')
    plan = {'tasks': [{'task_id': 'task_1'}]}
    (repo_root / 'plan_hooks_test6.json').write_text(json.dumps(plan))
    ledger = 'not json\n' + json.dumps({'phase': 'accepted', 'event': 'auto_commit', 'task_id': 'task_1', 'commit_sha': 'abc', 'ts': 123}) + '\n'
    (state_dir / 'impl_progress.jsonl').write_text(ledger)
    rows = compute_brief_status(repo_root, state_dir)
    assert len(rows) == 1
    assert rows[0]['state'] == 'complete'

def _write_ledger(state_dir, rows):
    state_dir.joinpath('impl_progress.jsonl').write_text(
        ''.join(json.dumps(r) + '\n' for r in rows))


def test_accepted_then_blocked_is_not_complete(tmp_path):
    """ROOT CAUSE (RED on HEAD): the worker logs ``accepted/auto_commit`` at
    COMMIT time, but if the later push/merge fails the task is routed to
    ``blocked`` (a ``task_blocked`` ledger row) and never lands. The stale
    accepted row must NOT keep counting the task as done, or the daemon never
    re-stages it. (Observed live: leaf-4a-payload-bank — accept@04:20,
    merge_failed/blocked@04:50, commit 8ba86be orphaned.)"""
    repo_root = tmp_path / 'repo'; repo_root.mkdir()
    state_dir = tmp_path / 'state'; state_dir.mkdir()
    (repo_root / 'brief_hooks_t8.md').write_text('c')
    (repo_root / 'plan_hooks_t8.json').write_text(json.dumps({'tasks': [{'task_id': 'task_1'}]}))
    _write_ledger(state_dir, [
        {'phase': 'accepted', 'event': 'auto_commit', 'task_id': 'task_1', 'commit_sha': 'abc', 'ts': 100},
        {'phase': 'autowork', 'event': 'task_blocked', 'task_id': 'task_1', 'outcome': 'auto_commit_failed', 'ts': 200},
    ])
    rows = compute_brief_status(repo_root, state_dir)
    assert rows[0]['accepted'] == []
    assert 'task_1' in rows[0]['unstaged_task_ids']
    assert rows[0]['state'] != 'complete'


def test_accepted_then_reject_rollback_is_not_complete(tmp_path):
    repo_root = tmp_path / 'repo'; repo_root.mkdir()
    state_dir = tmp_path / 'state'; state_dir.mkdir()
    (repo_root / 'brief_hooks_t9.md').write_text('c')
    (repo_root / 'plan_hooks_t9.json').write_text(json.dumps({'tasks': [{'task_id': 'task_1'}]}))
    _write_ledger(state_dir, [
        {'phase': 'accepted', 'event': 'auto_commit', 'task_id': 'task_1', 'commit_sha': 'abc', 'ts': 100},
        {'event': 'reject_rollback', 'task_id': 'task_1', 'files': ['x.py'], 'ts': 200},
    ])
    rows = compute_brief_status(repo_root, state_dir)
    assert rows[0]['accepted'] == []
    assert 'task_1' in rows[0]['unstaged_task_ids']


def test_blocked_then_reaccepted_is_complete(tmp_path):
    """Anti-regression: a task that was blocked on an earlier attempt and then
    LATER successfully accepted (accept is the most-recent terminal event) is
    DONE — chronological order, last terminal event wins."""
    repo_root = tmp_path / 'repo'; repo_root.mkdir()
    state_dir = tmp_path / 'state'; state_dir.mkdir()
    (repo_root / 'brief_hooks_t10.md').write_text('c')
    (repo_root / 'plan_hooks_t10.json').write_text(json.dumps({'tasks': [{'task_id': 'task_1'}]}))
    _write_ledger(state_dir, [
        {'phase': 'autowork', 'event': 'task_blocked', 'task_id': 'task_1', 'outcome': 'auto_commit_failed', 'ts': 100},
        {'phase': 'accepted', 'event': 'auto_commit', 'task_id': 'task_1', 'commit_sha': 'abc', 'ts': 200},
    ])
    rows = compute_brief_status(repo_root, state_dir)
    assert rows[0]['state'] == 'complete'
    assert len(rows[0]['accepted']) == 1
    assert 'task_1' not in rows[0]['unstaged_task_ids']


def test_critique_sibling_not_treated_as_plan(tmp_path):
    repo_root = tmp_path / 'repo'
    repo_root.mkdir()
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    (repo_root / 'brief_hooks_test7_critique.md').write_text('content')
    plan = {'tasks': [{'task_id': 'task_1'}]}
    (repo_root / 'plan_hooks_test7_critique.json').write_text(json.dumps(plan))
    rows = compute_brief_status(repo_root, state_dir)
    assert len(rows) == 1
    assert rows[0]['has_plan'] is False
    assert rows[0]['state'] == 'unplanned'