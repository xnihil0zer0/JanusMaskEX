"""RED oracle for gap #3 (NGv2 rebuild Phase 0): the autowork daemon must
propagate an EXTERNAL task's trusted ``working_dir`` to the spawned worker as
``JANUSMASK_WORKING_DIR`` so the worker's jail retarget (orchestrator.py:391)
fires and the synthesis agent can read the external repo's source.

Before the fix, ``_spawn_worker`` calls ``subprocess.Popen(cmd, start_new_session=True)``
with NO ``env=`` argument, so the env var is never set on the worker path (only
the serial ``run_pipeline`` sets it). These tests pin the propagation contract.
"""
import json

import harness.autowork_daemon as awd


class _FakeProc:
    def __init__(self, pid=4321):
        self.pid = pid


def _capture_popen(monkeypatch):
    captured = {}

    def fake_popen(cmd, **kwargs):
        captured['cmd'] = cmd
        captured['env'] = kwargs.get('env')
        return _FakeProc()

    monkeypatch.setattr(awd.subprocess, 'Popen', fake_popen)
    return captured


def _write_task(state_dir, task_id, task):
    tasks = state_dir / 'tasks'
    tasks.mkdir(parents=True, exist_ok=True)
    (tasks / f'{task_id}.json').write_text(json.dumps(task), encoding='utf-8')


def test_external_working_dir_propagated_to_worker_env(tmp_path, monkeypatch):
    captured = _capture_popen(monkeypatch)
    _write_task(tmp_path, 't1', {'task_id': 't1',
                                 'working_dir': '/home/xnihil0zer0/NobleGreedv2'})
    pid = awd._spawn_worker(tmp_path, 't1')
    assert pid == 4321
    assert captured['env'] is not None
    assert captured['env'].get('JANUSMASK_WORKING_DIR') == '/home/xnihil0zer0/NobleGreedv2'


def test_self_task_does_not_leak_working_dir_env(tmp_path, monkeypatch):
    captured = _capture_popen(monkeypatch)
    # A stale value in the parent env must NOT leak to a self-build worker.
    monkeypatch.setenv('JANUSMASK_WORKING_DIR', '/leaked/from/parent')
    _write_task(tmp_path, 't2', {'task_id': 't2'})  # no working_dir -> self build
    awd._spawn_worker(tmp_path, 't2')
    assert captured['env'] is not None
    assert 'JANUSMASK_WORKING_DIR' not in captured['env']


def test_missing_task_file_is_fail_safe(tmp_path, monkeypatch):
    captured = _capture_popen(monkeypatch)
    # No task json on disk: still spawns, and does not set the external var.
    pid = awd._spawn_worker(tmp_path, 'nonexistent')
    assert pid == 4321
    assert captured['env'] is not None
    assert 'JANUSMASK_WORKING_DIR' not in captured['env']
