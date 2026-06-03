import pytest
import json
import pathlib
from harness.autowork_daemon import _auto_promote

def test_staging_dep_gate(tmp_path, monkeypatch):
    """
    Negative control (RED on HEAD):
    If A is processed-but-not-accepted, B (which depends on A) should not be staged.
    """
    repo_root = tmp_path / 'repo'
    repo_root.mkdir()
    state_dir = tmp_path / 'state'
    (state_dir / 'tasks').mkdir(parents=True)
    (state_dir / 'tasks' / 'processed').mkdir()
    (state_dir / 'control' / 'autowork').mkdir(parents=True)

    slug = 'staging_dep_gate_test_neg'
    brief_path = repo_root / f'brief_hooks_{slug}.md'
    brief_path.write_text('# Brief content\n', encoding='utf-8')

    plan_filename = f'plan_hooks_{slug}.json'
    plan_path = repo_root / plan_filename
    plan_data = {
        'slug': slug,
        'brief_filename': brief_path.name,
        'tasks': [
            {'task_id': 'A_TASK_ID', 'dependencies': []},
            {'task_id': 'B_TASK_ID', 'dependencies': ['A_TASK_ID']}
        ]
    }
    plan_path.write_text(json.dumps(plan_data), encoding='utf-8')

    # Allowlist the slug
    (state_dir / 'control' / 'autowork' / 'auto_promote.allowlist').write_text(f'{slug}\n', encoding='utf-8')

    # Make A processed-but-not-accepted: place A's task json in tasks/processed/ and do NOT write any accepted ledger row for A.
    a_task_json = state_dir / 'tasks' / 'processed' / 'A_TASK_ID.json'
    a_task_json.write_text(json.dumps({'task_id': 'A_TASK_ID'}), encoding='utf-8')

    staged_calls = []
    def mock_stage_task(plan_p, tid, state_d, canonical=True, working_dir=None):
        staged_calls.append((plan_p, tid))

    import harness.planner.staging
    import harness.autowork_daemon
    monkeypatch.setattr(harness.planner.staging, 'stage_task', mock_stage_task)
    monkeypatch.setattr(harness.autowork_daemon, 'stage_task', mock_stage_task)

    _auto_promote(repo_root, state_dir)

    # Negative assert: assert B was NOT passed to stage_task (failed upstream).
    # On HEAD, this will fail because B is wrongly staged (staged_calls contains B_TASK_ID).
    assert 'B_TASK_ID' not in [tid for _, tid in staged_calls], "B_TASK_ID should not be staged since A_TASK_ID is not accepted"


def test_staging_dep_gate_positive_control(tmp_path, monkeypatch):
    """
    Positive control (GREEN on HEAD & patched):
    If A is processed AND accepted (row in ledger), B should be staged.
    """
    repo_root = tmp_path / 'repo'
    repo_root.mkdir()
    state_dir = tmp_path / 'state'
    (state_dir / 'tasks').mkdir(parents=True)
    (state_dir / 'tasks' / 'processed').mkdir()
    (state_dir / 'control' / 'autowork').mkdir(parents=True)

    slug = 'staging_dep_gate_test_pos'
    brief_path = repo_root / f'brief_hooks_{slug}.md'
    brief_path.write_text('# Brief content\n', encoding='utf-8')

    plan_filename = f'plan_hooks_{slug}.json'
    plan_path = repo_root / plan_filename
    plan_data = {
        'slug': slug,
        'brief_filename': brief_path.name,
        'tasks': [
            {'task_id': 'A_TASK_ID', 'dependencies': []},
            {'task_id': 'B_TASK_ID', 'dependencies': ['A_TASK_ID']}
        ]
    }
    plan_path.write_text(json.dumps(plan_data), encoding='utf-8')

    # Allowlist the slug
    (state_dir / 'control' / 'autowork' / 'auto_promote.allowlist').write_text(f'{slug}\n', encoding='utf-8')

    # Make A processed: place A's task json in tasks/processed/
    a_task_json = state_dir / 'tasks' / 'processed' / 'A_TASK_ID.json'
    a_task_json.write_text(json.dumps({'task_id': 'A_TASK_ID'}), encoding='utf-8')

    # Write an accepted ledger row for A
    ledger_path = state_dir / 'impl_progress.jsonl'
    accepted_row = {
        'phase': 'accepted',
        'event': 'auto_commit',
        'task_id': 'A_TASK_ID',
        'commit_sha': 'x',
        'ts': 1
    }
    ledger_path.write_text(json.dumps(accepted_row) + '\n', encoding='utf-8')

    staged_calls = []
    def mock_stage_task(plan_p, tid, state_d, canonical=True, working_dir=None):
        staged_calls.append((plan_p, tid))

    import harness.planner.staging
    import harness.autowork_daemon
    monkeypatch.setattr(harness.planner.staging, 'stage_task', mock_stage_task)
    monkeypatch.setattr(harness.autowork_daemon, 'stage_task', mock_stage_task)

    _auto_promote(repo_root, state_dir)

    # Positive control: assert B IS staged.
    assert 'B_TASK_ID' in [tid for _, tid in staged_calls], "B_TASK_ID should be staged since A_TASK_ID is accepted"
