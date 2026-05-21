import json

import pytest

from harness._journal import write_jsonl_row


def test_write_jsonl_row_writes_json_line(tmp_path):
    path = tmp_path / "journal.jsonl"
    row = {"event": "start", "id": 1}
    write_jsonl_row(path, row)
    content = path.read_text(encoding="utf-8")
    # Exactly one json.dumps-encoded line terminated by a newline.
    assert content == json.dumps(row) + "\n"
    assert content.endswith("\n")
    assert json.loads(content) == row


def test_write_jsonl_row_creates_parent_directory(tmp_path):
    path = tmp_path / "deep" / "nested" / "dir" / "journal.jsonl"
    assert not path.parent.exists()
    write_jsonl_row(path, {"k": "v"})
    assert path.parent.is_dir()
    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8")) == {"k": "v"}


def test_write_jsonl_row_appends_multiple_rows(tmp_path):
    path = tmp_path / "journal.jsonl"
    write_jsonl_row(path, {"n": 1})
    write_jsonl_row(path, {"n": 2})
    write_jsonl_row(path, {"n": 3})
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert [json.loads(line) for line in lines] == [{"n": 1}, {"n": 2}, {"n": 3}]


def test_write_jsonl_row_preserves_existing_content(tmp_path):
    path = tmp_path / "journal.jsonl"
    path.write_text('{"pre": true}\n', encoding="utf-8")
    write_jsonl_row(path, {"new": 1})
    lines = path.read_text(encoding="utf-8").splitlines()
    # Append mode: original content is retained, new row added after it.
    assert len(lines) == 2
    assert json.loads(lines[0]) == {"pre": True}
    assert json.loads(lines[1]) == {"new": 1}


def test_write_jsonl_row_returns_none(tmp_path):
    path = tmp_path / "journal.jsonl"
    result = write_jsonl_row(path, {"x": 1})
    assert result is None


def test_write_jsonl_row_empty_dict(tmp_path):
    path = tmp_path / "journal.jsonl"
    write_jsonl_row(path, {})
    assert path.read_text(encoding="utf-8") == "{}\n"


def test_write_jsonl_row_serializes_nested_and_unicode(tmp_path):
    path = tmp_path / "journal.jsonl"
    row = {
        "name": "café",
        "nested": {"list": [1, 2, 3], "flag": True, "none": None},
    }
    write_jsonl_row(path, row)
    content = path.read_text(encoding="utf-8")
    # Encoding must match json.dumps' default (ensure_ascii) exactly and round-trip.
    assert content == json.dumps(row) + "\n"
    assert json.loads(content) == row


def test_write_jsonl_row_with_lock_path_writes_row(tmp_path):
    path = tmp_path / "journal.jsonl"
    lock_path = tmp_path / "journal.lock"
    row = {"event": "locked", "id": 7}
    write_jsonl_row(path, row, lock_path=lock_path)
    assert json.loads(path.read_text(encoding="utf-8")) == row
    # The lock file is created as a side effect of acquiring the lock.
    assert lock_path.exists()


def test_write_jsonl_row_with_lock_path_appends(tmp_path):
    path = tmp_path / "journal.jsonl"
    lock_path = tmp_path / "journal.lock"
    write_jsonl_row(path, {"n": 1}, lock_path=lock_path)
    write_jsonl_row(path, {"n": 2}, lock_path=lock_path)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line) for line in lines] == [{"n": 1}, {"n": 2}]


def test_write_jsonl_row_with_lock_path_creates_parent_directory(tmp_path):
    path = tmp_path / "sub" / "journal.jsonl"
    lock_path = tmp_path / "sub" / "journal.lock"
    assert not path.parent.exists()
    write_jsonl_row(path, {"k": "v"}, lock_path=lock_path)
    assert path.parent.is_dir()
    assert json.loads(path.read_text(encoding="utf-8")) == {"k": "v"}
