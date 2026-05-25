from __future__ import annotations
import json
import os
import pathlib
from harness.autowork_daemon import collect_dispatchable_tasks
from harness.autowork_daemon import prioritize

def _write_task(tasks_dir: pathlib.Path, task: dict) -> pathlib.Path:
    tasks_dir.mkdir(parents=True, exist_ok=True)
    path = tasks_dir / f'{task['task_id']}.json'
    path.write_text(json.dumps(task), encoding='utf-8')
    return path

def test_prioritize_orders_by_priority_bucket() -> None:
    low = {'task_id': 'L', 'priority': 'low'}
    critical = {'task_id': 'C', 'priority': 'critical'}
    medium = {'task_id': 'M', 'priority': 'medium'}
    ordered = prioritize([low, critical, medium])
    assert [t['task_id'] for t in ordered] == ['C', 'M', 'L']

def test_prioritize_mtime_tiebreak_within_bucket() -> None:
    newer = {'task_id': 'NEW', 'priority': 'high', '_mtime': 100.0}
    older = {'task_id': 'OLD', 'priority': 'high', '_mtime': 50.0}
    ordered = prioritize([newer, older])
    assert [t['task_id'] for t in ordered] == ['OLD', 'NEW']

def test_collect_dispatchable_filters_running_conflicts(tmp_path: pathlib.Path) -> None:
    state_dir = tmp_path / 'state'
    tasks_dir = state_dir / 'tasks'
    _write_task(tasks_dir, {'task_id': 'A', 'files_touched': ['shared.py'], 'dependencies': []})
    _write_task(tasks_dir, {'task_id': 'B', 'files_touched': ['shared.py'], 'dependencies': []})
    candidates = collect_dispatchable_tasks([], {'A'}, state_dir)
    returned_ids = {t['task_id'] for t in candidates}
    assert 'A' not in returned_ids
    assert 'B' not in returned_ids

def test_collect_dispatchable_filters_unsatisfied_deps(tmp_path: pathlib.Path) -> None:
    state_dir = tmp_path / 'state'
    tasks_dir = state_dir / 'tasks'
    _write_task(tasks_dir, {'task_id': 'B', 'files_touched': ['b.py'], 'dependencies': ['A']})
    status_with_a = [{'slug': 's', 'accepted': [{'task_id': 'A'}]}]
    candidates_with = collect_dispatchable_tasks(status_with_a, set(), state_dir)
    assert {t['task_id'] for t in candidates_with} == {'B'}
    candidates_without = collect_dispatchable_tasks([], set(), state_dir)
    assert {t['task_id'] for t in candidates_without} == set()

def test_collect_dispatchable_skips_processing_subdirs(tmp_path: pathlib.Path) -> None:
    state_dir = tmp_path / 'state'
    processing_dir = state_dir / 'tasks' / 'processing'
    processing_dir.mkdir(parents=True, exist_ok=True)
    nested = processing_dir / 'X.json'
    nested.write_text(json.dumps({'task_id': 'X', 'files_touched': ['x.py'], 'dependencies': []}), encoding='utf-8')
    candidates = collect_dispatchable_tasks([], set(), state_dir)
    assert 'X' not in {t['task_id'] for t in candidates}

def test_heartbeat_interval_returns_default_when_section_absent() -> None:
    assert _heartbeat_interval({}) == float(DEFAULT_HEARTBEAT_SEC)
    assert _heartbeat_interval({'autowork': {}}) == float(DEFAULT_HEARTBEAT_SEC)

def test_heartbeat_interval_returns_configured_value() -> None:
    assert _heartbeat_interval({'autowork': {'heartbeat_sec': 900}}) == 900.0
    assert _heartbeat_interval({'autowork': {'heartbeat_sec': 60}}) == 60.0

def test_heartbeat_interval_falls_back_on_non_numeric() -> None:
    assert _heartbeat_interval({'autowork': {'heartbeat_sec': 'bogus'}}) == float(DEFAULT_HEARTBEAT_SEC)
    assert _heartbeat_interval({'autowork': {'heartbeat_sec': None}}) == float(DEFAULT_HEARTBEAT_SEC)

def test_heartbeat_interval_falls_back_on_non_positive() -> None:
    assert _heartbeat_interval({'autowork': {'heartbeat_sec': 0}}) == float(DEFAULT_HEARTBEAT_SEC)
    assert _heartbeat_interval({'autowork': {'heartbeat_sec': -5}}) == float(DEFAULT_HEARTBEAT_SEC)
from harness.autowork_daemon import DEFAULT_HEARTBEAT_SEC
from harness.autowork_daemon import _heartbeat_interval