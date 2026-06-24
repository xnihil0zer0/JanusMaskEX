import json
import pytest
from pathlib import Path
from harness.orchestrator_worker import compute_fuzz_coverage

def test_test_authoring_excluded_from_capture_denominator(tmp_path):
    rows = [{'event': 'phase_transition', 'phase': 'accepted', 'task_id': 'refactor-1'}, {'event': 'phase_transition', 'phase': 'fuzzing', 'task_id': 'refactor-1'}, {'event': 'phase_transition', 'phase': 'accepted', 'task_id': 'refactor-2'}, {'event': 'phase_transition', 'phase': 'fuzzing', 'task_id': 'refactor-2'}, {'event': 'phase_transition', 'phase': 'accepted', 'task_id': 'refactor-3'}, {'event': 'phase_transition', 'phase': 'accepted', 'task_id': 'refactor-4'}, {'event': 'phase_transition', 'phase': 'accepted', 'task_id': 'ta-1'}, {'event': 'phase_transition', 'phase': 'accepted', 'task_id': 'ta-2'}, {'event': 'phase_transition', 'phase': 'accepted', 'task_id': 'ta-3'}, {'event': 'phase_transition', 'phase': 'accepted', 'task_id': 'ta-4'}, {'event': 'phase_transition', 'phase': 'accepted', 'task_id': 'tu-1'}]
    ledger_file = tmp_path / 'ledger_denominator.jsonl'
    with open(ledger_file, 'w', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps(r) + '\n')
    tasks_dir = tmp_path / 'tasks' / 'processed'
    tasks_dir.mkdir(parents=True, exist_ok=True)
    task_types = {'refactor-1': 'refactor', 'refactor-2': 'refactor', 'refactor-3': 'refactor', 'refactor-4': 'refactor', 'ta-1': 'test_authoring', 'ta-2': 'test_authoring', 'ta-3': 'test_authoring', 'ta-4': 'test_authoring', 'tu-1': 'test_unit'}
    for tid, mtt in task_types.items():
        with open(tasks_dir / f'{tid}.json', 'w', encoding='utf-8') as f:
            json.dump({'meta_task_type': mtt}, f)
    res = compute_fuzz_coverage(ledger_file)
    assert 'capture_rate' in res
    assert res['capture_rate'] == pytest.approx(0.5)
    assert res['capture_rate'] > 0.25

def test_capture_rate_window_reveals_recent_regime(tmp_path):
    rows = []
    task_types = {}
    for i in range(1, 11):
        tid = f'refactor-{i}'
        rows.append({'event': 'phase_transition', 'phase': 'accepted', 'task_id': tid})
        task_types[tid] = 'refactor'
    for i in range(11, 16):
        tid = f'refactor-{i}'
        rows.append({'event': 'phase_transition', 'phase': 'accepted', 'task_id': tid})
        rows.append({'event': 'phase_transition', 'phase': 'fuzzing', 'task_id': tid})
        task_types[tid] = 'refactor'
    ledger_file = tmp_path / 'ledger_window.jsonl'
    with open(ledger_file, 'w', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps(r) + '\n')
    tasks_dir = tmp_path / 'tasks' / 'processed'
    tasks_dir.mkdir(parents=True, exist_ok=True)
    for tid, mtt in task_types.items():
        with open(tasks_dir / f'{tid}.json', 'w', encoding='utf-8') as f:
            json.dump({'meta_task_type': mtt}, f)
    res = compute_fuzz_coverage(ledger_file, window=5)
    assert 'capture_rate_window' in res
    assert res['capture_rate_window'] == pytest.approx(1.0)
    assert res['capture_rate_window'] > res['capture_rate']

def test_empty_return_and_failsoft_unchanged(tmp_path):
    missing_file = tmp_path / 'missing.jsonl'
    res_empty = compute_fuzz_coverage(missing_file)
    expected_empty = {'accepted_total': 0, 'fuzzed': 0, 'bypassed': 0, 'fuzzed_fraction': 0.0, 'capture_rate': 0.0, 'fp_rate': 0.0}
    assert res_empty == expected_empty
    rows = [{'event': 'phase_transition', 'phase': 'accepted', 'task_id': 'task-fs1'}, {'event': 'phase_transition', 'phase': 'fuzzing', 'task_id': 'task-fs1'}, {'event': 'phase_transition', 'phase': 'accepted', 'task_id': 'task-fs2'}, {'event': 'phase_transition', 'phase': 'accepted', 'task_id': 'task-fs3'}]
    ledger_file = tmp_path / 'ledger_failsoft.jsonl'
    with open(ledger_file, 'w', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps(r) + '\n')
    res_baseline = compute_fuzz_coverage(ledger_file)
    tasks_dir = tmp_path / 'tasks' / 'processed'
    tasks_dir.mkdir(parents=True, exist_ok=True)
    with open(tasks_dir / 'task-fs1.json', 'w', encoding='utf-8') as f:
        f.write('{invalid json')
    with open(tasks_dir / 'task-fs2.json', 'w', encoding='utf-8') as f:
        f.write('this is invalid json')
    res_failsoft = compute_fuzz_coverage(ledger_file)
    for key in ['accepted_total', 'fuzzed', 'bypassed', 'fuzzed_fraction', 'capture_rate', 'fp_rate']:
        assert res_failsoft[key] == res_baseline[key]
    assert res_failsoft['accepted_total'] == 3
    assert res_failsoft['fuzzed'] == 1
    assert res_failsoft['bypassed'] == 2
    assert res_failsoft['fuzzed_fraction'] == pytest.approx(1.0 / 3.0)
    assert res_failsoft['fp_rate'] == 0.0
    assert res_failsoft['fuzzed_fraction_window'] == pytest.approx(1.0 / 3.0)