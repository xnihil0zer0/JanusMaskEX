"""P0.3 adversarial battery — session_namer filename contract.

Covers the master plan's Phase 0 adversarial row:
    Revert P0.3 filename wiring, run two-round cross-exam fixture.
    Expected: round-1 file overwrite detected by test.

Mutation tests verify that reverting the fix breaks the contract (no-mutation = not counted).
"""

from __future__ import annotations

import json
import pathlib
import sys
from unittest import mock

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from harness import cross_examiner as ce_mod
from harness import session_namer as sn_mod
from harness.cross_examiner import (
    ExamPacket,
    clear_feedback_files,
    write_feedback_files,
)


def _make_packet(agent: str) -> ExamPacket:
    return ExamPacket(
        agent=agent,
        code_under_review="def f(): pass\n",
        task_specification="spec",
        fuzz_failures=[],
        review_prompt="review this",
    )


# ---------------------------------------------------------------------------
# Attack 1: two-round cross-exam must NOT overwrite round-1 feedback
# ---------------------------------------------------------------------------

def test_two_round_feedback_no_overwrite(tmp_path, monkeypatch):
    """Round-1 and round-2 feedback files must coexist."""
    monkeypatch.setenv("JANUSMASK_TASK_ID", "T-multi")
    claude = _make_packet("claude")
    gemini = _make_packet("gemini")

    write_feedback_files(tmp_path, claude, gemini, round_number=1)
    r1_files = sorted(p.name for p in (tmp_path / "sessions").glob("*_feedback.json"))
    assert r1_files == [
        "T-multi_round1_claude_feedback.json",
        "T-multi_round1_gemini_feedback.json",
    ]

    write_feedback_files(tmp_path, claude, gemini, round_number=2)
    all_files = sorted(p.name for p in (tmp_path / "sessions").glob("*_feedback.json"))
    assert all_files == [
        "T-multi_round1_claude_feedback.json",
        "T-multi_round1_gemini_feedback.json",
        "T-multi_round2_claude_feedback.json",
        "T-multi_round2_gemini_feedback.json",
    ]


def test_feedback_filename_contains_round_and_task(tmp_path, monkeypatch):
    """Filename must include round number and task_id — the contract P0.3 restores."""
    monkeypatch.setenv("JANUSMASK_TASK_ID", "T-x")
    write_feedback_files(tmp_path, _make_packet("claude"), _make_packet("gemini"), round_number=3)
    produced = {p.name for p in (tmp_path / "sessions").glob("*_feedback.json")}
    assert "T-x_round3_claude_feedback.json" in produced
    assert "T-x_round3_gemini_feedback.json" in produced


# ---------------------------------------------------------------------------
# Attack 2: clear_feedback_files must clear across rounds
# ---------------------------------------------------------------------------

def test_clear_feedback_removes_all_rounds(tmp_path, monkeypatch):
    monkeypatch.setenv("JANUSMASK_TASK_ID", "T-clear")
    write_feedback_files(tmp_path, _make_packet("claude"), _make_packet("gemini"), round_number=1)
    write_feedback_files(tmp_path, _make_packet("claude"), _make_packet("gemini"), round_number=2)
    assert len(list((tmp_path / "sessions").glob("*_feedback.json"))) == 4

    clear_feedback_files(tmp_path)
    assert len(list((tmp_path / "sessions").glob("*_feedback.json"))) == 0


# ---------------------------------------------------------------------------
# Attack 3: orchestrator submission filename uses helper
# ---------------------------------------------------------------------------

def test_collect_submissions_uses_helper(tmp_path, monkeypatch):
    from harness import orchestrator as orch_mod
    monkeypatch.setenv("JANUSMASK_TASK_ID", "T-sub")
    sessions = tmp_path / "sessions"
    sessions.mkdir()

    # Use the helper directly to write — proving the reader finds files
    # named exactly as the helper produces.
    for agent in ("claude", "gemini"):
        fn = sn_mod.generate_submission_filename(agent, 5, "T-sub")
        (sessions / fn).write_text(json.dumps({"code": f"# {agent}\n"}), encoding="utf-8")

    claude_code, gemini_code = orch_mod.collect_submissions(tmp_path, round_number=5)
    assert claude_code == "# claude\n"
    assert gemini_code == "# gemini\n"


# ---------------------------------------------------------------------------
# Attack 4: all three modules import the helpers (P0.3 DoD #3)
# ---------------------------------------------------------------------------

def test_all_modules_import_session_namer():
    from harness import cross_examiner, mcp_server, orchestrator
    for mod, symbol in (
        (orchestrator, "generate_submission_filename"),
        (orchestrator, "generate_feedback_filename"),
        (cross_examiner, "generate_feedback_filename"),
        (mcp_server, "generate_submission_filename"),
        (mcp_server, "generate_feedback_filename"),
    ):
        assert hasattr(mod, symbol), f"{mod.__name__} missing {symbol}"


# ---------------------------------------------------------------------------
# Attack 5: mutation — revert the wiring, confirm tests catch it
# ---------------------------------------------------------------------------

def test_mutation_revert_cross_examiner_overwrites_round1(tmp_path, monkeypatch):
    """Pre-P0.3 behaviour used prefix only — overwrote across rounds."""
    monkeypatch.setenv("JANUSMASK_TASK_ID", "T-mut")

    def _legacy_write(state_dir, claude_packet, gemini_packet, round_number):
        import os as _os
        sessions_dir = state_dir / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)
        for packet in (claude_packet, gemini_packet):
            feedback = {"round": round_number, "code_under_review": packet.code_under_review}
            task_id = _os.environ.get("JANUSMASK_TASK_ID", "")
            prefix = f"{task_id}_" if task_id else ""
            path = sessions_dir / f"{prefix}{packet.agent}_feedback.json"
            with open(path, "w") as f:
                json.dump(feedback, f)

    with mock.patch.object(ce_mod, "write_feedback_files", _legacy_write):
        ce_mod.write_feedback_files(tmp_path, _make_packet("claude"), _make_packet("gemini"), round_number=1)
        ce_mod.write_feedback_files(tmp_path, _make_packet("claude"), _make_packet("gemini"), round_number=2)
        files = sorted(p.name for p in (tmp_path / "sessions").glob("*_feedback.json"))
        # Legacy produces only 2 files — round1 overwritten.
        assert files == ["T-mut_claude_feedback.json", "T-mut_gemini_feedback.json"]
        # And round-1 content is gone.
        data = json.loads((tmp_path / "sessions" / "T-mut_claude_feedback.json").read_text())
        assert data["round"] == 2

    # Post-fix (real function) keeps both rounds.
    tmp2 = tmp_path / "fixed"
    ce_mod.write_feedback_files(tmp2, _make_packet("claude"), _make_packet("gemini"), round_number=1)
    ce_mod.write_feedback_files(tmp2, _make_packet("claude"), _make_packet("gemini"), round_number=2)
    files = sorted(p.name for p in (tmp2 / "sessions").glob("*_feedback.json"))
    assert len(files) == 4


def test_feedback_glob_pattern_matches_all_rounds(tmp_path):
    pattern = sn_mod.feedback_glob_pattern("claude", "T-g")
    assert pattern == "T-g_round*_claude_feedback.json"
    # And with no task_id → matches any task.
    pattern_any = sn_mod.feedback_glob_pattern("gemini", None)
    assert pattern_any == "*_round*_gemini_feedback.json"
