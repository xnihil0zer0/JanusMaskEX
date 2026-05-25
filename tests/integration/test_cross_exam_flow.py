"""Integration tests: Cross-examiner <-> MCP server <-> state round-trip.

Tests I-13 through I-15 from the JanusMask Phase 1 Test Plan (Section 11.4).
"""

import ast
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from harness.cross_examiner import (
    anonymize_code,
    clear_feedback_files,
    prepare_exam_packets,
    write_feedback_files,
    ExamPacket,
)
from harness.diff_fuzzer import FuzzFailure
from harness.mcp_server import JanusMaskServer
from harness.sandbox import ExecutionResult
from harness.session_namer import generate_feedback_filename
from harness.state import init_state, set_phase, read_state

# Task id used by cross_examiner.write_feedback_files to build the feedback
# filename via generate_feedback_filename (contract: P0.3). The env var is set
# by the cross_exam_state fixture so the produced filenames are predictable.
_TASK_ID = "xexam-001"


def _make_failure():
    """Create a sample FuzzFailure for testing."""
    return FuzzFailure(
        input_args=[1, 2],
        input_kwargs={},
        result_a=ExecutionResult(success=True, return_value=3, return_repr="3"),
        result_b=ExecutionResult(success=True, return_value=5, return_repr="5"),
        reason="return_mismatch",
    )


@pytest.fixture
def state_dir(tmp_path):
    """Fresh state directory with initialization."""
    for sub in ("sessions", "tasks", "tasks/processed"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    init_state(tmp_path)
    return tmp_path


@pytest.fixture
def cross_exam_state(state_dir, monkeypatch):
    """State directory set up for cross-examination with feedback files."""
    # write_feedback_files reads JANUSMASK_TASK_ID to build the canonical
    # "{task_id}_round{N}_{agent}_feedback.json" filename (P0.3 contract).
    monkeypatch.setenv("JANUSMASK_TASK_ID", _TASK_ID)
    set_phase(state_dir, phase="cross_examination")
    state = read_state(state_dir)
    state["round"] = 1
    (state_dir / "STATE.json").write_text(json.dumps(state))

    code_a = (
        "def merge_sorted(a: list[int], b: list[int]) -> list[int]:\n"
        "    result = []\n"
        "    i = j = 0\n"
        "    while i < len(a) and j < len(b):\n"
        "        if a[i] <= b[j]:\n"
        "            result.append(a[i])\n"
        "            i += 1\n"
        "        else:\n"
        "            result.append(b[j])\n"
        "            j += 1\n"
        "    result.extend(a[i:])\n"
        "    result.extend(b[j:])\n"
        "    return result\n"
    )
    code_b = (
        "def merge_sorted(a: list[int], b: list[int]) -> list[int]:\n"
        "    merged = sorted(a + b)\n"
        "    return merged\n"
    )

    failures = [_make_failure()]
    cp, gp = prepare_exam_packets(code_a, code_b, "Merge two sorted lists", failures)
    write_feedback_files(state_dir, cp, gp, round_number=1)

    return state_dir, cp, gp


class TestCrossExamFlow:
    """I-13 through I-15: Cross-examiner <-> MCP server integration."""

    def test_i13_feedback_readable_by_mcp(self, cross_exam_state):
        """I-13: Feedback files written by cross_examiner are readable
        by MCP server via get_feedback command."""
        state_dir, cp, gp = cross_exam_state

        # Set up task for the MCP server (needed for get_task gate)
        task = {"task_id": "xexam-001", "constraints": {"deterministic": True}}
        (state_dir / "tasks" / "current_task.json").write_text(json.dumps(task))

        # Claude server reads feedback
        claude_server = JanusMaskServer("claude", state_dir)
        claude_server.cmd_get_task({})  # pass inbox gate
        feedback = claude_server.cmd_get_feedback({})

        assert "error" not in feedback, f"Unexpected error: {feedback}"
        assert feedback["round"] == 1
        assert "code_under_review" in feedback
        assert "review_prompt" in feedback
        assert "previous_fuzz_failures" in feedback

        # Verify the code_under_review is the anonymized code_b (Claude reviews B)
        assert feedback["code_under_review"] == cp.code_under_review

        # Gemini server reads feedback
        gemini_server = JanusMaskServer("gemini", state_dir)
        gemini_server.cmd_get_task({})
        gemini_feedback = gemini_server.cmd_get_feedback({})

        assert "error" not in gemini_feedback, f"Unexpected error: {gemini_feedback}"
        assert gemini_feedback["round"] == 1
        assert gemini_feedback["code_under_review"] == gp.code_under_review

    def test_i14_anonymized_code_parseable_python(self, cross_exam_state):
        """I-14: Anonymized code in feedback is parseable Python."""
        state_dir, cp, gp = cross_exam_state

        # Read the feedback files directly. Filenames follow the P0.3 contract:
        # "{task_id}_round{N}_{agent}_feedback.json" via generate_feedback_filename.
        claude_feedback_path = state_dir / "sessions" / generate_feedback_filename(
            "claude", 1, _TASK_ID
        )
        gemini_feedback_path = state_dir / "sessions" / generate_feedback_filename(
            "gemini", 1, _TASK_ID
        )

        claude_feedback = json.loads(claude_feedback_path.read_text())
        gemini_feedback = json.loads(gemini_feedback_path.read_text())

        # Both anonymized code snippets should be parseable Python
        claude_code = claude_feedback["code_under_review"]
        gemini_code = gemini_feedback["code_under_review"]

        try:
            ast.parse(claude_code)
        except SyntaxError as e:
            pytest.fail(f"Claude's anonymized code is not parseable: {e}\nCode: {claude_code}")

        try:
            ast.parse(gemini_code)
        except SyntaxError as e:
            pytest.fail(f"Gemini's anonymized code is not parseable: {e}\nCode: {gemini_code}")

    def test_i15_feedback_cleared_after_cross_exam(self, cross_exam_state):
        """I-15: Feedback cleared after cross-exam -- get_feedback returns
        'no_feedback' after clear_feedback_files is called."""
        state_dir, cp, gp = cross_exam_state

        # Verify feedback files exist before clearing. Filenames follow the
        # P0.3 contract: "{task_id}_round{N}_{agent}_feedback.json".
        claude_path = state_dir / "sessions" / generate_feedback_filename(
            "claude", 1, _TASK_ID
        )
        gemini_path = state_dir / "sessions" / generate_feedback_filename(
            "gemini", 1, _TASK_ID
        )
        assert claude_path.exists()
        assert gemini_path.exists()

        # Clear feedback files (as orchestrator would after cross-exam)
        clear_feedback_files(state_dir)

        # Verify files are gone
        assert not claude_path.exists()
        assert not gemini_path.exists()

        # Verify MCP server returns no_feedback
        task = {"task_id": "xexam-001", "constraints": {"deterministic": True}}
        (state_dir / "tasks" / "current_task.json").write_text(json.dumps(task))

        server = JanusMaskServer("claude", state_dir)
        server.cmd_get_task({})
        feedback = server.cmd_get_feedback({})

        assert "error" in feedback
        assert feedback["code"] == "no_feedback"
