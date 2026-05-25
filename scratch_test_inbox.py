from __future__ import annotations

import pathlib
import pytest

# Target under test
import temp_submission as _submission

def _recording(return_path):
    """A ``_work_dir`` stand-in that records each call's ``(session_id, agent)``."""
    calls: list[tuple[object, object]] = []

    def fake(session_id=None, *, agent=None):
        calls.append((session_id, agent))
        return return_path

    return fake, calls

def test_inbox_dir_appends_inbox_segment(tmp_path, monkeypatch):
    work = tmp_path / "wd"
    monkeypatch.setattr(
        _submission, "_work_dir", lambda session_id=None, *, agent=None: work
    )

    result = _submission._inbox_dir()

    assert result == work / "inbox"
    assert result.name == "inbox"
    assert isinstance(result, pathlib.Path)

def test_inbox_dir_builds_on_distinct_work_dirs(tmp_path, monkeypatch):
    work1 = tmp_path / "wd1"
    work2 = tmp_path / "wd2"
    
    # We can test that it uses the output of _work_dir
    monkeypatch.setattr(
        _submission, "_work_dir", lambda session_id=None, *, agent=None: work1
    )
    assert _submission._inbox_dir() == work1 / "inbox"
    
    monkeypatch.setattr(
        _submission, "_work_dir", lambda session_id=None, *, agent=None: work2
    )
    assert _submission._inbox_dir() == work2 / "inbox"

def test_inbox_dir_defaults_pass_none(tmp_path, monkeypatch):
    fake, calls = _recording(tmp_path / "wd")
    monkeypatch.setattr(_submission, "_work_dir", fake)

    _submission._inbox_dir()

    assert calls == [(None, None)]

def test_inbox_dir_forwards_session_id_and_agent(tmp_path, monkeypatch):
    fake, calls = _recording(tmp_path / "wd")
    monkeypatch.setattr(_submission, "_work_dir", fake)

    _submission._inbox_dir("sess-123", agent="gemini")

    assert calls == [("sess-123", "gemini")]
