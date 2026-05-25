"""P4 adversarial battery — HOOK-42 cross-examiner write/clear parity.

Mutation tests per augmented plan §5 P4 row: break the filename contract
or the glob, confirm the parity tests catch it, then restore.
"""

from __future__ import annotations

import fnmatch
import os
import pathlib
import sys
from unittest import mock

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from harness import cross_examiner as xam  # noqa: E402
from harness import session_namer  # noqa: E402


def _packets() -> tuple[xam.ExamPacket, xam.ExamPacket]:
    return (
        xam.ExamPacket(
            agent="claude",
            code_under_review="def a(): return 1",
            task_specification="",
            fuzz_failures=[],
            review_prompt="r",
        ),
        xam.ExamPacket(
            agent="gemini",
            code_under_review="def b(): return 2",
            task_specification="",
            fuzz_failures=[],
            review_prompt="r",
        ),
    )


# ---------------------------------------------------------------------------
# Attack 1: two consecutive cross-exam rounds must not leak files between
# them — the sweep has to clear every round for the current task.
# ---------------------------------------------------------------------------

def test_round2_starts_clean_after_round1_clear(tmp_path, monkeypatch):
    monkeypatch.setenv("JANUSMASK_TASK_ID", "STAB-003")
    c_pkt, g_pkt = _packets()

    xam.write_feedback_files(tmp_path, c_pkt, g_pkt, round_number=1)
    xam.clear_feedback_files(tmp_path)

    xam.write_feedback_files(tmp_path, c_pkt, g_pkt, round_number=2)
    names = sorted(p.name for p in (tmp_path / "sessions").iterdir())
    assert names == [
        "STAB-003_round2_claude_feedback.json",
        "STAB-003_round2_gemini_feedback.json",
    ]


# ---------------------------------------------------------------------------
# Attack 2: mutation — writer drops the round component (pre-P0.3
# schema). The round-trip parity test would catch this because the
# clear-glob now misses the written file.
# ---------------------------------------------------------------------------

def _legacy_generate_feedback_filename(agent, round_number, task_id, timestamp_str=None):
    # Pre-P0.3 schema; note: no round component.
    return f"{task_id}_{agent}_feedback.json"


def test_mutation_legacy_filename_breaks_glob_match():
    for task_id in ("STAB-001",):
        for agent in ("claude", "gemini"):
            legacy = _legacy_generate_feedback_filename(agent, 1, task_id)
            current_glob = session_namer.feedback_glob_pattern(agent, task_id)
            assert not fnmatch.fnmatch(legacy, current_glob), (
                "legacy filename should NOT match the current glob — "
                "that's the whole point of the parity check"
            )


def test_mutation_revert_writer_leaks_files(tmp_path, monkeypatch):
    monkeypatch.setenv("JANUSMASK_TASK_ID", "STAB-MUTATE")

    with mock.patch.object(
        xam, "generate_feedback_filename", _legacy_generate_feedback_filename
    ):
        c_pkt, g_pkt = _packets()
        xam.write_feedback_files(tmp_path, c_pkt, g_pkt, round_number=1)
        xam.clear_feedback_files(tmp_path)

        residue = [p.name for p in (tmp_path / "sessions").iterdir()]
        # Under the mutation, the writer used the legacy schema; the
        # cleaner's glob does not match it — files leak.
        assert residue, "mutation did not reproduce pre-P0.3 leakage"

    # Post-fix (un-patched): round-trip is clean.
    c_pkt, g_pkt = _packets()
    sessions = tmp_path / "sessions"
    for p in sessions.iterdir():
        p.unlink()
    xam.write_feedback_files(tmp_path, c_pkt, g_pkt, round_number=1)
    xam.clear_feedback_files(tmp_path)
    assert list(sessions.iterdir()) == []


# ---------------------------------------------------------------------------
# Attack 3: mutation — sweeper glob is too narrow (hardcodes round=1),
# round-2 files leak across rounds.
# ---------------------------------------------------------------------------

def test_mutation_narrow_glob_misses_later_rounds(tmp_path, monkeypatch):
    monkeypatch.setenv("JANUSMASK_TASK_ID", "STAB-NARROW")

    def _narrow(agent, task_id):
        # Round hardcoded → misses round≠1 files.
        return f"{task_id or '*'}_round1_{agent}_feedback.json"

    with mock.patch.object(xam, "feedback_glob_pattern", _narrow):
        c_pkt, g_pkt = _packets()
        xam.write_feedback_files(tmp_path, c_pkt, g_pkt, round_number=2)
        xam.clear_feedback_files(tmp_path)

        residue = [p.name for p in (tmp_path / "sessions").iterdir()]
        assert residue, "narrow glob mutation did not reproduce leakage"

    # Post-fix: the wildcard-round glob sweeps round-2 files.
    sessions = tmp_path / "sessions"
    for p in sessions.iterdir():
        p.unlink()
    c_pkt, g_pkt = _packets()
    xam.write_feedback_files(tmp_path, c_pkt, g_pkt, round_number=2)
    xam.clear_feedback_files(tmp_path)
    assert list(sessions.iterdir()) == []


# ---------------------------------------------------------------------------
# Attack 4: the glob must NOT match submission files (prefix disambiguation).
# Submissions live at {agent}_round*_{task_id}_submission.json — the
# feedback glob leads with {task_id}, submissions lead with {agent}.
# ---------------------------------------------------------------------------

def test_clear_never_touches_submission_files(tmp_path, monkeypatch):
    monkeypatch.setenv("JANUSMASK_TASK_ID", "STAB-004")
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    # Plant one submission, one unrelated foreign file, and one feedback.
    keep = [
        "claude_round1_STAB-004_submission.json",
        "gemini_round2_STAB-004_submission.json",
        "some_other_file.txt",
    ]
    for name in keep:
        (sessions / name).write_text("{}", encoding="utf-8")
    (sessions / session_namer.generate_feedback_filename("claude", 1, "STAB-004")).write_text(
        "{}", encoding="utf-8"
    )

    xam.clear_feedback_files(tmp_path)

    remaining = sorted(p.name for p in sessions.iterdir())
    assert remaining == sorted(keep)


# ---------------------------------------------------------------------------
# Attack 5: write is idempotent — calling twice in the same round
# produces two files with the SAME name, not duplicates (overwrite).
# ---------------------------------------------------------------------------

def test_write_is_overwrite_not_append(tmp_path, monkeypatch):
    monkeypatch.setenv("JANUSMASK_TASK_ID", "STAB-005")
    c_pkt, g_pkt = _packets()
    xam.write_feedback_files(tmp_path, c_pkt, g_pkt, round_number=1)
    xam.write_feedback_files(tmp_path, c_pkt, g_pkt, round_number=1)
    names = sorted(p.name for p in (tmp_path / "sessions").iterdir())
    assert names == [
        "STAB-005_round1_claude_feedback.json",
        "STAB-005_round1_gemini_feedback.json",
    ]


# ---------------------------------------------------------------------------
# Attack 6: filename separator hygiene — task_ids with underscores or
# hyphens must not collide with the round marker.
# ---------------------------------------------------------------------------

def test_task_ids_with_underscores_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("JANUSMASK_TASK_ID", "STAB_weird-123")
    c_pkt, g_pkt = _packets()
    xam.write_feedback_files(tmp_path, c_pkt, g_pkt, round_number=5)
    xam.clear_feedback_files(tmp_path)
    assert list((tmp_path / "sessions").iterdir()) == []
