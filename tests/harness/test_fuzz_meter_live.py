import importlib.util
import json
from pathlib import Path
from typing import Any

def get_compute_fuzz_coverage():
    current = Path(__file__).resolve().parent
    for p in [current] + list(current.parents):
        target = p / 'harness' / 'orchestrator_worker.py'
        if target.is_file():
            break
        target = p / 'inbox' / 'targets' / 'harness' / 'orchestrator_worker.py'
        if target.is_file():
            break
        target = p / 'targets' / 'harness' / 'orchestrator_worker.py'
        if target.is_file():
            break
    else:
        target = Path(__file__).resolve().parents[2] / 'harness' / 'orchestrator_worker.py'
    spec = importlib.util.spec_from_file_location('orchestrator_worker', target)
    if spec is None or spec.loader is None:
        raise ImportError(f'Could not load spec for {target}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.compute_fuzz_coverage

def test_empty_ledger_guard(tmp_path: Path) -> None:
    compute_fuzz_coverage = get_compute_fuzz_coverage()
    non_existent = tmp_path / 'nonexistent.jsonl'
    res1 = compute_fuzz_coverage(non_existent)
    assert res1 == {'accepted_total': 0, 'fuzzed': 0, 'bypassed': 0, 'fuzzed_fraction': 0.0, 'capture_rate': 0.0, 'fp_rate': 0.0}
    empty_file = tmp_path / 'empty.jsonl'
    empty_file.touch()
    res2 = compute_fuzz_coverage(empty_file)
    assert res2 == {'accepted_total': 0, 'fuzzed': 0, 'bypassed': 0, 'fuzzed_fraction': 0.0, 'capture_rate': 0.0, 'fp_rate': 0.0}

def test_auto_commit_accepted_is_counted(tmp_path: Path) -> None:
    compute_fuzz_coverage = get_compute_fuzz_coverage()
    ledger = tmp_path / 'impl_progress.jsonl'
    row = {'event': 'auto_commit', 'phase': 'accepted', 'task_id': 'T_ac'}
    with open(ledger, 'w', encoding='utf-8') as f:
        f.write(json.dumps(row) + '\n')
    res = compute_fuzz_coverage(ledger)
    assert res['accepted_total'] == 1
    assert res['fuzzed'] == 0
    assert res['bypassed'] == 1
    assert res['fuzzed_fraction'] == 0.0
    assert res['capture_rate'] == 0.0
    assert res['fp_rate'] == 0.0

def test_legacy_phase_transition_still_counted_and_deduped(tmp_path: Path) -> None:
    compute_fuzz_coverage = get_compute_fuzz_coverage()
    ledger = tmp_path / 'impl_progress.jsonl'
    rows = [{'event': 'phase_transition', 'phase': 'accepted', 'task_id': 'T_pt'}, {'event': 'phase_transition', 'phase': 'accepted', 'task_id': 'T_both'}, {'event': 'auto_commit', 'phase': 'accepted', 'task_id': 'T_both'}, {'event': 'auto_commit', 'phase': 'accepted', 'task_id': 'T_ac'}]
    with open(ledger, 'w', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps(r) + '\n')
    res = compute_fuzz_coverage(ledger)
    assert res['accepted_total'] == 3
    res_window = compute_fuzz_coverage(ledger, window=2)
    assert res_window['accepted_total'] == 2

def test_rejected_and_nonaccept_rows_not_counted_and_fuzzed_intact(tmp_path: Path) -> None:
    compute_fuzz_coverage = get_compute_fuzz_coverage()
    ledger = tmp_path / 'impl_progress.jsonl'
    rows = [{'event': 'auto_commit', 'phase': 'rejected', 'task_id': 'T_rej'}, {'event': 'verification_failed', 'task_id': 'T_fail'}, {'event': 'phase_transition', 'phase': 'accepted', 'task_id': 'T_acc_fuzz'}, {'event': 'phase_transition', 'phase': 'fuzzing', 'task_id': 'T_acc_fuzz'}, {'event': 'phase_transition', 'phase': 'cross_examination', 'task_id': 'T_acc_fuzz'}, {'event': 'auto_commit', 'phase': 'accepted', 'task_id': 'T_acc_nofuzz'}]
    with open(ledger, 'w', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps(r) + '\n')
    res = compute_fuzz_coverage(ledger)
    assert res['accepted_total'] == 2
    assert res['fuzzed'] == 1
    assert res['bypassed'] == 1
    assert res['fuzzed_fraction'] == 0.5
    assert res['fp_rate'] == 1.0