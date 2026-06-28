import json
import pathlib
from harness.autowork_daemon import collect_dispatchable_tasks

def _write_task(tasks_dir: pathlib.Path, task: dict) -> pathlib.Path:
    tasks_dir.mkdir(parents=True, exist_ok=True)
    path = tasks_dir / f"{task['task_id']}.json"
    path.write_text(json.dumps(task), encoding='utf-8')
    return path

def test_collect_dispatchable_accepts_phase_accepted_without_auto_commit(tmp_path: pathlib.Path) -> None:
    state_dir = tmp_path / 'state'
    tasks_dir = state_dir / 'tasks'
    tasks_dir.mkdir(parents=True, exist_ok=True)
    
    # Task B depends on A
    _write_task(tasks_dir, {'task_id': 'B', 'files_touched': ['b.py'], 'dependencies': ['A']})
    
    # Progress ledger has A accepted but with no_diff event instead of auto_commit
    ledger_path = state_dir / 'impl_progress.jsonl'
    row = {
        'ts': 1000.0,
        'pid': 123,
        'phase': 'accepted',
        'task_id': 'A',
        'event': 'no_diff',
        'reason': 'AST merge produced byte-identical content; no commit created'
    }
    with open(ledger_path, 'w', encoding='utf-8') as f:
        f.write(json.dumps(row) + '\n')
        
    candidates = collect_dispatchable_tasks([], set(), state_dir)
    assert {t['task_id'] for t in candidates} == {'B'}
