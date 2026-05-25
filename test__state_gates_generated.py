"""Verification oracle for harness.hooks._state_gates.read_state_besteffort.

read_state_besteffort() performs a best-effort read of STATE.json:
  * resolves the target via the module-level _state_file()
  * returns {} when the file does not exist
  * returns the JSON-decoded content (utf-8) when the file is valid
  * returns {} when the content is corrupt JSON (json.JSONDecodeError)
  * returns {} when reading raises an OSError (e.g. target is a directory)

Each test isolates the unit by monkeypatching the sibling _state_file() to a
path the test controls, so the test never depends on _state_file()'s own
(possibly still-stubbed) implementation -- the behaviour exercised is purely
read_state_besteffort()'s own missing/valid/corrupt handling.
"""
from __future__ import annotations

import json

import pytest

from harness.hooks import _state_gates
from harness.hooks._state_gates import read_state_besteffort


def _point_state_file_at(monkeypatch, target):
    """Make read_state_besteffort() resolve STATE.json to `target`."""
    monkeypatch.setattr(_state_gates, "_state_file", lambda: target)


def test_read_state_besteffort_returns_empty_dict_when_file_missing(tmp_path, monkeypatch):
    target = tmp_path / "STATE.json"
    assert not target.exists()
    _point_state_file_at(monkeypatch, target)

    result = read_state_besteffort()

    assert result == {}
    assert isinstance(result, dict)


def test_read_state_besteffort_returns_parsed_dict_for_valid_json(tmp_path, monkeypatch):
    target = tmp_path / "STATE.json"
    payload = {
        "round": 3,
        "phase": "synthesis",
        "task_id": "T-42",
        "nested": {"flags": [1, 2, 3], "ok": True},
    }
    target.write_text(json.dumps(payload), encoding="utf-8")
    _point_state_file_at(monkeypatch, target)

    result = read_state_besteffort()

    assert result == payload


def test_read_state_besteffort_returns_empty_dict_on_corrupt_json(tmp_path, monkeypatch):
    target = tmp_path / "STATE.json"
    target.write_text("{ this is : not valid json ,,, ", encoding="utf-8")
    _point_state_file_at(monkeypatch, target)

    result = read_state_besteffort()

    assert result == {}


def test_read_state_besteffort_returns_empty_dict_on_empty_file(tmp_path, monkeypatch):
    # An empty file is not valid JSON -> json.JSONDecodeError -> {}.
    target = tmp_path / "STATE.json"
    target.write_text("", encoding="utf-8")
    _point_state_file_at(monkeypatch, target)

    result = read_state_besteffort()

    assert result == {}


def test_read_state_besteffort_returns_empty_dict_on_oserror(tmp_path, monkeypatch):
    # target exists but is a directory: read_text raises IsADirectoryError
    # (an OSError subclass), which must be swallowed and yield {}.
    target = tmp_path / "STATE.json"
    target.mkdir()
    assert target.exists()
    _point_state_file_at(monkeypatch, target)

    result = read_state_besteffort()

    assert result == {}


def test_read_state_besteffort_decodes_utf8_content(tmp_path, monkeypatch):
    target = tmp_path / "STATE.json"
    payload = {"note": "café ☕ naïve — ünïcodé"}
    target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    _point_state_file_at(monkeypatch, target)

    result = read_state_besteffort()

    assert result == payload


def test_read_state_besteffort_reflects_current_file_contents(tmp_path, monkeypatch):
    # Best-effort read is not cached: a second read after a rewrite must
    # observe the new contents (the function re-reads the file each call).
    target = tmp_path / "STATE.json"
    _point_state_file_at(monkeypatch, target)

    target.write_text(json.dumps({"round": 1}), encoding="utf-8")
    assert read_state_besteffort() == {"round": 1}

    target.write_text(json.dumps({"round": 2}), encoding="utf-8")
    assert read_state_besteffort() == {"round": 2}

