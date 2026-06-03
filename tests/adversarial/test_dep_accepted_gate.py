import pytest
import json
from pathlib import Path
from harness.orchestrator import get_next_task

def test_dependency_rejected_should_not_run_downstream(tmp_path):
    # Case 1: A only in processed/ (rejected), NO auto_commit ledger row.
    # get_next_task(state_dir) must NOT return task B (returns None).
    state_dir = tmp_path
    tasks_dir = state_dir / 'tasks'
    tasks_dir.mkdir(parents=True)
    processed_dir = tasks_dir / 'processed'
    processed_dir.mkdir(parents=True)
    
    # Write A.json in processed/ to simulate it has been processed but not accepted
    a_json = processed_dir / 'A.json'
    a_json.write_text(json.dumps({"task_id": "A"}), encoding='utf-8')
    
    # Write B.json in tasks/ with dependency on A
    b_json = tasks_dir / 'B.json'
    b_json.write_text(json.dumps({
        "task_id": "B",
        "dependencies": ["A"]
    }), encoding='utf-8')
    
    # On HEAD, this returns B task data, which is wrong.
    # With the patch, this must return None because A was not accepted (no auto_commit ledger row).
    res = get_next_task(state_dir)
    assert res is None

def test_dependency_accepted_should_run_downstream(tmp_path):
    # Case 2: A in processed/ AND an accepted auto_commit row written to impl_progress.jsonl.
    # get_next_task(state_dir) returns B.
    state_dir = tmp_path
    tasks_dir = state_dir / 'tasks'
    tasks_dir.mkdir(parents=True)
    processed_dir = tasks_dir / 'processed'
    processed_dir.mkdir(parents=True)
    
    # Write A.json in processed/
    a_json = processed_dir / 'A.json'
    a_json.write_text(json.dumps({"task_id": "A"}), encoding='utf-8')
    
    # Write B.json in tasks/ with dependency on A
    b_json = tasks_dir / 'B.json'
    b_json.write_text(json.dumps({
        "task_id": "B",
        "dependencies": ["A"]
    }), encoding='utf-8')
    
    # Write accepted auto_commit row for A in impl_progress.jsonl
    ledger = state_dir / 'impl_progress.jsonl'
    row = {"phase": "accepted", "event": "auto_commit", "task_id": "A"}
    ledger.write_text(json.dumps(row) + "\n", encoding='utf-8')
    
    # This should return B task data in both HEAD and patched.
    res = get_next_task(state_dir)
    assert res is not None
    assert res["task_id"] == "B"
