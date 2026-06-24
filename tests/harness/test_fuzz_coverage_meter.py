import json
import pytest
from pathlib import Path

def test_import_compute_fuzz_coverage():
    from harness.orchestrator_worker import compute_fuzz_coverage
    assert callable(compute_fuzz_coverage)

def test_fuzz_coverage_metrics_calculation(tmp_path):
    from harness.orchestrator_worker import compute_fuzz_coverage
    rows = []
    for i in range(1, 4):
        tid = f'task-{i}'
        rows.append({'event': 'phase_transition', 'phase': 'fuzzing', 'task_id': tid})
        rows.append({'event': 'phase_transition', 'phase': 'accepted', 'task_id': tid})
    for i in range(4, 11):
        tid = f'task-{i}'
        rows.append({'event': 'phase_transition', 'phase': 'accepted', 'task_id': tid})
    rows.append({'event': 'phase_transition', 'phase': 'fuzzing', 'task_id': 'task-11'})
    rows.append({'event': 'phase_transition', 'phase': 'rejected', 'task_id': 'task-11'})
    ledger_file = tmp_path / 'impl_progress_basic.jsonl'
    with open(ledger_file, 'w', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps(r) + '\n')
    res = compute_fuzz_coverage(ledger_file)
    assert res['accepted_total'] == 10
    assert res['fuzzed'] == 3
    assert res['bypassed'] == 7
    assert res['fuzzed_fraction'] == pytest.approx(0.3)
    assert res['capture_rate'] == pytest.approx(0.3)
    assert res['fp_rate'] == 0.0
    rows_types = [{'task_id': 'task-t1', 'meta_task_type': 'refactor'}, {'event': 'phase_transition', 'phase': 'fuzzing', 'task_id': 'task-t1'}, {'event': 'phase_transition', 'phase': 'accepted', 'task_id': 'task-t1'}, {'task_id': 'task-t2', 'meta_task_type': 'refactor'}, {'event': 'phase_transition', 'phase': 'fuzzing', 'task_id': 'task-t2'}, {'event': 'phase_transition', 'phase': 'accepted', 'task_id': 'task-t2'}, {'task_id': 'task-t3', 'meta_task_type': 'sandbox_infra'}, {'event': 'phase_transition', 'phase': 'accepted', 'task_id': 'task-t3'}, {'task_id': 'task-t4', 'meta_task_type': 'refactor'}, {'event': 'phase_transition', 'phase': 'accepted', 'task_id': 'task-t4'}]
    ledger_types = tmp_path / 'impl_progress_types.jsonl'
    with open(ledger_types, 'w', encoding='utf-8') as f:
        for r in rows_types:
            f.write(json.dumps(r) + '\n')
    res_types = compute_fuzz_coverage(ledger_types)
    assert res_types['accepted_total'] == 4
    assert res_types['fuzzed'] == 2
    assert res_types['bypassed'] == 2
    assert res_types['fuzzed_fraction'] == 0.5
    assert res_types['capture_rate'] == pytest.approx(2 / 3)
    rows_w = [{'event': 'phase_transition', 'phase': 'fuzzing', 'task_id': 'task-w1'}, {'event': 'phase_transition', 'phase': 'accepted', 'task_id': 'task-w1'}, {'event': 'phase_transition', 'phase': 'accepted', 'task_id': 'task-w2'}, {'event': 'phase_transition', 'phase': 'fuzzing', 'task_id': 'task-w3'}, {'event': 'phase_transition', 'phase': 'accepted', 'task_id': 'task-w3'}, {'event': 'phase_transition', 'phase': 'accepted', 'task_id': 'task-w4'}, {'event': 'phase_transition', 'phase': 'fuzzing', 'task_id': 'task-w5'}, {'event': 'phase_transition', 'phase': 'accepted', 'task_id': 'task-w5'}]
    ledger_w = tmp_path / 'impl_progress_window.jsonl'
    with open(ledger_w, 'w', encoding='utf-8') as f:
        for r in rows_w:
            f.write(json.dumps(r) + '\n')
    res_w = compute_fuzz_coverage(ledger_w, window=3)
    assert res_w['accepted_total'] == 3
    assert res_w['fuzzed'] == 2
    assert res_w['bypassed'] == 1
    assert res_w['fuzzed_fraction'] == pytest.approx(2 / 3)
    rows_fp = [{'event': 'phase_transition', 'phase': 'fuzzing', 'task_id': 'task-tb1'}, {'event': 'phase_transition', 'phase': 'cross_examination', 'task_id': 'task-tb1'}, {'event': 'phase_transition', 'phase': 'fuzzing', 'task_id': 'task-tb1'}, {'event': 'phase_transition', 'phase': 'accepted', 'task_id': 'task-tb1'}, {'event': 'phase_transition', 'phase': 'fuzzing', 'task_id': 'task-tb2'}, {'event': 'event_other', 'task_id': 'task-tb2'}, {'event': 'phase_transition', 'phase': 'decomposition', 'task_id': 'task-tb2'}, {'event': 'phase_transition', 'phase': 'rejected', 'task_id': 'task-tb2'}, {'event': 'phase_transition', 'phase': 'fuzzing', 'task_id': 'task-tb3'}, {'event': 'phase_transition', 'phase': 'accepted', 'task_id': 'task-tb3'}]
    ledger_fp = tmp_path / 'impl_progress_fp.jsonl'
    with open(ledger_fp, 'w', encoding='utf-8') as f:
        for r in rows_fp:
            f.write(json.dumps(r) + '\n')
    res_fp = compute_fuzz_coverage(ledger_fp)
    assert res_fp['fp_rate'] == pytest.approx(0.5)

def test_empty_ledger_no_crash(tmp_path):
    from harness.orchestrator_worker import compute_fuzz_coverage
    empty_file = tmp_path / 'empty.jsonl'
    empty_file.touch()
    res = compute_fuzz_coverage(empty_file)
    assert isinstance(res, dict)
    assert res['accepted_total'] == 0
    assert res['fuzzed'] == 0
    assert res['bypassed'] == 0
    assert res['fuzzed_fraction'] == 0.0
    assert res['capture_rate'] == 0.0
    assert res['fp_rate'] == 0.0

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