import json
from pathlib import Path
import pytest
from tools.brief_reaper import _integrated_task_ids

def _write_ledger(root: Path, rows: list) -> None:
    sd = root / 'state'
    sd.mkdir(parents=True, exist_ok=True)
    lines = []
    for row in rows:
        if isinstance(row, str):
            lines.append(row)
        else:
            lines.append(json.dumps(row))
    (sd / 'impl_progress.jsonl').write_text('\n'.join(lines) + '\n', encoding='utf-8')

def test_nodiff_not_integrated_without_commit(tmp_path):
    root = tmp_path
    noop_task = 'noop-task'
    real_task = 'real-task'
    rows = [{'ts': '2026-06-24T00:00:00Z', 'task_id': noop_task, 'event': 'no_diff', 'commit_sha': None}, {'ts': '2026-06-24T00:00:01Z', 'phase': 'accepted', 'task_id': noop_task, 'event': 'accepted_transition', 'commit_sha': None}, {'ts': '2026-06-24T00:00:02Z', 'phase': 'accepted', 'task_id': real_task, 'event': 'auto_commit', 'commit_sha': 'a' * 40}]
    _write_ledger(root, rows)
    integrated = _integrated_task_ids(root)
    assert noop_task not in integrated
    assert real_task in integrated

def test_missing_ledger_fail_soft(tmp_path):
    integrated = _integrated_task_ids(tmp_path)
    assert integrated == set()
    assert isinstance(integrated, set)

def test_malformed_ledger_skipped(tmp_path):
    root = tmp_path
    rows = ['this is not json at all', '[1, 2, 3]', '{}', {'ts': '2026-06-24T00:00:02Z', 'phase': 'accepted', 'task_id': 'real-task', 'event': 'auto_commit', 'commit_sha': 'a' * 40}]
    _write_ledger(root, rows)
    integrated = _integrated_task_ids(root)
    assert integrated == {'real-task'}
    _write_ledger(root, ['this is not json at all'])
    integrated_empty = _integrated_task_ids(root)
    assert integrated_empty == set()
    assert len(integrated_empty) == 0

def test_uncount_reject_rollback(tmp_path):
    root = tmp_path
    tid = 'reverted-task'
    rows = [{'ts': '2026-06-24T00:00:00Z', 'phase': 'accepted', 'task_id': tid, 'event': 'auto_commit', 'commit_sha': 'b' * 40}, {'ts': '2026-06-24T00:00:01Z', 'phase': 'rejected', 'task_id': tid, 'event': 'reject_rollback', 'reason': 'rolled back'}]
    _write_ledger(root, rows)
    integrated = _integrated_task_ids(root)
    assert tid not in integrated

def test_uncount_task_blocked(tmp_path):
    root = tmp_path
    tid = 'blocked-task'
    rows = [{'ts': '2026-06-24T00:00:00Z', 'phase': 'accepted', 'task_id': tid, 'event': 'auto_commit', 'commit_sha': 'b' * 40}, {'ts': '2026-06-24T00:00:01Z', 'phase': 'autowork', 'task_id': tid, 'event': 'task_blocked', 'detail': 'blocked'}]
    _write_ledger(root, rows)
    integrated = _integrated_task_ids(root)
    assert tid not in integrated

def test_substring_matching_exact(tmp_path):
    root = tmp_path
    _write_ledger(root, [{'ts': '2026-06-24T00:00:00Z', 'phase': 'accepted', 'task_id': 't1', 'event': 'auto_commit', 'commit_sha': 'c' * 40}, {'ts': '2026-06-24T00:00:01Z', 'phase': 'rejected', 'task_id': 't1', 'event': 'reject_rollback', 'reason': 'rolled back'}])
    integrated = _integrated_task_ids(root)
    assert 't1' not in integrated
    assert 't12' not in integrated
    _write_ledger(root, [{'ts': '2026-06-24T00:00:00Z', 'phase': 'accepted', 'task_id': 't1', 'event': 'auto_commit', 'commit_sha': 'c' * 40}, {'ts': '2026-06-24T00:00:01Z', 'phase': 'accepted', 'task_id': 't12', 'event': 'auto_commit', 'commit_sha': 'd' * 40}, {'ts': '2026-06-24T00:00:02Z', 'phase': 'rejected', 'task_id': 't1', 'event': 'reject_rollback', 'reason': 'rolled back'}])
    integrated = _integrated_task_ids(root)
    assert 't1' not in integrated
    assert 't12' in integrated

def test_empty_ledger_returns_empty_set(tmp_path):
    root = tmp_path
    _write_ledger(root, [])
    integrated = _integrated_task_ids(root)
    assert integrated == set()

def test_only_whitespace_yields_empty_set(tmp_path):
    root = tmp_path
    _write_ledger(root, ['   ', '\n', ' \t '])
    integrated = _integrated_task_ids(root)
    assert integrated == set()

def test_non_dict_json_lines_skipped(tmp_path):
    root = tmp_path
    rows = ['123', '"string"', 'true', 'null', '[1, 2]', {'ts': '2026-06-24T00:00:00Z', 'phase': 'accepted', 'task_id': 'valid', 'event': 'auto_commit', 'commit_sha': 'e' * 40}]
    _write_ledger(root, rows)
    integrated = _integrated_task_ids(root)
    assert integrated == {'valid'}

def test_complex_ledger_sequence(tmp_path):
    root = tmp_path
    rows = [{'ts': '2026-06-24T00:00:00Z', 'phase': 'accepted', 'task_id': 'complex', 'event': 'auto_commit', 'commit_sha': 'f' * 40}, {'ts': '2026-06-24T00:00:01Z', 'phase': 'rejected', 'task_id': 'complex', 'event': 'reject_rollback', 'reason': 'rolled back'}, {'ts': '2026-06-24T00:00:02Z', 'phase': 'accepted', 'task_id': 'complex', 'event': 'auto_commit', 'commit_sha': '0' * 40}]
    _write_ledger(root, rows)
    integrated = _integrated_task_ids(root)
    assert 'complex' in integrated
    rows = [{'ts': '2026-06-24T00:00:00Z', 'phase': 'accepted', 'task_id': 'complex2', 'event': 'auto_commit', 'commit_sha': 'f' * 40}, {'ts': '2026-06-24T00:00:01Z', 'phase': 'rejected', 'task_id': 'complex2', 'event': 'reject_rollback', 'reason': 'rolled back'}, {'ts': '2026-06-24T00:00:02Z', 'phase': 'accepted', 'task_id': 'complex2', 'event': 'accepted_transition', 'commit_sha': None}]
    _write_ledger(root, rows)
    integrated = _integrated_task_ids(root)
    assert 'complex2' not in integrated

def test_no_diff_with_commit_is_integrated(tmp_path):
    root = tmp_path
    rows = [{'ts': '2026-06-24T00:00:00Z', 'task_id': 'nodiff-committed', 'event': 'no_diff', 'commit_sha': 'a' * 40}]
    _write_ledger(root, rows)
    integrated = _integrated_task_ids(root)
    assert 'nodiff-committed' in integrated