"""P4 invariant: cross_examiner write/clear parity (HOOK-42).

Sub-plan 04 §3.5 requires the writer (``cross_examiner.write_feedback_files``)
and the sweeper (``cross_examiner.clear_feedback_files``) to agree on the
filename schema so feedback files don't silently accumulate across rounds.
``harness/session_namer.py`` (P0.3) is the single source of truth for that
schema; the invariant here is that a write followed by a clear leaves the
sessions dir empty.

Schema (locked): ``{task_id}_round{N}_{agent}_feedback.json``
"""

from __future__ import annotations

import fnmatch
import os
import pathlib
import sys

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from harness.cross_examiner import (  # noqa: E402
    ExamPacket,
    clear_feedback_files,
    write_feedback_files,
)
from harness.session_namer import (  # noqa: E402
    feedback_glob_pattern,
    generate_feedback_filename,
)


def _packets() -> tuple[ExamPacket, ExamPacket]:
    return (
        ExamPacket(
            agent="claude",
            code_under_review="def a(): return 1",
            task_specification="",
            fuzz_failures=[],
            review_prompt="review",
        ),
        ExamPacket(
            agent="gemini",
            code_under_review="def b(): return 2",
            task_specification="",
            fuzz_failures=[],
            review_prompt="review",
        ),
    )


def test_generate_filename_matches_glob_pattern():
    # The glob pattern must match the filename the writer picks.
    for task_id in ("STAB-001", "HOOK-42-demo", "t_123"):
        for agent in ("claude", "gemini"):
            fname = generate_feedback_filename(agent, 1, task_id)
            pattern = feedback_glob_pattern(agent, task_id)
            assert fnmatch.fnmatch(fname, pattern), (
                f"filename {fname} does not match glob {pattern}"
            )


def test_write_then_clear_roundtrip_leaves_no_residue(tmp_path, monkeypatch):
    monkeypatch.setenv("JANUSMASK_TASK_ID", "STAB-001")
    claude_pkt, gemini_pkt = _packets()

    write_feedback_files(tmp_path, claude_pkt, gemini_pkt, round_number=1)
    sessions = tmp_path / "sessions"
    assert sorted(p.name for p in sessions.iterdir()) == [
        "STAB-001_round1_claude_feedback.json",
        "STAB-001_round1_gemini_feedback.json",
    ]

    clear_feedback_files(tmp_path)
    residue = [p.name for p in sessions.iterdir()]
    assert residue == [], f"residue after clear: {residue}"


def test_writer_uses_session_namer_exact_filenames(tmp_path, monkeypatch):
    monkeypatch.setenv("JANUSMASK_TASK_ID", "EDGE-007")
    claude_pkt, gemini_pkt = _packets()
    write_feedback_files(tmp_path, claude_pkt, gemini_pkt, round_number=4)

    for agent in ("claude", "gemini"):
        expected = generate_feedback_filename(agent, 4, "EDGE-007")
        assert (tmp_path / "sessions" / expected).is_file()


def test_glob_matches_multiple_rounds(tmp_path, monkeypatch):
    # clear_feedback_files must sweep ALL rounds for the active task,
    # per sub-plan 04 §3.5 ("Keep clear_feedback_files glob
    # {task_id}_round*_{agent}_feedback.json").
    monkeypatch.setenv("JANUSMASK_TASK_ID", "STAB-002")
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    for round_number in (1, 2, 3):
        for agent in ("claude", "gemini"):
            (sessions / generate_feedback_filename(agent, round_number, "STAB-002")).write_text(
                "{}", encoding="utf-8"
            )
    # Plant one file for a DIFFERENT task — must survive the clear.
    (sessions / generate_feedback_filename("claude", 1, "OTHER-TASK")).write_text(
        "{}", encoding="utf-8"
    )

    clear_feedback_files(tmp_path)

    remaining = sorted(p.name for p in sessions.iterdir())
    assert remaining == [
        generate_feedback_filename("claude", 1, "OTHER-TASK"),
    ], f"clear swept wrong files: {remaining}"


def test_clear_with_no_task_id_uses_wildcard(tmp_path, monkeypatch):
    # If JANUSMASK_TASK_ID is unset, clear_feedback_files falls back to
    # a task-wildcard glob — this is the "end of pipeline" sweep.
    monkeypatch.delenv("JANUSMASK_TASK_ID", raising=False)
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    (sessions / "A_round1_claude_feedback.json").write_text("{}", encoding="utf-8")
    (sessions / "B_round2_gemini_feedback.json").write_text("{}", encoding="utf-8")
    # Non-feedback files must survive.
    (sessions / "claude_round1_A_submission.json").write_text("{}", encoding="utf-8")

    clear_feedback_files(tmp_path)

    remaining = sorted(p.name for p in sessions.iterdir())
    assert remaining == ["claude_round1_A_submission.json"]
