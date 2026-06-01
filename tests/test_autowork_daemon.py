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

def test_collect_dispatchable_skips_mismatched_stems(tmp_path: pathlib.Path) -> None:
    state_dir = tmp_path / 'state'
    tasks_dir = state_dir / 'tasks'
    tasks_dir.mkdir(parents=True, exist_ok=True)
    p = tasks_dir / 'current_task.json'
    p.write_text(json.dumps({'task_id': 'RB_JR_tierC_set_phase-conditional_0-reviewed', 'files_touched': ['a.py'], 'dependencies': []}), encoding='utf-8')
    candidates = collect_dispatchable_tasks([], set(), state_dir)
    assert 'RB_JR_tierC_set_phase-conditional_0-reviewed' not in {t['task_id'] for t in candidates}

def test_watchdog_timeout_reads_config(tmp_path: pathlib.Path, monkeypatch) -> None:
    import time
    import subprocess
    import harness.autowork_daemon as ad

    # 1. Mock _decide to return one task
    monkeypatch.setattr(ad, '_decide', lambda *args: ([{'task_id': 'test-task', 'files_touched': []}], False, 1))

    # 2. Mock Popen to return a mock process
    class MockProc:
        pid = 12345
        def poll(self):
            return None
        def wait(self):
            return 0
    monkeypatch.setattr(subprocess, 'Popen', lambda *args, **kwargs: MockProc())

    # 3. Mock _kill_process_group
    killed = []
    monkeypatch.setattr(ad, '_kill_process_group', lambda sd, tid, proc: killed.append(tid))

    # 4. Mock _emit_telemetry
    events = []
    monkeypatch.setattr(ad, '_emit_telemetry', lambda sd, tid, ev, det='': events.append((tid, ev, det)))

    # 5. Mock time.time to simulate timeout
    time_seq = [1000.0, 1000.0, 6000.0]
    time_iter = iter(time_seq)
    def mock_time():
        try:
            return next(time_iter)
        except StopIteration:
            return 6000.0
    monkeypatch.setattr(time, 'time', mock_time)

    # 6. Call _iteration with timeout config of 2000s
    #    (widened watchdog = max(1800, 2*2000 + 600) = 4600s; jump 5000 > 4600 kills)
    config = {
        'synthesis': {
            'active_agents': ['claude'],
            'timeout_seconds': 2000
        }
    }

    repo_root = tmp_path / 'repo'
    state_dir = tmp_path / 'state'
    repo_root.mkdir()
    state_dir.mkdir()

    monkeypatch.setattr(ad, 'suspend_parallel_workers', lambda *a, **kw: None)
    monkeypatch.setattr(ad, 'resume_parallel_workers', lambda *a: None)
    monkeypatch.setattr(ad, '_write_pidfile', lambda *a: None)

    ad._iteration(repo_root, state_dir, 4, dry_run=False, config=config)

    assert 'test-task' in killed
    timeout_events = [e for e in events if e[1] == 'timeout']
    assert len(timeout_events) == 1
    assert "77 min" in timeout_events[0][2]

    # Test the fallback floor of 1800s
    killed.clear()
    events.clear()
    time_seq2 = [1000.0, 1000.0, 2900.0]
    time_iter2 = iter(time_seq2)
    def mock_time2():
        try:
            return next(time_iter2)
        except StopIteration:
            return 2900.0
    monkeypatch.setattr(time, 'time', mock_time2)

    config_low = {
        'synthesis': {
            'active_agents': ['claude'],
            'timeout_seconds': 500
        }
    }
    ad._iteration(repo_root, state_dir, 4, dry_run=False, config=config_low)

    assert 'test-task' in killed
    timeout_events = [e for e in events if e[1] == 'timeout']
    assert len(timeout_events) == 1
    assert "30 min" in timeout_events[0][2]