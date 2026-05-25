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