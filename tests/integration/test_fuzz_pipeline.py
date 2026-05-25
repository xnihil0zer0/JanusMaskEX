"""Integration tests: AST enforcer -> sandbox -> differential fuzzer pipeline.

Tests I-09 through I-12 from the JanusMask Phase 1 Test Plan (Section 11.3).
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from harness.sandbox import Sandbox, SandboxConfig, sandbox_from_config
from harness.diff_fuzzer import differential_fuzz, FuzzResult


@pytest.fixture
def fast_fuzz_config():
    """Config with minimal inputs for fast integration testing."""
    return {
        "fuzzing": {
            "function_level_inputs": 30,
            "timeout_per_input_ms": 15000,
            "float_tolerance": 1e-9,
            "seed": 42,
        },
        "sandbox": {
            "memory_limit_mb": 256,
            "cpu_time_limit_seconds": 5,
            "filesystem_root": "/tmp/janusmask_test_sandbox",
        },
    }


@pytest.fixture
def large_fuzz_config():
    """Config with 100+ inputs for I-12."""
    return {
        "fuzzing": {
            "function_level_inputs": 120,
            "timeout_per_input_ms": 3000,
            "float_tolerance": 1e-9,
            "seed": 42,
        },
        "sandbox": {
            "memory_limit_mb": 256,
            "cpu_time_limit_seconds": 5,
            "filesystem_root": "/tmp/janusmask_test_sandbox",
        },
    }


class TestFuzzPipeline:
    """I-09 through I-12: Sandbox <-> Differential Fuzzer integration."""

    def test_i09_end_to_end_fuzz_equivalent(self, fast_fuzz_config):
        """I-09: Fuzzer creates sandboxes, runs code, compares outputs --
        two equivalent implementations should produce equivalent=True."""
        code_a = (
            "def add(a: int, b: int) -> int:\n"
            "    return a + b\n"
        )
        code_b = (
            "def add(a: int, b: int) -> int:\n"
            "    result = a + b\n"
            "    return result\n"
        )
        result = differential_fuzz(code_a, code_b, "add", fast_fuzz_config,
                                   session_id="i09")
        assert isinstance(result, FuzzResult)
        assert result.equivalent is True
        assert result.total_inputs > 0
        assert result.matching_inputs == result.total_inputs
        assert len(result.failures) == 0
        assert result.error is None

    def test_i09_end_to_end_fuzz_divergent(self, fast_fuzz_config):
        """I-09: Fuzzer detects divergent outputs between two implementations."""
        code_a = (
            "def abs_val(x: int) -> int:\n"
            "    return abs(x)\n"
        )
        code_b = (
            "def abs_val(x: int) -> int:\n"
            "    return x\n"  # Wrong for negative values
        )
        result = differential_fuzz(code_a, code_b, "abs_val", fast_fuzz_config,
                                   session_id="i09d")
        assert isinstance(result, FuzzResult)
        assert result.equivalent is False
        assert len(result.failures) > 0
        # Failures should have input data
        for f in result.failures:
            assert f.input_args is not None
            assert f.reason  # non-empty reason string

    def test_i10_sandbox_timeout_during_fuzz(self, fast_fuzz_config):
        """I-10: Sandbox timeout triggers during fuzz -- failure recorded
        with timeout reason."""
        code_a = (
            "def slow(x: int) -> int:\n"
            "    return x + 1\n"
        )
        # code_b contains an infinite loop
        code_b = (
            "def slow(x: int) -> int:\n"
            "    while True:\n"
            "        pass\n"
        )
        # Use a very short timeout for the test
        fast_fuzz_config["fuzzing"]["timeout_per_input_ms"] = 1000
        fast_fuzz_config["sandbox"]["cpu_time_limit_seconds"] = 1
        fast_fuzz_config["fuzzing"]["function_level_inputs"] = 3

        result = differential_fuzz(code_a, code_b, "slow", fast_fuzz_config,
                                   session_id="i10")
        assert result.equivalent is False
        assert len(result.failures) > 0
        # At least one failure should be timeout-related
        timeout_reasons = [f for f in result.failures if "timeout" in f.reason]
        assert len(timeout_reasons) > 0

    def test_i11_sandbox_cleanup_after_fuzz(self, fast_fuzz_config):
        """I-11: Sandbox cleanup after fuzz completes -- no lingering temp dirs."""
        code_a = "def inc(x: int) -> int:\n    return x + 1\n"
        code_b = "def inc(x: int) -> int:\n    return x + 1\n"

        fast_fuzz_config["fuzzing"]["function_level_inputs"] = 5

        sandbox_root = Path(fast_fuzz_config["sandbox"]["filesystem_root"])

        result = differential_fuzz(code_a, code_b, "inc", fast_fuzz_config,
                                   session_id="i11")

        # differential_fuzz calls cleanup() in its finally block
        sandbox_a_dir = sandbox_root / "session_i11_a"
        sandbox_b_dir = sandbox_root / "session_i11_b"
        assert not sandbox_a_dir.exists(), "Sandbox A dir should be cleaned up"
        assert not sandbox_b_dir.exists(), "Sandbox B dir should be cleaned up"

    @pytest.mark.timeout(120)
    def test_i12_fuzz_100_plus_inputs(self, large_fuzz_config):
        """I-12: Fuzz with 100+ inputs completes -- all inputs processed
        or capped at failure limit."""
        code_a = (
            "def double(x: int) -> int:\n"
            "    return x * 2\n"
        )
        code_b = (
            "def double(x: int) -> int:\n"
            "    return x + x\n"
        )
        result = differential_fuzz(code_a, code_b, "double", large_fuzz_config,
                                   session_id="i12")
        assert result.equivalent is True
        # Should have processed a significant number of inputs
        assert result.total_inputs >= 50  # Hypothesis may deduplicate some
        assert result.error is None
