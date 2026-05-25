"""Tests for harness.track_record.track_record_tiebreaker."""

import json

import pytest

from harness.track_record import (
    TrackRecordUnavailable,
    _track_record_file,
    track_record_tiebreaker,
)


def _seed_state_dir(tmp_path, monkeypatch):
    """Point JANUSMASK_STATE_DIR at tmp_path and return the track-record path."""
    monkeypatch.setenv("JANUSMASK_STATE_DIR", str(tmp_path))
    return _track_record_file(tmp_path)


def _write_record(path, claude_cell, gemini_cell, meta_task_type="test_unit"):
    record = {
        "version": 1,
        "spec_authorship": {
            "claude": {meta_task_type: claude_cell},
            "gemini": {meta_task_type: gemini_cell},
        },
        "synthesis": {"claude": {}, "gemini": {}},
    }
    path.write_text(json.dumps(record))


def test_tiebreaker_file_missing_raises_unavailable(tmp_path, monkeypatch):
    _seed_state_dir(tmp_path, monkeypatch)

    with pytest.raises(TrackRecordUnavailable, match="not found"):
        track_record_tiebreaker("test_unit", None)


def test_tiebreaker_corrupt_json_raises_unavailable(tmp_path, monkeypatch):
    record_path = _seed_state_dir(tmp_path, monkeypatch)
    record_path.write_text("{not valid json")

    with pytest.raises(TrackRecordUnavailable, match="corrupt"):
        track_record_tiebreaker("test_unit", None)


def test_tiebreaker_claude_lower_failure_rate_returns_claude(tmp_path, monkeypatch):
    record_path = _seed_state_dir(tmp_path, monkeypatch)
    _write_record(
        record_path,
        claude_cell={"attempts": 10, "failures": 1},
        gemini_cell={"attempts": 10, "failures": 8},
    )

    assert track_record_tiebreaker("test_unit", None) == "claude"


def test_tiebreaker_gemini_lower_failure_rate_returns_gemini(tmp_path, monkeypatch):
    record_path = _seed_state_dir(tmp_path, monkeypatch)
    _write_record(
        record_path,
        claude_cell={"attempts": 10, "failures": 8},
        gemini_cell={"attempts": 10, "failures": 1},
    )

    assert track_record_tiebreaker("test_unit", None) == "gemini"


def test_tiebreaker_equal_rates_defaults_to_claude(tmp_path, monkeypatch):
    record_path = _seed_state_dir(tmp_path, monkeypatch)
    _write_record(
        record_path,
        claude_cell={"attempts": 10, "failures": 5},
        gemini_cell={"attempts": 10, "failures": 5},
    )

    assert track_record_tiebreaker("test_unit", None) == "claude"
