import json
import pytest
from pathlib import Path

def test_import_compute_fuzz_coverage():
    from harness.orchestrator_worker import compute_fuzz_coverage
    assert callable(compute_fuzz_coverage)

def test_windowed_fraction_reveals_recent_regime(tmp_path):
    from harness.orchestrator_worker import compute_fuzz_coverage
    rows = []
    for i in range(1, 26):
        tid = f'old-{i}'
        rows.append({'event': 'phase_transition', 'phase': 'accepted', 'task_id': tid})
    for i in range(1, 9):
        tid = f'recent-{i}'
        rows.append({'event': 'phase_transition', 'phase': 'fuzzing', 'task_id': tid})
        rows.append({'event': 'phase_transition', 'phase': 'accepted', 'task_id': tid})
    ledger_file = tmp_path / 'ledger_recent.jsonl'
    with open(ledger_file, 'w', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps(r) + '\n')
    res = compute_fuzz_coverage(ledger_file)
    assert 'fuzzed_fraction_window' in res
    assert 'window_size' in res
    assert 'window_accepted' in res
    assert 'window_fuzzed' in res
    assert res['window_size'] == 20
    assert res['window_accepted'] == 20
    assert res['window_fuzzed'] == 8
    assert res['fuzzed_fraction_window'] == pytest.approx(0.4)
    assert res['fuzzed_fraction'] == pytest.approx(8 / 33)
    assert res['fuzzed_fraction_window'] > res['fuzzed_fraction']
    res_explicit = compute_fuzz_coverage(ledger_file, window=5)
    assert res_explicit['accepted_total'] == 5
    assert res_explicit['fuzzed'] == 5
    assert res_explicit['fuzzed_fraction'] == pytest.approx(1.0)
    assert res_explicit['window_size'] == 5
    assert res_explicit['window_accepted'] == 5
    assert res_explicit['window_fuzzed'] == 5
    assert res_explicit['fuzzed_fraction_window'] == pytest.approx(1.0)

def test_capture_rate_uses_task_file_fallback(tmp_path):
    from harness.orchestrator_worker import compute_fuzz_coverage
    rows = [{'event': 'phase_transition', 'phase': 'fuzzing', 'task_id': 'task-1'}, {'event': 'phase_transition', 'phase': 'accepted', 'task_id': 'task-1'}, {'event': 'phase_transition', 'phase': 'fuzzing', 'task_id': 'task-2'}, {'event': 'phase_transition', 'phase': 'accepted', 'task_id': 'task-2'}, {'event': 'phase_transition', 'phase': 'accepted', 'task_id': 'task-3'}, {'event': 'phase_transition', 'phase': 'fuzzing', 'task_id': 'task-4'}, {'event': 'phase_transition', 'phase': 'accepted', 'task_id': 'task-4'}]
    ledger_file = tmp_path / 'ledger_fallback.jsonl'
    with open(ledger_file, 'w', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps(r) + '\n')
    tasks_dir = tmp_path / 'tasks' / 'processed'
    tasks_dir.mkdir(parents=True, exist_ok=True)
    task_types = {'task-1': 'refactor', 'task-2': 'refactor', 'task-3': 'refactor', 'task-4': 'test_unit'}
    for tid, mtt in task_types.items():
        with open(tasks_dir / f'{tid}.json', 'w', encoding='utf-8') as f:
            json.dump({'meta_task_type': mtt}, f)
    res = compute_fuzz_coverage(ledger_file)
    assert res['accepted_total'] == 4
    assert res['fuzzed'] == 3
    assert res['bypassed'] == 1
    assert res['fuzzed_fraction'] == pytest.approx(0.75)
    assert res['capture_rate'] != res['fuzzed_fraction']
    assert res['capture_rate'] == pytest.approx(2 / 3)

def test_bypass_set_is_taxonomy_derived(tmp_path):
    from harness.orchestrator_worker import compute_fuzz_coverage
    from harness.planner.taxonomies import BYPASS_FUZZER_TYPES
    assert 'sandbox_infra' not in BYPASS_FUZZER_TYPES
    rows = [{'event': 'phase_transition', 'phase': 'fuzzing', 'task_id': 'task-sb1'}, {'event': 'phase_transition', 'phase': 'accepted', 'task_id': 'task-sb1'}]
    ledger_file = tmp_path / 'ledger_sb.jsonl'
    with open(ledger_file, 'w', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps(r) + '\n')
    tasks_dir = tmp_path / 'tasks' / 'processed'
    tasks_dir.mkdir(parents=True, exist_ok=True)
    with open(tasks_dir / 'task-sb1.json', 'w', encoding='utf-8') as f:
        json.dump({'meta_task_type': 'sandbox_infra'}, f)
    res = compute_fuzz_coverage(ledger_file)
    assert res['accepted_total'] == 1
    assert res['fuzzed'] == 1
    assert res['capture_rate'] == 1.0

def test_failsoft_and_empty_return_unchanged(tmp_path):
    from harness.orchestrator_worker import compute_fuzz_coverage
    rows = [{'event': 'phase_transition', 'phase': 'fuzzing', 'task_id': 'task-fs1'}, {'event': 'phase_transition', 'phase': 'accepted', 'task_id': 'task-fs1'}, {'event': 'phase_transition', 'phase': 'accepted', 'task_id': 'task-fs2'}, {'event': 'phase_transition', 'phase': 'accepted', 'task_id': 'task-fs3'}]
    ledger_file = tmp_path / 'ledger_fs.jsonl'
    with open(ledger_file, 'w', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps(r) + '\n')
    res_baseline = compute_fuzz_coverage(ledger_file)
    tasks_dir = tmp_path / 'tasks' / 'processed'
    tasks_dir.mkdir(parents=True, exist_ok=True)
    with open(tasks_dir / 'task-fs2.json', 'w', encoding='utf-8') as f:
        f.write('this is { invalid json }')
    res_failsoft = compute_fuzz_coverage(ledger_file)
    for key in ['accepted_total', 'fuzzed', 'bypassed', 'fuzzed_fraction', 'capture_rate', 'fp_rate']:
        assert res_failsoft[key] == res_baseline[key]
    empty_file = tmp_path / 'missing.jsonl'
    res_empty = compute_fuzz_coverage(empty_file)
    expected_empty = {'accepted_total': 0, 'fuzzed': 0, 'bypassed': 0, 'fuzzed_fraction': 0.0, 'capture_rate': 0.0, 'fp_rate': 0.0}
    assert res_empty == expected_empty

def test_unparseable_json_lines(tmp_path):
    from harness.orchestrator_worker import compute_fuzz_coverage
    ledger_file = tmp_path / 'unparseable.jsonl'
    with open(ledger_file, 'w', encoding='utf-8') as f:
        f.write('not valid json\n')
        f.write('{"event": "phase_transition", "phase": "accepted", "task_id": "task-1"}\n')
        f.write('{\n')
        f.write('{"event": "phase_transition", "phase": "fuzzing", "task_id": "task-2"}\n')
        f.write('{"event": "phase_transition", "phase": "accepted", "task_id": "task-2"}\n')
    res = compute_fuzz_coverage(ledger_file)
    assert res['accepted_total'] == 2
    assert res['fuzzed'] == 1
    assert res['bypassed'] == 1
    assert res['fuzzed_fraction'] == 0.5

def test_missing_ledger_file(tmp_path):
    from harness.orchestrator_worker import compute_fuzz_coverage
    missing_file = tmp_path / 'does_not_exist.jsonl'
    res = compute_fuzz_coverage(missing_file)
    assert isinstance(res, dict)
    assert res['accepted_total'] == 0
    assert res['fuzzed'] == 0
    assert res['bypassed'] == 0
    assert res['fuzzed_fraction'] == 0.0
    assert res['capture_rate'] == 0.0
    assert res['fp_rate'] == 0.0