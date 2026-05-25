"""Adversarial coverage for ``scripts/impl_drain_capture.py::_clear_stale_task_state``.

The function deletes stale ``state/tasks/processed/<task_id>.json`` entries
and stale ``state/sessions/*_<task_id>_submission.json`` files for every
task in the merged plan, so a ``--skip-planner`` re-run actually picks up
the same task IDs again instead of treating them as already-processed.

Coverage gap closed:
    The recovery brief (2026-04-19T22:00Z B3 blocker #11) flagged that
    the prior version of these tests was lost in the reset. This file
    pins the behavioural contract of the recovered helper so future
    edits cannot silently drift.

All tests work on tmp paths; no real orchestrator/planner is spawned.
"""
from __future__ import annotations

import io
import json
import pathlib
import sys

import pytest


_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))
import impl_drain_capture as wrapper  # noqa: E402


def _setup_state(tmp_path: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
    state_dir = tmp_path / "state"
    processed = state_dir / "tasks" / "processed"
    sessions = state_dir / "sessions"
    processed.mkdir(parents=True)
    sessions.mkdir(parents=True)
    return state_dir, processed, sessions


# ---------------------------------------------------------------------------
# Happy path: stale processed + session files are unlinked.
# ---------------------------------------------------------------------------

def test_clear_stale_unlinks_processed_entry(tmp_path):
    state_dir, processed, _sessions = _setup_state(tmp_path)
    (processed / "TASK-A.json").write_text("{}", encoding="utf-8")
    plan = {"tasks": [{"task_id": "TASK-A"}]}

    n = wrapper._clear_stale_task_state(plan, state_dir, io.StringIO())

    assert n == 1
    assert not (processed / "TASK-A.json").exists()


def test_clear_stale_unlinks_session_submissions(tmp_path):
    state_dir, _processed, sessions = _setup_state(tmp_path)
    # Pattern matches ``*_<task_id>_submission.json``.
    (sessions / "claude_TASK-B_submission.json").write_text("{}", encoding="utf-8")
    (sessions / "gemini_TASK-B_submission.json").write_text("{}", encoding="utf-8")
    plan = {"tasks": [{"task_id": "TASK-B"}]}

    n = wrapper._clear_stale_task_state(plan, state_dir, io.StringIO())

    assert n == 2
    assert list(sessions.glob("*_TASK-B_submission.json")) == []


def test_clear_stale_processed_plus_sessions_combined_count(tmp_path):
    """Total returned count = processed deletions + session deletions."""
    state_dir, processed, sessions = _setup_state(tmp_path)
    (processed / "TASK-C.json").write_text("{}", encoding="utf-8")
    (sessions / "claude_TASK-C_submission.json").write_text("{}", encoding="utf-8")
    (sessions / "gemini_TASK-C_submission.json").write_text("{}", encoding="utf-8")
    plan = {"tasks": [{"task_id": "TASK-C"}]}

    n = wrapper._clear_stale_task_state(plan, state_dir, io.StringIO())

    # 1 processed + 2 sessions = 3.
    assert n == 3


def test_clear_stale_handles_multiple_tasks(tmp_path):
    state_dir, processed, sessions = _setup_state(tmp_path)
    for tid in ("T1", "T2", "T3"):
        (processed / f"{tid}.json").write_text("{}", encoding="utf-8")
        (sessions / f"claude_{tid}_submission.json").write_text("{}", encoding="utf-8")
    plan = {"tasks": [{"task_id": "T1"}, {"task_id": "T2"}, {"task_id": "T3"}]}

    n = wrapper._clear_stale_task_state(plan, state_dir, io.StringIO())

    assert n == 6
    for tid in ("T1", "T2", "T3"):
        assert not (processed / f"{tid}.json").exists()
        assert list(sessions.glob(f"*_{tid}_submission.json")) == []


# ---------------------------------------------------------------------------
# Schema flexibility: dict-with-tasks vs bare list.
# ---------------------------------------------------------------------------

def test_clear_stale_accepts_bare_task_list(tmp_path):
    """Wrapper tolerates ``[{...}, {...}]`` as well as ``{"tasks": [...]}``."""
    state_dir, processed, _sessions = _setup_state(tmp_path)
    (processed / "TASK-D.json").write_text("{}", encoding="utf-8")
    plan_as_list = [{"task_id": "TASK-D"}]

    n = wrapper._clear_stale_task_state(plan_as_list, state_dir, io.StringIO())

    assert n == 1
    assert not (processed / "TASK-D.json").exists()


# ---------------------------------------------------------------------------
# Defensive shape handling — bad inputs must not raise.
# ---------------------------------------------------------------------------

def test_clear_stale_none_plan_returns_zero(tmp_path):
    state_dir, _processed, _sessions = _setup_state(tmp_path)
    n = wrapper._clear_stale_task_state(None, state_dir, io.StringIO())
    assert n == 0


def test_clear_stale_string_plan_returns_zero(tmp_path):
    """Top-level non-dict, non-list payload yields zero unlinks."""
    state_dir, _processed, _sessions = _setup_state(tmp_path)
    n = wrapper._clear_stale_task_state("not-a-plan", state_dir, io.StringIO())
    assert n == 0


def test_clear_stale_dict_without_tasks_returns_zero(tmp_path):
    state_dir, _processed, _sessions = _setup_state(tmp_path)
    n = wrapper._clear_stale_task_state({"other_key": []}, state_dir, io.StringIO())
    assert n == 0


def test_clear_stale_tasks_not_a_list_returns_zero(tmp_path):
    state_dir, _processed, _sessions = _setup_state(tmp_path)
    n = wrapper._clear_stale_task_state(
        {"tasks": "not-a-list"}, state_dir, io.StringIO()
    )
    assert n == 0


def test_clear_stale_skips_non_dict_task_entries(tmp_path):
    state_dir, processed, _sessions = _setup_state(tmp_path)
    (processed / "GOOD.json").write_text("{}", encoding="utf-8")
    plan = {"tasks": ["not-a-dict", 42, None, {"task_id": "GOOD"}]}
    n = wrapper._clear_stale_task_state(plan, state_dir, io.StringIO())
    assert n == 1
    assert not (processed / "GOOD.json").exists()


def test_clear_stale_skips_task_without_string_task_id(tmp_path):
    state_dir, processed, _sessions = _setup_state(tmp_path)
    (processed / "OK.json").write_text("{}", encoding="utf-8")
    plan = {"tasks": [
        {"task_id": 42},          # not a string
        {"task_id": ""},          # empty string
        {"missing": True},        # missing entirely
        {"task_id": "OK"},
    ]}
    n = wrapper._clear_stale_task_state(plan, state_dir, io.StringIO())
    assert n == 1
    assert not (processed / "OK.json").exists()


# ---------------------------------------------------------------------------
# No-op safety: missing files / missing dirs.
# ---------------------------------------------------------------------------

def test_clear_stale_missing_processed_file_is_noop(tmp_path):
    """Task in plan but no processed entry on disk => zero deletions, no error."""
    state_dir, _processed, _sessions = _setup_state(tmp_path)
    plan = {"tasks": [{"task_id": "MISSING"}]}
    n = wrapper._clear_stale_task_state(plan, state_dir, io.StringIO())
    assert n == 0


def test_clear_stale_missing_sessions_dir_is_noop(tmp_path):
    """No sessions/ directory at all => only processed entries cleaned."""
    state_dir = tmp_path / "state"
    processed = state_dir / "tasks" / "processed"
    processed.mkdir(parents=True)
    # Intentionally no sessions/ dir.
    (processed / "TASK-E.json").write_text("{}", encoding="utf-8")
    plan = {"tasks": [{"task_id": "TASK-E"}]}

    n = wrapper._clear_stale_task_state(plan, state_dir, io.StringIO())

    assert n == 1
    assert not (processed / "TASK-E.json").exists()


def test_clear_stale_missing_processed_dir_is_noop_for_sessions(tmp_path):
    """No processed/ dir => only session submissions cleaned."""
    state_dir = tmp_path / "state"
    sessions = state_dir / "sessions"
    sessions.mkdir(parents=True)
    # Intentionally no processed/ dir.
    (sessions / "claude_TASK-F_submission.json").write_text("{}", encoding="utf-8")
    plan = {"tasks": [{"task_id": "TASK-F"}]}

    n = wrapper._clear_stale_task_state(plan, state_dir, io.StringIO())

    assert n == 1
    assert list(sessions.glob("*_TASK-F_submission.json")) == []


# ---------------------------------------------------------------------------
# Stderr observability: each unlink is logged.
# ---------------------------------------------------------------------------

def test_clear_stale_writes_processed_unlink_to_stderr(tmp_path):
    state_dir, processed, _sessions = _setup_state(tmp_path)
    (processed / "TASK-G.json").write_text("{}", encoding="utf-8")
    plan = {"tasks": [{"task_id": "TASK-G"}]}
    buf = io.StringIO()

    wrapper._clear_stale_task_state(plan, state_dir, buf)

    output = buf.getvalue()
    assert "cleared stale processed entry" in output
    assert "TASK-G.json" in output


def test_clear_stale_writes_session_unlink_to_stderr(tmp_path):
    state_dir, _processed, sessions = _setup_state(tmp_path)
    (sessions / "claude_TASK-H_submission.json").write_text("{}", encoding="utf-8")
    plan = {"tasks": [{"task_id": "TASK-H"}]}
    buf = io.StringIO()

    wrapper._clear_stale_task_state(plan, state_dir, buf)

    output = buf.getvalue()
    assert "cleared stale submission" in output
    assert "TASK-H_submission.json" in output


# ---------------------------------------------------------------------------
# Boundary: only matches the exact ``*_<task_id>_submission.json`` pattern.
# ---------------------------------------------------------------------------

def test_clear_stale_does_not_match_unrelated_session_files(tmp_path):
    state_dir, _processed, sessions = _setup_state(tmp_path)
    # Real submission for TASK-I (must be cleared).
    (sessions / "claude_TASK-I_submission.json").write_text("{}", encoding="utf-8")
    # Unrelated files that happen to live in sessions/ — must survive.
    (sessions / "claude_TASK-I_feedback.json").write_text("{}", encoding="utf-8")
    (sessions / "TASK-I.log").write_text("x", encoding="utf-8")
    (sessions / "claude_OTHER_submission.json").write_text("{}", encoding="utf-8")
    plan = {"tasks": [{"task_id": "TASK-I"}]}

    n = wrapper._clear_stale_task_state(plan, state_dir, io.StringIO())

    assert n == 1
    # Survivors:
    assert (sessions / "claude_TASK-I_feedback.json").exists()
    assert (sessions / "TASK-I.log").exists()
    assert (sessions / "claude_OTHER_submission.json").exists()
