"""Tests for harness/diff_fuzzer.py — differential fuzzing engine."""

import sys
from pathlib import Path

import pytest
from hypothesis import given, settings as h_settings
from hypothesis import strategies as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.diff_fuzzer import (
    FUZZ_BYPASS_META_TYPES,
    FuzzFailure,
    FuzzResult,
    _code_defines_function,
    _deep_compare,
    _extract_meta_task_type,
    _generate_inputs,
    _split_type_args,
    _strategy_for_annotation,
    build_input_strategy,
    differential_fuzz,
    extract_function_signature,
    fuzz_from_task,
    outputs_match,
)
from harness.sandbox import ExecutionResult


# ── Type Strategy Mapping ───────────────────────────────────────────────

class TestStrategyMapping:
    def test_int(self):
        s = _strategy_for_annotation("int")
        val = s.example()
        assert isinstance(val, int)

    def test_float(self):
        s = _strategy_for_annotation("float")
        val = s.example()
        assert isinstance(val, float)

    def test_str(self):
        s = _strategy_for_annotation("str")
        val = s.example()
        assert isinstance(val, str)

    def test_bool(self):
        s = _strategy_for_annotation("bool")
        val = s.example()
        assert isinstance(val, bool)

    def test_bytes(self):
        s = _strategy_for_annotation("bytes")
        val = s.example()
        assert isinstance(val, bytes)

    def test_none(self):
        s = _strategy_for_annotation("None")
        val = s.example()
        assert val is None

    def test_nonetype(self):
        s = _strategy_for_annotation("NoneType")
        val = s.example()
        assert val is None

    def test_list_int(self):
        s = _strategy_for_annotation("list[int]")
        val = s.example()
        assert isinstance(val, list)

    def test_tuple_fixed(self):
        s = _strategy_for_annotation("tuple[int, str]")
        val = s.example()
        assert isinstance(val, tuple)
        assert len(val) == 2

    def test_tuple_variable(self):
        s = _strategy_for_annotation("tuple[int, ...]")
        val = s.example()
        assert isinstance(val, tuple)

    def test_set_int(self):
        s = _strategy_for_annotation("set[int]")
        val = s.example()
        assert isinstance(val, set)

    def test_dict_str_int(self):
        s = _strategy_for_annotation("dict[str, int]")
        val = s.example()
        assert isinstance(val, dict)

    def test_optional_int(self):
        s = _strategy_for_annotation("Optional[int]")
        # Just verify it produces values without error
        for _ in range(10):
            s.example()

    def test_union_syntax(self):
        s = _strategy_for_annotation("int | None")
        for _ in range(10):
            s.example()

    def test_unknown_falls_back(self):
        s = _strategy_for_annotation("SomeUnknownType")
        val = s.example()
        assert isinstance(val, int)


# ── Type Arg Splitting ──────────────────────────────────────────────────

class TestSplitTypeArgs:
    def test_simple(self):
        assert _split_type_args("int, str") == ["int", "str"]

    def test_nested(self):
        assert _split_type_args("dict[str, int], list[int]") == ["dict[str, int]", "list[int]"]

    def test_single(self):
        assert _split_type_args("int") == ["int"]

    def test_empty_string(self):
        result = _split_type_args("")
        # Empty string may return [] or [""] depending on implementation
        assert result == [] or result == [""]


# ── Function Signature Extraction ───────────────────────────────────────

class TestSignatureExtraction:
    def test_annotated(self):
        code = "def add(a: int, b: int) -> int:\n    return a + b\n"
        sig = extract_function_signature(code, "add")
        assert sig == {"a": "int", "b": "int"}

    def test_unannotated_defaults_to_int(self):
        code = "def f(x):\n    return x\n"
        sig = extract_function_signature(code, "f")
        assert sig == {"x": "int"}

    def test_complex_annotations(self):
        code = "def f(a: list[int], b: str) -> bool:\n    pass\n"
        sig = extract_function_signature(code, "f")
        assert sig == {"a": "list[int]", "b": "str"}

    def test_function_not_found(self):
        code = "def foo(): pass\n"
        with pytest.raises(ValueError):
            extract_function_signature(code, "bar")

    def test_multiple_functions_correct_one(self):
        code = "def foo(x: str): pass\ndef bar(y: float): pass\n"
        sig = extract_function_signature(code, "bar")
        assert sig == {"y": "float"}


# ── Input Strategy Building ─────────────────────────────────────────────

class TestBuildStrategy:
    def test_generates_correct_arity(self):
        code = "def add(a: int, b: int) -> int:\n    return a + b\n"
        strategy = build_input_strategy(code, "add")
        args, kwargs = strategy.example()
        assert len(args) == 2
        assert kwargs == {}

    def test_no_arg_function(self):
        code = "def constant() -> int:\n    return 42\n"
        strategy = build_input_strategy(code, "constant")
        args, kwargs = strategy.example()
        assert len(args) == 0


# ── Output Comparison ───────────────────────────────────────────────────

class TestOutputsMatch:
    def _result(self, *, success=True, return_value=None, return_repr="",
                exception_type=None, exception_message=None, timed_out=False):
        return ExecutionResult(
            success=success, return_value=return_value, return_repr=return_repr,
            exception_type=exception_type, exception_message=exception_message,
            timed_out=timed_out,
        )

    def test_both_succeed_same_return(self):
        a = self._result(return_value=42, return_repr="42")
        b = self._result(return_value=42, return_repr="42")
        match, reason = outputs_match(a, b)
        assert match is True

    def test_both_succeed_different_return(self):
        a = self._result(return_value=42, return_repr="42")
        b = self._result(return_value=99, return_repr="99")
        match, reason = outputs_match(a, b)
        assert match is False

    def test_both_timed_out(self):
        a = self._result(success=False, timed_out=True)
        b = self._result(success=False, timed_out=True)
        match, reason = outputs_match(a, b)
        assert match is True

    def test_one_timed_out(self):
        a = self._result(success=False, timed_out=True)
        b = self._result(return_value=1, return_repr="1")
        match, reason = outputs_match(a, b)
        assert match is False

    def test_same_exception(self):
        a = self._result(success=False, exception_type="ValueError", exception_message="x")
        b = self._result(success=False, exception_type="ValueError", exception_message="y")
        match, reason = outputs_match(a, b)
        assert match is True

    def test_different_exceptions(self):
        a = self._result(success=False, exception_type="ValueError")
        b = self._result(success=False, exception_type="TypeError")
        match, reason = outputs_match(a, b)
        assert match is False

    def test_exception_vs_return(self):
        a = self._result(success=False, exception_type="ValueError")
        b = self._result(return_value=42, return_repr="42")
        match, reason = outputs_match(a, b)
        assert match is False

    def test_floats_within_tolerance(self):
        a = self._result(return_value=1.0, return_repr="1.0")
        b = self._result(return_value=1.0 + 1e-12, return_repr=repr(1.0 + 1e-12))
        match, reason = outputs_match(a, b)
        assert match is True

    def test_floats_outside_tolerance(self):
        a = self._result(return_value=1.0, return_repr="1.0")
        b = self._result(return_value=2.0, return_repr="2.0")
        match, reason = outputs_match(a, b)
        assert match is False

    def test_both_nan(self):
        import math
        a = self._result(return_value=float("nan"), return_repr="nan")
        b = self._result(return_value=float("nan"), return_repr="nan")
        match, reason = outputs_match(a, b)
        assert match is True

    def test_lists_same(self):
        a = self._result(return_value=[1, 2, 3], return_repr="[1, 2, 3]")
        b = self._result(return_value=[1, 2, 3], return_repr="[1, 2, 3]")
        match, reason = outputs_match(a, b)
        assert match is True

    def test_lists_different_length(self):
        a = self._result(return_value=[1, 2], return_repr="[1, 2]")
        b = self._result(return_value=[1, 2, 3], return_repr="[1, 2, 3]")
        match, reason = outputs_match(a, b)
        assert match is False

    def test_dicts_same(self):
        a = self._result(return_value={"a": 1}, return_repr="{'a': 1}")
        b = self._result(return_value={"a": 1}, return_repr="{'a': 1}")
        match, reason = outputs_match(a, b)
        assert match is True

    def test_dicts_different_keys(self):
        a = self._result(return_value={"a": 1}, return_repr="{'a': 1}")
        b = self._result(return_value={"b": 1}, return_repr="{'b': 1}")
        match, reason = outputs_match(a, b)
        assert match is False

    def test_both_none(self):
        a = self._result(return_value=None, return_repr="None")
        b = self._result(return_value=None, return_repr="None")
        match, reason = outputs_match(a, b)
        assert match is True

    def test_type_mismatch(self):
        a = self._result(return_value=1, return_repr="1")
        b = self._result(return_value=1.0, return_repr="1.0")
        match, reason = outputs_match(a, b)
        assert match is False


# ── Input Generation ────────────────────────────────────────────────────

class TestInputGeneration:
    def test_generates_inputs(self):
        # _generate_inputs expects a strategy that produces (list, dict) tuples
        code = "def add(a: int, b: int) -> int:\n    return a + b\n"
        strategy = build_input_strategy(code, "add")
        inputs = _generate_inputs(strategy, 20, seed=42)
        assert len(inputs) > 0
        # Each input should be a (args_list, kwargs_dict) tuple
        for args, kwargs in inputs:
            assert isinstance(args, list)
            assert isinstance(kwargs, dict)

    def test_deterministic(self):
        code = "def add(a: int, b: int) -> int:\n    return a + b\n"
        strategy = build_input_strategy(code, "add")
        a = _generate_inputs(strategy, 20, seed=42)
        b = _generate_inputs(strategy, 20, seed=42)
        assert a == b


# ── Differential Fuzzing E2E ────────────────────────────────────────────

class TestDifferentialFuzz:
    @pytest.fixture
    def fast_config(self):
        return {
            "fuzzing": {
                "function_level_inputs": 50,
                "float_tolerance": 1e-9,
                "seed": 42,
                "timeout_per_input_ms": 3000,
            },
            "sandbox": {
                "memory_limit_mb": 256,
                "cpu_time_limit_seconds": 5,
                "filesystem_root": "/tmp/janusmask_test_sandbox",
            },
        }

    def test_identical_implementations_equivalent(self, fast_config):
        code = "def add(a: int, b: int) -> int:\n    return a + b\n"
        result = differential_fuzz(code, code, "add", fast_config, session_id="eq_test")
        assert result.equivalent is True
        assert len(result.failures) == 0

    def test_different_implementations_divergent(self, fast_config):
        code_a = "def abs_val(x: int) -> int:\n    return x if x >= 0 else -x\n"
        code_b = "def abs_val(x: int) -> int:\n    return x\n"
        result = differential_fuzz(code_a, code_b, "abs_val", fast_config, session_id="div_test")
        assert result.equivalent is False
        assert len(result.failures) > 0

    def test_syntax_error_returns_error(self, fast_config):
        code_a = "def foo(: pass\n"
        code_b = "def foo(): pass\n"
        result = differential_fuzz(code_a, code_b, "foo", fast_config, session_id="syn_test")
        assert result.equivalent is False
        assert result.error is not None

    def test_failures_capped(self, fast_config):
        code_a = "def ident(x: int) -> int:\n    return x\n"
        code_b = "def ident(x: int) -> int:\n    return x + 1\n"
        result = differential_fuzz(code_a, code_b, "ident", fast_config, session_id="cap_test")
        assert len(result.failures) <= 20

    def test_fuzz_from_task(self, fast_config):
        code = "def add(a: int, b: int) -> int:\n    return a + b\n"
        task = {
            "task_id": "t1",
            "constraints": {
                "function_signature": "def add(a: int, b: int) -> int",
            },
        }
        result = fuzz_from_task(code, code, task, fast_config, session_id="task_test")
        assert result.equivalent is True


# ── Missing Strategy Mapping Tests (F-09, F-16, F-17) ─────────────────

class TestStrategyMappingExtended:
    def test_f09_list_str(self):
        """F-09: list[str] strategy generates list of strings."""
        s = _strategy_for_annotation("list[str]")
        val = s.example()
        assert isinstance(val, list)
        for item in val:
            assert isinstance(item, str)

    def test_f16_nested_list_list_int(self):
        """F-16: list[list[int]] nested strategy."""
        s = _strategy_for_annotation("list[list[int]]")
        val = s.example()
        assert isinstance(val, list)
        for inner in val:
            assert isinstance(inner, list)
            for item in inner:
                assert isinstance(item, int)

    def test_f17_dict_str_list_int(self):
        """F-17: dict[str, list[int]] complex nested strategy."""
        s = _strategy_for_annotation("dict[str, list[int]]")
        val = s.example()
        assert isinstance(val, dict)
        for k, v in val.items():
            assert isinstance(k, str)
            assert isinstance(v, list)
            for item in v:
                assert isinstance(item, int)


# ── Missing Type Arg Splitting (F-23) ──────────────────────────────────

class TestSplitTypeArgsExtended:
    def test_f23_deeply_nested(self):
        """F-23: Deeply nested type arg splitting."""
        result = _split_type_args("dict[str, list[tuple[int, ...]]]")
        # Should be a single element since the entire thing is one type arg
        assert result == ["dict[str, list[tuple[int, ...]]]"]

    def test_f23_deeply_nested_two_args(self):
        """F-23 variant: two deeply nested args split correctly."""
        result = _split_type_args("dict[str, list[int]], tuple[int, ...]")
        assert result == ["dict[str, list[int]]", "tuple[int, ...]"]


# ── Missing Signature Extraction (F-29) ────────────────────────────────

class TestSignatureExtractionExtended:
    def test_f29_async_function(self):
        """F-29: Async function signature extraction."""
        code = "async def f(x: int) -> str:\n    return str(x)\n"
        sig = extract_function_signature(code, "f")
        assert sig == {"x": "int"}


# ── Missing Build Strategy (F-32) ─────────────────────────────────────

class TestBuildStrategyExtended:
    def test_f32_kwargs_always_empty(self):
        """F-32: kwargs is always empty dict for all draws."""
        code = "def add(a: int, b: int) -> int:\n    return a + b\n"
        strategy = build_input_strategy(code, "add")
        inputs = _generate_inputs(strategy, 50, seed=42)
        for args, kwargs in inputs:
            assert kwargs == {}, f"Expected empty kwargs, got {kwargs}"


# ── Missing Output Comparison (F-48 through F-56) ─────────────────────

class TestOutputsMatchExtended:
    def _result(self, *, success=True, return_value=None, return_repr="",
                exception_type=None, exception_message=None, timed_out=False):
        return ExecutionResult(
            success=success, return_value=return_value, return_repr=return_repr,
            exception_type=exception_type, exception_message=exception_message,
            timed_out=timed_out,
        )

    def test_f48_sets_same_elements(self):
        """F-48: Sets with same elements match."""
        a = self._result(return_value={1, 2, 3}, return_repr="{1, 2, 3}")
        b = self._result(return_value={1, 2, 3}, return_repr="{1, 2, 3}")
        match, reason = outputs_match(a, b)
        assert match is True
        # outputs_match wraps _deep_compare's "set_match" as "values_match"
        assert reason == "values_match"

    def test_f49_sets_different_elements(self):
        """F-49: Sets with different elements mismatch."""
        a = self._result(return_value={1, 2, 3}, return_repr="{1, 2, 3}")
        b = self._result(return_value={1, 2, 4}, return_repr="{1, 2, 4}")
        match, reason = outputs_match(a, b)
        assert match is False
        assert "set_mismatch" in reason

    def test_f50_type_mismatch_int_vs_float(self):
        """F-50: Type mismatch int vs float."""
        a = self._result(return_value=1, return_repr="1")
        b = self._result(return_value=1.0, return_repr="1.0")
        match, reason = outputs_match(a, b)
        assert match is False
        assert "type_mismatch" in reason

    def test_f51_both_return_none(self):
        """F-51: Both return None."""
        a = self._result(return_value=None, return_repr="None")
        b = self._result(return_value=None, return_repr="None")
        match, reason = outputs_match(a, b)
        assert match is True
        # outputs_match wraps _deep_compare's "both_none" as "values_match"
        assert reason == "values_match"

    def test_f52_non_serializable_same_repr(self):
        """F-52: Non-serializable but same repr -> repr_match.

        When _deep_compare fails (e.g., different non-None values) but repr
        strings match, outputs_match falls back to repr comparison.
        """
        # Use distinct return_value objects that fail _deep_compare but have
        # identical repr strings (simulates non-JSON-serializable objects).
        a = self._result(return_value={"x": 1}, return_repr="<CustomObj(1)>")
        b = self._result(return_value={"y": 2}, return_repr="<CustomObj(1)>")
        match, reason = outputs_match(a, b)
        assert match is True
        assert reason == "repr_match"

    def test_f53_deeply_nested_structure(self):
        """F-53: Deeply nested structure (5+ levels) comparison."""
        deep = {"a": [{"b": [{"c": [{"d": [1, 2, 3]}]}]}]}
        a = self._result(return_value=deep, return_repr=repr(deep))
        b = self._result(return_value=deep, return_repr=repr(deep))
        match, reason = outputs_match(a, b)
        assert match is True

    def test_f53_deeply_nested_mismatch(self):
        """F-53 variant: Deeply nested mismatch detected."""
        deep_a = {"a": [{"b": [{"c": [{"d": [1, 2, 3]}]}]}]}
        deep_b = {"a": [{"b": [{"c": [{"d": [1, 2, 999]}]}]}]}
        a = self._result(return_value=deep_a, return_repr=repr(deep_a))
        b = self._result(return_value=deep_b, return_repr=repr(deep_b))
        match, reason = outputs_match(a, b)
        assert match is False

    def test_f54_empty_collections_match(self):
        """F-54: Empty collections match."""
        for val, repr_val in [([], "[]"), ({}, "{}"), (set(), "set()")]:
            a = self._result(return_value=val, return_repr=repr_val)
            b = self._result(return_value=val, return_repr=repr_val)
            match, reason = outputs_match(a, b)
            assert match is True, f"Expected match for empty {type(val).__name__}"

    def test_f55_mixed_types_in_list(self):
        """F-55: Mixed types in list element-wise comparison."""
        val = [1, "a", None]
        a = self._result(return_value=val, return_repr=repr(val))
        b = self._result(return_value=val, return_repr=repr(val))
        match, reason = outputs_match(a, b)
        assert match is True

    def test_f55_mixed_types_mismatch(self):
        """F-55 variant: Mixed types mismatch detected."""
        a = self._result(return_value=[1, "a", None], return_repr="[1, 'a', None]")
        b = self._result(return_value=[1, "b", None], return_repr="[1, 'b', None]")
        match, reason = outputs_match(a, b)
        assert match is False

    def test_f56_bool_vs_int_type_mismatch(self):
        """F-56: Boolean vs int (True vs 1) -> type mismatch."""
        a = self._result(return_value=True, return_repr="True")
        b = self._result(return_value=1, return_repr="1")
        match, reason = outputs_match(a, b)
        assert match is False
        assert "type_mismatch" in reason


# ── Missing Input Generation (F-59, F-60, F-61) ───────────────────────

class TestInputGenerationExtended:
    def test_f59_different_seeds_different_inputs(self):
        """F-59: Different seeds produce different inputs."""
        code = "def add(a: int, b: int) -> int:\n    return a + b\n"
        strategy = build_input_strategy(code, "add")
        inputs_a = _generate_inputs(strategy, 50, seed=42)
        inputs_b = _generate_inputs(strategy, 50, seed=123)
        # They may not be completely different but should not be identical
        assert inputs_a != inputs_b

    def test_f60_large_count_completes(self):
        """F-60: Large count (2000) completes without timeout."""
        code = "def f(x: int) -> int:\n    return x\n"
        strategy = build_input_strategy(code, "f")
        inputs = _generate_inputs(strategy, 2000, seed=42)
        assert len(inputs) > 0

    def test_f61_deduplication_via_seen_set(self):
        """F-61: Deduplication via seen set — no exact duplicate inputs."""
        code = "def f(x: bool) -> bool:\n    return x\n"
        strategy = build_input_strategy(code, "f")
        inputs = _generate_inputs(strategy, 100, seed=42)
        reprs = [repr(inp) for inp in inputs]
        assert len(reprs) == len(set(reprs)), "Found duplicate inputs"


# ── Missing E2E Tests (F-64, F-65, F-68, F-69, F-72) ──────────────────

class TestDifferentialFuzzExtended:
    @pytest.fixture
    def fast_config(self):
        return {
            "fuzzing": {
                "function_level_inputs": 50,
                "float_tolerance": 1e-9,
                "seed": 42,
                "timeout_per_input_ms": 3000,
            },
            "sandbox": {
                "memory_limit_mb": 256,
                "cpu_time_limit_seconds": 5,
                "filesystem_root": "/tmp/janusmask_test_sandbox",
            },
        }

    def test_f64_case_sensitive_vs_insensitive(self, fast_config):
        """F-64: Case-sensitive vs case-insensitive palindrome check divergence.

        Uses direct outputs_match comparison with a known divergent input
        ("AbBa") since random generation rarely produces case-insensitive-only
        palindromes. Also exercises sandbox-level comparison to confirm the
        implementations disagree.
        """
        from harness.sandbox import Sandbox, SandboxConfig
        code_a = "def is_palindrome(s: str) -> bool:\n    return s == s[::-1]\n"
        code_b = (
            "def is_palindrome(s: str) -> bool:\n"
            "    s = s.lower()\n"
            "    return s == s[::-1]\n"
        )
        sandbox = Sandbox(SandboxConfig(
            filesystem_root="/tmp/janusmask_test_case64",
            cpu_time_limit_seconds=5,
            timeout_per_input_ms=3000,
        ))
        try:
            res_a = sandbox.execute(code_a, "is_palindrome", args=["AbBa"])
            res_b = sandbox.execute(code_b, "is_palindrome", args=["AbBa"])
            match, reason = outputs_match(res_a, res_b)
            assert match is False, (
                f"Expected divergence for 'AbBa': a={res_a.return_repr}, b={res_b.return_repr}"
            )
        finally:
            sandbox.cleanup()

    def test_f65_off_by_one_detected(self, fast_config):
        """F-65: Off-by-one error detected."""
        code_a = "def length(a: list[int]) -> int:\n    return len(a)\n"
        code_b = "def length(a: list[int]) -> int:\n    return len(a) + 1\n"
        result = differential_fuzz(code_a, code_b, "length", fast_config,
                                   session_id="obo_test")
        assert result.equivalent is False
        assert len(result.failures) > 0

    def test_f68_function_name_fallback(self, fast_config):
        """F-68: Function name fallback when no signature in task."""
        code_a = "def compute(x: int) -> int:\n    return x * 2\n"
        code_b = "def compute(x: int) -> int:\n    return x * 2\n"
        task = {
            "task_id": "t2",
            "constraints": {},  # No function_signature
        }
        result = fuzz_from_task(code_a, code_b, task, fast_config,
                                session_id="fallback_test")
        assert result.equivalent is True

    def test_f69_no_function_in_code_and_no_signature(self, fast_config):
        """F-69: No function in code and no signature -> skip with equivalent=True."""
        code = "x = 42\ny = x + 1\n"
        task = {
            "task_id": "t3",
            "constraints": {},
        }
        result = fuzz_from_task(code, code, task, fast_config,
                                session_id="nofunc_test")
        assert result.equivalent is True
        assert result.skipped_reason is not None

    def test_fuzz_from_task_logs_info_on_skip(self, fast_config, caplog):
        import logging
        code = "x = 42\ny = x + 1\n"
        task = {
            "task_id": "t3",
            "constraints": {},
        }
        with caplog.at_level(logging.INFO, logger="janusmask.diff_fuzzer"):
            result = fuzz_from_task(code, code, task, fast_config, session_id="nofunc_test")
        assert result.equivalent is True
        assert result.skipped_reason is not None
        assert any("skipping" in record.message or "Could not determine" in record.message for record in caplog.records)

    def test_fuzz_from_task_skips_regardless_of_meta_task_type(self, fast_config):
        code = "x = 42\ny = x + 1\n"
        for meta_type in ["refactor", "bugfix", "feature", "rebuild", None]:
            task = {
                "task_id": f"t_{meta_type}",
                "meta_task_type": meta_type,
                "constraints": {},
            }
            result = fuzz_from_task(code, code, task, fast_config, session_id="nofunc_test")
            assert result.equivalent is True
            assert result.skipped_reason is not None

    def test_fuzz_from_task_retains_normal_behavior(self, fast_config):
        # Identical should return equivalent=True, no skipped_reason
        code_eq = "def add(a: int, b: int) -> int:\n    return a + b\n"
        task = {
            "task_id": "t_normal",
            "constraints": {
                "function_signature": "def add(a: int, b: int) -> int",
            },
        }
        result = fuzz_from_task(code_eq, code_eq, task, fast_config, session_id="task_test_normal")
        assert result.equivalent is True
        assert result.skipped_reason is None

        # Different should return equivalent=False, no skipped_reason
        code_diff = "def add(a: int, b: int) -> int:\n    return a + b + 1\n"
        result2 = fuzz_from_task(code_eq, code_diff, task, fast_config, session_id="task_test_normal_diff")
        assert result2.equivalent is False
        assert result2.skipped_reason is None

    def test_f72_sandboxes_cleaned_up(self, fast_config):
        """F-72: Sandboxes cleaned up after fuzzing."""
        import os
        code = "def add(a: int, b: int) -> int:\n    return a + b\n"
        session = "cleanup_test"
        fast_config["sandbox"]["filesystem_root"] = "/tmp/janusmask_cleanup_test"
        result = differential_fuzz(code, code, "add", fast_config, session_id=session)
        # After fuzzing, sandbox dirs should have been cleaned up
        sandbox_a_dir = f"/tmp/janusmask_cleanup_test/session_{session}_a"
        sandbox_b_dir = f"/tmp/janusmask_cleanup_test/session_{session}_b"
        assert not os.path.exists(sandbox_a_dir), f"Sandbox A dir still exists: {sandbox_a_dir}"
        assert not os.path.exists(sandbox_b_dir), f"Sandbox B dir still exists: {sandbox_b_dir}"
