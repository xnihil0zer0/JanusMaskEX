"""Adversarial regression tests for harness/diff_fuzzer.py meta-task-type bypass.

Regression origin (B3 F2 followup, 2026-04-20):
    stab_005 drain logged
        "Fuzzing error: Failed to build input strategy from code_a:
         Function 'should_bypass_fuzzer' not found in code"
    on the ORCHESTRATOR-002-planner-tooling-bypass task.  The task itself
    edits the very function the fuzzer was attempting to locate, so
    neither Claude's nor Gemini's submission carried a fuzzable
    `should_bypass_fuzzer` definition.

    `fuzz_from_task` now treats that combination (permissive
    `meta_task_type` + target absent from both sides) as a clean skip
    rather than an error, unblocking the task.  Non-bypass meta types
    still loudly error on missing functions so real content bugs are
    NOT swallowed.

Filed under tests/adversarial/ to match the META-phase allow-list and
the existing convention for B3 regression repairs.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# tests/adversarial/ is two levels under project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from harness.diff_fuzzer import (
    FUZZ_BYPASS_META_TYPES,
    FuzzResult,
    _code_defines_function,
    _extract_meta_task_type,
    _split_type_args,
    fuzz_from_task,
)


# ── _code_defines_function ─────────────────────────────────────────────


class TestCodeDefinesFunction:
    def test_sync_def_detected(self):
        assert _code_defines_function("def foo(): pass\n", "foo") is True

    def test_async_def_detected(self):
        assert _code_defines_function("async def foo(): pass\n", "foo") is True

    def test_missing_returns_false(self):
        assert _code_defines_function("def bar(): pass\n", "foo") is False

    def test_syntax_error_returns_false(self):
        assert _code_defines_function("def foo(: pass\n", "foo") is False

    def test_nested_function_detected(self):
        code = "def outer():\n    def foo():\n        pass\n"
        # ast.walk recurses, so nested definitions match.
        assert _code_defines_function(code, "foo") is True

    def test_empty_code_returns_false(self):
        assert _code_defines_function("", "foo") is False


# ── _extract_meta_task_type ────────────────────────────────────────────


class TestExtractMetaTaskType:
    def test_task_level_wins(self):
        task = {
            "meta_task_type": "planner_tooling",
            "constraints": {"meta_task_type": "orchestration"},
        }
        assert _extract_meta_task_type(task) == "planner_tooling"

    def test_constraints_level_fallback(self):
        task = {"constraints": {"meta_task_type": "planner_tooling"}}
        assert _extract_meta_task_type(task) == "planner_tooling"

    def test_none_when_absent(self):
        assert _extract_meta_task_type({}) is None

    def test_empty_string_treated_as_absent(self):
        assert _extract_meta_task_type({"meta_task_type": ""}) is None

    def test_non_dict_constraints_tolerated(self):
        """Malformed tasks (constraints is a list) must not raise."""
        task = {"meta_task_type": None, "constraints": ["not a dict"]}
        assert _extract_meta_task_type(task) is None

    def test_task_level_none_falls_back_to_constraints(self):
        task = {"meta_task_type": None, "constraints": {"meta_task_type": "sandbox_infra"}}
        assert _extract_meta_task_type(task) == "sandbox_infra"


# ── _split_type_args (helper re-introduced alongside bypass fix) ────────


class TestSplitTypeArgs:
    def test_simple(self):
        assert _split_type_args("int, str") == ["int", "str"]

    def test_nested(self):
        assert _split_type_args("dict[str, int], list[int]") == ["dict[str, int]", "list[int]"]

    def test_single(self):
        assert _split_type_args("int") == ["int"]

    def test_empty_string(self):
        assert _split_type_args("") == []

    def test_deeply_nested_single_arg(self):
        assert _split_type_args("dict[str, list[tuple[int, ...]]]") == [
            "dict[str, list[tuple[int, ...]]]"
        ]


# ── fuzz_from_task bypass / fallback semantics ─────────────────────────


@pytest.fixture
def fast_config():
    return {
        "fuzzing": {
            "function_level_inputs": 10,
            "float_tolerance": 1e-9,
            "seed": 42,
            "timeout_per_input_ms": 1000,
        },
        "sandbox": {
            "memory_limit_mb": 256,
            "cpu_time_limit_seconds": 5,
            "filesystem_root": "/tmp/janusmask_test_sandbox_bypass",
        },
        "batch_execution": {"enabled": False},
    }


class TestFuzzBypassSet:
    def test_bypass_set_includes_planner_tooling(self):
        assert "planner_tooling" in FUZZ_BYPASS_META_TYPES

    def test_bypass_set_includes_orchestration(self):
        assert "orchestration" in FUZZ_BYPASS_META_TYPES

    def test_bypass_set_includes_harness_plumbing(self):
        assert "harness_plumbing" in FUZZ_BYPASS_META_TYPES

    def test_bypass_set_includes_sandbox_infra(self):
        assert "sandbox_infra" in FUZZ_BYPASS_META_TYPES


class TestFuzzFromTaskBypass:
    """Meta-task-type aware skip / fallback path in fuzz_from_task."""

    def test_planner_tooling_both_sides_missing_function_skips(self, fast_config):
        """Reproduces stab_005: bypass-type task + absent target -> skip, not error."""
        code_a = "def helper_a(x: int) -> int:\n    return x + 1\n"
        code_b = "def helper_b(x: int) -> int:\n    return x + 1\n"
        task = {
            "task_id": "ORCHESTRATOR-002-planner-tooling-bypass",
            "meta_task_type": "planner_tooling",
            "constraints": {
                "function_signature": "def should_bypass_fuzzer(task: Task) -> bool",
            },
        }
        result = fuzz_from_task(code_a, code_b, task, fast_config, session_id="bypass_both_missing")
        assert isinstance(result, FuzzResult)
        assert result.error is None, f"expected no error, got {result.error!r}"
        assert result.equivalent is True
        assert result.skipped_reason is not None
        assert "should_bypass_fuzzer" in result.skipped_reason
        assert "planner_tooling" in result.skipped_reason

    def test_planner_tooling_via_constraints_only(self, fast_config):
        """meta_task_type nested only under constraints still triggers bypass."""
        code_a = "def helper_a(): pass\n"
        code_b = "def helper_b(): pass\n"
        task = {
            "task_id": "LOGACT-002",
            "constraints": {
                "function_signature": "def should_bypass_fuzzer(task: Task) -> bool",
                "meta_task_type": "planner_tooling",
            },
        }
        result = fuzz_from_task(code_a, code_b, task, fast_config, session_id="bypass_constraints_only")
        assert result.error is None
        assert result.equivalent is True
        assert result.skipped_reason is not None

    def test_content_task_both_missing_still_errors(self, fast_config):
        """Plain content tasks (no bypass meta_type) MUST still loudly error."""
        code_a = "def helper_a(): pass\n"
        code_b = "def helper_b(): pass\n"
        task = {
            "task_id": "CONTENT-001",
            "constraints": {
                "function_signature": "def merge_sorted(a: list[int], b: list[int]) -> list[int]",
            },
        }
        result = fuzz_from_task(code_a, code_b, task, fast_config, session_id="content_both_missing")
        assert result.equivalent is False
        assert result.error is not None
        assert "merge_sorted" in result.error
        assert result.skipped_reason is None

    def test_one_sided_planner_tooling_skips(self, fast_config):
        """Only one side has the function + permissive meta_type -> skip."""
        code_a = "def should_bypass_fuzzer(task): return True\n"
        code_b = "def unrelated(): pass\n"
        task = {
            "task_id": "ORCHESTRATOR-002-planner-tooling-bypass",
            "meta_task_type": "planner_tooling",
            "constraints": {
                "function_signature": "def should_bypass_fuzzer(task: Task) -> bool",
            },
        }
        result = fuzz_from_task(code_a, code_b, task, fast_config, session_id="bypass_one_sided")
        assert result.error is None
        assert result.equivalent is True
        assert result.skipped_reason is not None
        assert "one side only" in result.skipped_reason

    def test_one_sided_content_task_errors(self, fast_config):
        """Non-bypass meta_type with one-sided function: structured error, not crash."""
        code_a = "def merge_sorted(a, b): return a + b\n"
        code_b = "def other(): pass\n"
        task = {
            "task_id": "CONTENT-002",
            "constraints": {
                "function_signature": "def merge_sorted(a: list[int], b: list[int]) -> list[int]",
            },
        }
        result = fuzz_from_task(code_a, code_b, task, fast_config, session_id="content_one_sided")
        assert result.equivalent is False
        assert result.error is not None
        assert "merge_sorted" in result.error
        assert "code_b" in result.error  # identifies which side is missing
        assert result.skipped_reason is None

    def test_no_primary_function_planner_tooling_skips(self, fast_config):
        """No discoverable function at all + planner_tooling -> skip, not error."""
        code_a = "x = 42\ny = x + 1\n"
        code_b = "z = 99\n"
        task = {
            "task_id": "ORCHESTRATOR-002-planner-tooling-bypass",
            "meta_task_type": "planner_tooling",
            "constraints": {},  # no function_signature to extract
        }
        result = fuzz_from_task(code_a, code_b, task, fast_config, session_id="nofunc_bypass")
        assert result.error is None
        assert result.equivalent is True
        assert result.skipped_reason is not None

    def test_regular_content_task_still_fuzzes_normally(self, fast_config):
        """Regression: normal content task with both sides defining the function
        is unaffected by the bypass logic and still runs the real fuzzer."""
        code_a = "def add(a: int, b: int) -> int:\n    return a + b\n"
        code_b = "def add(a: int, b: int) -> int:\n    return a + b\n"
        task = {
            "task_id": "CONTENT-NORMAL-001",
            "constraints": {
                "function_signature": "def add(a: int, b: int) -> int",
            },
        }
        result = fuzz_from_task(code_a, code_b, task, fast_config, session_id="normal_content")
        assert result.error is None
        assert result.skipped_reason is None  # fuzzing actually happened
        assert result.equivalent is True
        assert result.total_inputs > 0  # evidence we went through the real fuzzer

    def test_unknown_meta_task_type_does_not_bypass(self, fast_config):
        """meta_task_type not in FUZZ_BYPASS_META_TYPES -> still errors."""
        code_a = "def helper_a(): pass\n"
        code_b = "def helper_b(): pass\n"
        task = {
            "task_id": "SOMETHING-UNKNOWN",
            "meta_task_type": "brand_new_type",
            "constraints": {
                "function_signature": "def should_bypass_fuzzer(task: Task) -> bool",
            },
        }
        result = fuzz_from_task(code_a, code_b, task, fast_config, session_id="unknown_meta")
        assert result.equivalent is False
        assert result.error is not None
        assert result.skipped_reason is None

    def test_orchestration_meta_type_also_bypasses(self, fast_config):
        """Sanity: orchestration type bypasses just like planner_tooling."""
        code_a = "def helper_a(): pass\n"
        code_b = "def helper_b(): pass\n"
        task = {
            "task_id": "ORCH-XYZ",
            "meta_task_type": "orchestration",
            "constraints": {
                "function_signature": "def some_orchestration_fn(x: int) -> int",
            },
        }
        result = fuzz_from_task(code_a, code_b, task, fast_config, session_id="orch_bypass")
        assert result.error is None
        assert result.equivalent is True
        assert result.skipped_reason is not None
