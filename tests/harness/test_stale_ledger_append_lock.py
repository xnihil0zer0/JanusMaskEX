"""RED oracle for harness._journal.write_jsonl_row default-lock behaviour.

These tests assert that when ``lock_path`` is ``None`` the writer derives a
per-target-file lock path (``path.with_suffix(path.suffix + '.lock')``) and
acquires an ``fcntl.flock`` on it.  On HEAD this does not happen, so concurrent
appends issued while a rewriter holds the lock and replaces the file are lost.

Every test is hermetic: it runs entirely under pytest's ``tmp_path`` and has no
network or live-state dependencies.
"""
from __future__ import annotations
import fcntl
import json
import os
import threading
import time
from unittest import mock
import pytest
from harness import _journal

def _default_lock_path(target):
    """Mirror the default lock path the implementation is expected to derive."""
    return target.with_suffix(target.suffix + '.lock')

def _read_rows(target):
    text = target.read_text(encoding='utf-8')
    return [json.loads(line) for line in text.splitlines() if line.strip()]

def test_concurrent_append_during_rewrite_loses_no_rows(tmp_path):
    """A rewriter holding the default lock must not cause a concurrent
    appender to lose its row when ``lock_path`` is None."""
    target = tmp_path / 'ledger.jsonl'
    lock_path = _default_lock_path(target)
    seed = [{'id': 0, 'kind': 'seed'}, {'id': 1, 'kind': 'seed'}]
    with target.open('w', encoding='utf-8') as f:
        for r in seed:
            f.write(json.dumps(r) + '\n')
    appended_row = {'id': 99, 'kind': 'append'}
    rewrite_row = {'id': 50, 'kind': 'rewrite'}
    lock_fd = lock_path.open('a', encoding='utf-8')
    fcntl.flock(lock_fd, fcntl.LOCK_EX)
    try:
        snapshot = _read_rows(target)

        def _appender():
            _journal.write_jsonl_row(target, appended_row, lock_path=None)
        t = threading.Thread(target=_appender)
        t.start()
        time.sleep(0.5)
        tmp = target.with_suffix(target.suffix + '.tmp')
        with tmp.open('w', encoding='utf-8') as f:
            for r in snapshot + [rewrite_row]:
                f.write(json.dumps(r) + '\n')
        os.replace(tmp, target)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()
    t.join(timeout=10)
    assert not t.is_alive(), 'appender thread did not finish; lock was never released to it'
    rows = _read_rows(target)
    assert rewrite_row in rows, 'rewritten data missing from final ledger'
    assert appended_row in rows, 'appended row was LOST during the rewrite (no default flock)'

def test_default_lock_path_is_per_target_file(tmp_path):
    """write_jsonl_row must flock a path derived from the target when
    lock_path is None: LOCK_EX then LOCK_UN on ``<path><suffix>.lock``."""
    target = tmp_path / 'events.jsonl'
    expected_lock = _default_lock_path(target)
    with mock.patch.object(_journal.fcntl, 'flock') as flock_mock:
        _journal.write_jsonl_row(target, {'hello': 'world'}, lock_path=None)
    assert flock_mock.call_count == 2, f'expected exactly two flock calls (lock + unlock) when lock_path is None; got {flock_mock.call_count}'
    first_call, second_call = flock_mock.call_args_list
    assert first_call.args[1] == fcntl.LOCK_EX
    assert second_call.args[1] == fcntl.LOCK_UN
    locked_fd = first_call.args[0]
    assert getattr(locked_fd, 'name', None) == str(expected_lock)
    assert expected_lock.exists(), 'default per-target lock file was not created'

def test_hermetic_tmp_path_usage(tmp_path):
    """The writer must operate entirely under tmp_path, creating both the
    target and its default lock file there and nothing outside."""
    target = tmp_path / 'sub' / 'hermetic.jsonl'
    expected_lock = _default_lock_path(target)
    _journal.write_jsonl_row(target, {'a': 1}, lock_path=None)
    assert target.exists()
    assert _read_rows(target) == [{'a': 1}]
    assert expected_lock.exists(), 'no default lock file created under tmp_path'
    assert tmp_path in target.parents
    assert tmp_path in expected_lock.parents

def test_appends_preserve_order_under_locks(tmp_path):
    """Sequential appends through the default-lock path preserve write order."""
    target = tmp_path / 'order.jsonl'
    rows = [{'seq': i} for i in range(5)]
    for r in rows:
        _journal.write_jsonl_row(target, r, lock_path=None)
    assert _read_rows(target) == rows

def test_parent_dir_creation_under_default_lock(tmp_path):
    """The writer creates missing parent directories even when locking via
    the derived default lock path."""
    target = tmp_path / 'deeply' / 'nested' / 'dir' / 'j.jsonl'
    assert not target.parent.exists()
    _journal.write_jsonl_row(target, {'created': True}, lock_path=None)
    assert target.parent.is_dir()
    assert _read_rows(target) == [{'created': True}]

def test_explicit_lock_path_still_supported(tmp_path):
    """A caller-supplied lock_path keeps working (positive control)."""
    target = tmp_path / 'explicit.jsonl'
    lock_path = tmp_path / 'explicit.custom.lock'
    _journal.write_jsonl_row(target, {'x': 1}, lock_path=lock_path)
    _journal.write_jsonl_row(target, {'x': 2}, lock_path=lock_path)
    assert _read_rows(target) == [{'x': 1}, {'x': 2}]
    assert lock_path.exists()

def test_flock_called_lock_then_unlock_when_lock_path_none(tmp_path):
    """Negative/positive control on the locking sequence: exactly one
    acquire and one release happen for a None-lock write."""
    target = tmp_path / 'seq.jsonl'
    with mock.patch.object(_journal.fcntl, 'flock') as flock_mock:
        _journal.write_jsonl_row(target, {'n': 1}, lock_path=None)
    ops = [c.args[1] for c in flock_mock.call_args_list]
    assert ops == [fcntl.LOCK_EX, fcntl.LOCK_UN]

def test_no_extra_files_created_outside_target_and_lock(tmp_path):
    """A None-lock write creates only the target and its derived lock file."""
    target = tmp_path / 'clean.jsonl'
    expected_lock = _default_lock_path(target)
    _journal.write_jsonl_row(target, {'ok': 1}, lock_path=None)
    created = {p.name for p in tmp_path.iterdir()}
    assert created == {target.name, expected_lock.name}