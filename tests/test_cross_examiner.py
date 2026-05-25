"""Tests for harness/cross_examiner.py -- 33 tests (X-01 through X-33)."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json
import pytest
from pathlib import Path

from harness.cross_examiner import (
    anonymize_code,
    serialize_failure,
    prepare_exam_packets,
    write_feedback_files,
    clear_feedback_files,
    _safe_repr,
    ExamPacket,
    Critique,
    CrossExamResult,
)
from harness.sandbox import ExecutionResult
from harness.diff_fuzzer import FuzzFailure


def _make_failure(
    input_args=None,
    input_kwargs=None,
    result_a=None,
    result_b=None,
    reason="return_mismatch",
):
    if input_args is None:
        input_args = [1, 2]
    if input_kwargs is None:
        input_kwargs = {}
    if result_a is None:
        result_a = ExecutionResult(success=True, return_value=42, return_repr="42")
    if result_b is None:
        result_b = ExecutionResult(success=True, return_value=99, return_repr="99")
    return FuzzFailure(
        input_args=input_args,
        input_kwargs=input_kwargs,
        result_a=result_a,
        result_b=result_b,
        reason=reason,
    )


# ===========================================================================
# Code Anonymization (X-01 to X-11)
# ===========================================================================

class TestAnonymizeCode:

    def test_x01_simple_function_locals_renamed(self):
        code = "def foo(x):\n    a = x + 1\n    b = a + 2\n    return b"
        result = anonymize_code(code)
        assert "var_0" in result
        assert "var_1" in result

    def test_x02_function_parameters_preserved(self):
        code = "def foo(x, y):\n    temp = x + y\n    return temp"
        result = anonymize_code(code)
        assert "x" in result
        assert "y" in result

    def test_x03_function_name_preserved(self):
        code = "def my_function(x):\n    temp = x + 1\n    return temp"
        result = anonymize_code(code)
        assert "my_function" in result

    def test_x04_imported_names_preserved(self):
        code = "import math\ndef foo(x):\n    result = math.sqrt(x)\n    return result"
        result = anonymize_code(code)
        assert "math" in result

    def test_x05_class_names_preserved(self):
        code = "class MyClass:\n    pass\ndef foo(x):\n    temp = x\n    return temp"
        result = anonymize_code(code)
        assert "MyClass" in result

    def test_x06_comments_stripped(self):
        code = "def foo(x):\n    # this is a comment\n    temp = x + 1\n    return temp"
        result = anonymize_code(code)
        assert "# this is a comment" not in result

    def test_x07_docstrings_stripped(self):
        code = 'def foo(x):\n    """This is a docstring."""\n    temp = x + 1\n    return temp'
        result = anonymize_code(code)
        assert "This is a docstring" not in result

    def test_x08_whitespace_normalized(self):
        code = "def foo(x):\n    temp   =   x   +  1\n    return   temp"
        result = anonymize_code(code)
        assert "   =   " not in result

    def test_x09_syntax_error_falls_back_to_comment_stripping(self):
        code = "def foo(x):\n    # strip me\n    return x +++"
        result = anonymize_code(code)
        assert "# strip me" not in result
        assert "return x +++" in result

    def test_x10_multiple_functions_locals_renamed(self):
        code = (
            "def foo(x):\n"
            "    a = x + 1\n"
            "    return a\n"
            "def bar(y):\n"
            "    b = y + 2\n"
            "    return b\n"
        )
        result = anonymize_code(code)
        # Original local names should be gone
        assert "var_" in result
        assert " a " not in result.replace("var_", "XXX")
        assert " b " not in result.replace("var_", "XXX")

    def test_x11_global_variables_preserved(self):
        code = "CONSTANT = 42\ndef foo(x):\n    temp = x + CONSTANT\n    return temp"
        result = anonymize_code(code)
        assert "42" in result


# ===========================================================================
# Failure Serialization (X-12 to X-16)
# ===========================================================================

class TestSerializeFailure:

    def test_x12_successful_result(self):
        success_result = ExecutionResult(success=True, return_value=42, return_repr="42")
        fail_result = ExecutionResult(success=True, return_value=99, return_repr="99")
        failure = FuzzFailure(
            input_args=[1], input_kwargs={},
            result_a=success_result, result_b=fail_result,
            reason="return_mismatch",
        )
        serialized = serialize_failure(failure)
        assert serialized["result_a"]["status"] == "success"
        assert serialized["result_a"]["return_value"] == "42"

    def test_x13_exception_result(self):
        fail_result = ExecutionResult(
            success=False, exception_type="ValueError", exception_message="bad",
        )
        success_result = ExecutionResult(success=True, return_value=42, return_repr="42")
        failure = FuzzFailure(
            input_args=[1], input_kwargs={},
            result_a=fail_result, result_b=success_result,
            reason="exception_vs_return",
        )
        serialized = serialize_failure(failure)
        assert serialized["result_a"]["status"] == "exception"
        assert serialized["result_a"]["exception_type"] == "ValueError"
        assert serialized["result_a"]["exception_message"] == "bad"

    def test_x14_timeout_result(self):
        timeout_result = ExecutionResult(success=False, timed_out=True)
        success_result = ExecutionResult(success=True, return_value=42, return_repr="42")
        failure = FuzzFailure(
            input_args=[1], input_kwargs={},
            result_a=timeout_result, result_b=success_result,
            reason="timeout_a",
        )
        serialized = serialize_failure(failure)
        assert serialized["result_a"]["status"] == "timeout"

    def test_x15_long_repr_truncated_at_500_chars(self):
        long_val = "x" * 600
        result = _safe_repr(long_val)
        assert len(result) == 500
        assert result.endswith("...")

    def test_x16_input_args_serialized(self):
        failure = _make_failure(input_args=[1, "hello", [3, 4]], input_kwargs={"key": "val"})
        serialized = serialize_failure(failure)
        assert "input" in serialized
        assert "args" in serialized["input"]
        assert "kwargs" in serialized["input"]
        assert "1" in serialized["input"]["args"]
        assert "hello" in serialized["input"]["args"]


# ===========================================================================
# Exam Packet Preparation (X-17 to X-24)
# ===========================================================================

class TestPrepareExamPackets:

    @pytest.fixture
    def sample_inputs(self):
        code_a = "def foo(x):\n    a = x + 1\n    return a"
        code_b = "def foo(x):\n    b = x + 2\n    return b"
        task_spec = "Implement a function foo that adds 1 to x"
        failures = [_make_failure() for _ in range(3)]
        return code_a, code_b, task_spec, failures

    def test_x17_returns_2_packets(self, sample_inputs):
        code_a, code_b, task_spec, failures = sample_inputs
        result = prepare_exam_packets(code_a, code_b, task_spec, failures)
        assert len(result) == 2

    def test_x18_claude_receives_anonymized_code_b(self, sample_inputs):
        code_a, code_b, task_spec, failures = sample_inputs
        claude_pkt, gemini_pkt = prepare_exam_packets(code_a, code_b, task_spec, failures)
        anon_b = anonymize_code(code_b)
        assert claude_pkt.code_under_review == anon_b

    def test_x19_gemini_receives_anonymized_code_a(self, sample_inputs):
        code_a, code_b, task_spec, failures = sample_inputs
        claude_pkt, gemini_pkt = prepare_exam_packets(code_a, code_b, task_spec, failures)
        anon_a = anonymize_code(code_a)
        assert gemini_pkt.code_under_review == anon_a

    def test_x20_review_prompt_includes_task_spec(self, sample_inputs):
        code_a, code_b, task_spec, failures = sample_inputs
        claude_pkt, _ = prepare_exam_packets(code_a, code_b, task_spec, failures)
        assert task_spec in claude_pkt.review_prompt

    def test_x21_review_prompt_includes_failures(self, sample_inputs):
        code_a, code_b, task_spec, failures = sample_inputs
        claude_pkt, _ = prepare_exam_packets(code_a, code_b, task_spec, failures)
        assert "Failure" in claude_pkt.review_prompt

    def test_x22_failures_capped_at_10(self):
        code_a = "def foo(x):\n    return x + 1"
        code_b = "def foo(x):\n    return x + 2"
        task_spec = "add 1 to x"
        failures = [_make_failure() for _ in range(15)]
        claude_pkt, _ = prepare_exam_packets(code_a, code_b, task_spec, failures)
        assert len(claude_pkt.fuzz_failures) == 10

    def test_x23_packet_agent_field_correct(self, sample_inputs):
        code_a, code_b, task_spec, failures = sample_inputs
        claude_pkt, gemini_pkt = prepare_exam_packets(code_a, code_b, task_spec, failures)
        assert claude_pkt.agent == "claude"
        assert gemini_pkt.agent == "gemini"

    def test_x24_prompt_mentions_submit_code(self, sample_inputs):
        code_a, code_b, task_spec, failures = sample_inputs
        claude_pkt, _ = prepare_exam_packets(code_a, code_b, task_spec, failures)
        assert "submit_code" in claude_pkt.review_prompt

    def test_anonymization_labels_are_consistent(self, sample_inputs):
        """Verify agent identities are hidden and labels are consistent."""
        code_a, code_b, task_spec, failures = sample_inputs
        claude_pkt, gemini_pkt = prepare_exam_packets(code_a, code_b, task_spec, failures)
        
        for pkt in (claude_pkt, gemini_pkt):
            assert "Result from Code Under Review" in pkt.review_prompt
            assert "Result from Other Code" in pkt.review_prompt
            assert "Result A:" not in pkt.review_prompt
            assert "Result B:" not in pkt.review_prompt


# ===========================================================================
# Feedback File Management (X-25 to X-33)
# ===========================================================================

class TestFeedbackFileManagement:

    @pytest.fixture
    def packets(self):
        claude_pkt = ExamPacket(
            agent="claude",
            code_under_review="def foo(x): return x",
            task_specification="implement foo",
            fuzz_failures=[{"input": {"args": "[1]", "kwargs": "{}"}, "reason": "mismatch"}],
            review_prompt="Review this code...",
        )
        gemini_pkt = ExamPacket(
            agent="gemini",
            code_under_review="def foo(x): return x + 1",
            task_specification="implement foo",
            fuzz_failures=[{"input": {"args": "[1]", "kwargs": "{}"}, "reason": "mismatch"}],
            review_prompt="Review this other code...",
        )
        return claude_pkt, gemini_pkt

    def test_x25_write_creates_claude_feedback(self, tmp_path, packets, monkeypatch):
        monkeypatch.setenv("JANUSMASK_TASK_ID", "X25")
        claude_pkt, gemini_pkt = packets
        write_feedback_files(tmp_path, claude_pkt, gemini_pkt, round_number=1)
        assert (tmp_path / "sessions" / "X25_round1_claude_feedback.json").exists()

    def test_x26_write_creates_gemini_feedback(self, tmp_path, packets, monkeypatch):
        monkeypatch.setenv("JANUSMASK_TASK_ID", "X26")
        claude_pkt, gemini_pkt = packets
        write_feedback_files(tmp_path, claude_pkt, gemini_pkt, round_number=1)
        assert (tmp_path / "sessions" / "X26_round1_gemini_feedback.json").exists()

    def test_x27_feedback_includes_round(self, tmp_path, packets, monkeypatch):
        monkeypatch.setenv("JANUSMASK_TASK_ID", "X27")
        claude_pkt, gemini_pkt = packets
        write_feedback_files(tmp_path, claude_pkt, gemini_pkt, round_number=3)
        with open(tmp_path / "sessions" / "X27_round3_claude_feedback.json") as f:
            data = json.load(f)
        assert data["round"] == 3

    def test_x28_feedback_includes_code_under_review(self, tmp_path, packets, monkeypatch):
        monkeypatch.setenv("JANUSMASK_TASK_ID", "X28")
        claude_pkt, gemini_pkt = packets
        write_feedback_files(tmp_path, claude_pkt, gemini_pkt, round_number=1)
        with open(tmp_path / "sessions" / "X28_round1_claude_feedback.json") as f:
            data = json.load(f)
        assert data["code_under_review"] == claude_pkt.code_under_review

    def test_x29_feedback_includes_review_prompt(self, tmp_path, packets, monkeypatch):
        monkeypatch.setenv("JANUSMASK_TASK_ID", "X29")
        claude_pkt, gemini_pkt = packets
        write_feedback_files(tmp_path, claude_pkt, gemini_pkt, round_number=1)
        with open(tmp_path / "sessions" / "X29_round1_claude_feedback.json") as f:
            data = json.load(f)
        assert data["review_prompt"] == claude_pkt.review_prompt

    def test_x30_feedback_includes_previous_fuzz_failures(self, tmp_path, packets, monkeypatch):
        monkeypatch.setenv("JANUSMASK_TASK_ID", "X30")
        claude_pkt, gemini_pkt = packets
        write_feedback_files(tmp_path, claude_pkt, gemini_pkt, round_number=1)
        with open(tmp_path / "sessions" / "X30_round1_claude_feedback.json") as f:
            data = json.load(f)
        assert "previous_fuzz_failures" in data
        assert len(data["previous_fuzz_failures"]) == 1

    def test_x31_clear_removes_both_files(self, tmp_path, packets, monkeypatch):
        monkeypatch.setenv("JANUSMASK_TASK_ID", "X31")
        claude_pkt, gemini_pkt = packets
        write_feedback_files(tmp_path, claude_pkt, gemini_pkt, round_number=1)
        clear_feedback_files(tmp_path)
        assert not (tmp_path / "sessions" / "X31_round1_claude_feedback.json").exists()
        assert not (tmp_path / "sessions" / "X31_round1_gemini_feedback.json").exists()

    def test_x32_clear_when_files_dont_exist_no_error(self, tmp_path):
        (tmp_path / "sessions").mkdir(parents=True, exist_ok=True)
        clear_feedback_files(tmp_path)

    def test_x33_sessions_dir_created_if_missing(self, tmp_path, packets, monkeypatch):
        monkeypatch.setenv("JANUSMASK_TASK_ID", "X33")
        claude_pkt, gemini_pkt = packets
        state_dir = tmp_path / "brand_new_state"
        write_feedback_files(state_dir, claude_pkt, gemini_pkt, round_number=1)
        assert (state_dir / "sessions").is_dir()
        assert (state_dir / "sessions" / "X33_round1_claude_feedback.json").exists()


# ===========================================================================
# Additional Edge Cases (X-34 to X-37)
# ===========================================================================

class TestAnonymizeCodeEdgeCases:

    def test_x34_from_import_names_preserved(self):
        """X-34: from-import names are preserved during anonymization."""
        code = "from os.path import join\ndef foo(x):\n    temp = join(x, 'a')\n    return temp"
        result = anonymize_code(code)
        assert "join" in result

    def test_x35_vararg_kwarg_preserved(self):
        """X-35: *args and **kwargs parameter names preserved."""
        code = "def foo(*args, **kwargs):\n    temp = list(args)\n    return temp"
        result = anonymize_code(code)
        assert "args" in result
        assert "kwargs" in result

    def test_x36_anonymization_idempotent(self):
        """X-36: Anonymizing already-anonymized code produces same result."""
        code = "def foo(x):\n    a = x + 1\n    b = a + 2\n    return b"
        first_pass = anonymize_code(code)
        second_pass = anonymize_code(first_pass)
        assert first_pass == second_pass


class TestFeedbackFileEdgeCases:

    def test_x37_new_round_preserves_old_feedback(self, tmp_path, monkeypatch):
        """X-37 (inverted per P0.3): round N+1 must NOT overwrite round N feedback."""
        monkeypatch.setenv("JANUSMASK_TASK_ID", "X37")
        claude_pkt = ExamPacket(
            agent="claude",
            code_under_review="def foo(x): return x",
            task_specification="implement foo",
            fuzz_failures=[{"reason": "round1"}],
            review_prompt="Review round 1",
        )
        gemini_pkt = ExamPacket(
            agent="gemini",
            code_under_review="def foo(x): return x + 1",
            task_specification="implement foo",
            fuzz_failures=[{"reason": "round1"}],
            review_prompt="Review round 1",
        )
        write_feedback_files(tmp_path, claude_pkt, gemini_pkt, round_number=1)

        # Write round 2
        claude_pkt2 = ExamPacket(
            agent="claude",
            code_under_review="def foo(x): return x * 2",
            task_specification="implement foo v2",
            fuzz_failures=[{"reason": "round2"}],
            review_prompt="Review round 2",
        )
        gemini_pkt2 = ExamPacket(
            agent="gemini",
            code_under_review="def foo(x): return x * 3",
            task_specification="implement foo v2",
            fuzz_failures=[{"reason": "round2"}],
            review_prompt="Review round 2",
        )
        write_feedback_files(tmp_path, claude_pkt2, gemini_pkt2, round_number=2)

        # Round 1 content still present
        r1 = tmp_path / "sessions" / "X37_round1_claude_feedback.json"
        r2 = tmp_path / "sessions" / "X37_round2_claude_feedback.json"
        assert r1.exists()
        assert r2.exists()
        with open(r1) as f:
            d1 = json.load(f)
        with open(r2) as f:
            d2 = json.load(f)
        assert d1["round"] == 1
        assert d1["review_prompt"] == "Review round 1"
        assert d2["round"] == 2
        assert d2["review_prompt"] == "Review round 2"
