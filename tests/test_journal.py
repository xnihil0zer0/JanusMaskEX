"""Tests for harness._journal.write_jsonl_row primitive."""
from __future__ import annotations

import fcntl
import json
import multiprocessing
from unittest.mock import patch

import pytest

from harness._journal import write_jsonl_row


def test_append_creates_file_writes_valid_json_with_newline(tmp_path):
    target = tmp_path / "events.jsonl"
    row = {"ts": "2026-04-22T00:00:00Z", "msg": "hello", "n": 42}

    write_jsonl_row(target, row)

    assert target.exists()
    lines = target.read_text(encoding="utf-8").splitlines(keepends=True)
    assert len(lines) == 1
    assert lines[0].endswith("\n")
    assert json.loads(lines[0]) == row


def test_multiple_appends_preserve_order(tmp_path):
    target = tmp_path / "events.jsonl"
    for i in range(5):
        write_jsonl_row(target, {"i": i})

    rows = [json.loads(l) for l in target.read_text(encoding="utf-8").splitlines()]
    assert [r["i"] for r in rows] == [0, 1, 2, 3, 4]


def test_parent_dir_created_if_missing(tmp_path):
    target = tmp_path / "a" / "b" / "c" / "events.jsonl"

    write_jsonl_row(target, {"k": "v"})

    assert target.exists()
    assert json.loads(target.read_text(encoding="utf-8")) == {"k": "v"}


def test_default_separators_match_json_dumps_default(tmp_path):
    """Primitive uses default (loose) separators — byte-identical to
    legacy `json.dumps(row) + '\\n'` callers that PR-2/PR-3 will migrate.
    """
    target = tmp_path / "events.jsonl"
    row = {"a": 1, "b": [2, 3]}

    write_jsonl_row(target, row)

    written = target.read_text(encoding="utf-8").rstrip("\n")
    assert written == json.dumps(row)


def test_lock_acquired_and_released_when_lock_path_provided(tmp_path):
    target = tmp_path / "data.jsonl"
    lock = tmp_path / "data.lock"

    with patch("harness._journal.fcntl.flock") as mock_flock:
        write_jsonl_row(target, {"x": 1}, lock_path=lock)

    assert mock_flock.call_count == 2
    assert mock_flock.call_args_list[0][0][1] == fcntl.LOCK_EX
    assert mock_flock.call_args_list[1][0][1] == fcntl.LOCK_UN
    assert lock.exists()


def test_lock_not_acquired_when_lock_path_none(tmp_path):
    target = tmp_path / "data.jsonl"

    with patch("harness._journal.fcntl.flock") as mock_flock:
        write_jsonl_row(target, {"x": 1}, lock_path=None)

    assert mock_flock.call_count == 2
    assert mock_flock.call_args_list[0][0][1] == fcntl.LOCK_EX
    assert mock_flock.call_args_list[1][0][1] == fcntl.LOCK_UN


def test_fsync_called_on_target_fd(tmp_path):
    target = tmp_path / "data.jsonl"

    with patch("harness._journal.os.fsync") as mock_fsync:
        write_jsonl_row(target, {"x": 1})

    mock_fsync.assert_called_once()


def test_fsync_called_when_locked(tmp_path):
    target = tmp_path / "data.jsonl"
    lock = tmp_path / "data.lock"

    with patch("harness._journal.os.fsync") as mock_fsync:
        write_jsonl_row(target, {"x": 1}, lock_path=lock)

    mock_fsync.assert_called_once()


def _lock_worker(target_str: str, lock_str: str, worker_id: int, count: int) -> None:
    import pathlib
    from harness._journal import write_jsonl_row as _write

    target = pathlib.Path(target_str)
    lock = pathlib.Path(lock_str)
    for i in range(count):
        _write(target, {"worker": worker_id, "seq": i}, lock_path=lock)


def test_concurrent_writes_preserve_integrity(tmp_path):
    target = tmp_path / "data.jsonl"
    lock = tmp_path / "data.lock"

    procs = [
        multiprocessing.Process(
            target=_lock_worker,
            args=(str(target), str(lock), wid, 10),
        )
        for wid in range(3)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join()

    lines = target.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 30
    for line in lines:
        row = json.loads(line)
        assert "worker" in row and "seq" in row
