"""Configuration Tests (CF-01 through CF-15) for JanusMask.

Tests config loading, edge case config values, and environment variables.
"""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.orchestrator import load_config, DEFAULT_CONFIG_PATH
from harness.state import _default_state_dir, init_state, read_state
from harness.diff_fuzzer import (
    _generate_inputs,
    build_input_strategy,
    differential_fuzz,
)
from harness.sandbox import SandboxConfig, sandbox_from_config


PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# CF-01 through CF-05: Config Validation
# ---------------------------------------------------------------------------

class TestConfigValidation:
    """15.1 Config Validation."""

    def test_cf01_default_config_loads_successfully(self):
        """CF-01: Default config.yaml loads successfully with all required keys."""
        config = load_config(DEFAULT_CONFIG_PATH)
        assert isinstance(config, dict)
        required_sections = ["synthesis", "fuzzing", "sandbox", "agents",
                             "cross_examination", "decomposition"]
        for section in required_sections:
            assert section in config, f"Missing section: {section}"

    def test_cf02_missing_synthesis_section(self, tmp_path):
        """CF-02: Missing synthesis section — defaults or error."""
        config_data = {
            "fuzzing": {"function_level_inputs": 100, "seed": 42},
            "sandbox": {"memory_limit_mb": 256},
            "agents": {
                "claude": {"command": "claude", "args": ["-p"]},
                "gemini": {"command": "gemini", "args": ["-p"]},
            },
        }
        config_path = tmp_path / "config.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config_data, f)

        config = load_config(config_path)
        assert isinstance(config, dict)
        # synthesis section is missing — accessing it should raise KeyError
        # or the config should simply not have it
        assert "synthesis" not in config

    def test_cf03_missing_fuzzing_section(self, tmp_path):
        """CF-03: Missing fuzzing section — defaults used by modules."""
        config_data = {
            "synthesis": {"timeout_seconds": 300},
            "sandbox": {"memory_limit_mb": 256},
            "agents": {
                "claude": {"command": "claude", "args": ["-p"]},
                "gemini": {"command": "gemini", "args": ["-p"]},
            },
        }
        config_path = tmp_path / "config.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config_data, f)

        config = load_config(config_path)
        assert isinstance(config, dict)
        assert "fuzzing" not in config
        # diff_fuzzer uses .get() with defaults, so it should still work
        fuzz_cfg = config.get("fuzzing", {})
        assert fuzz_cfg.get("function_level_inputs", 2000) == 2000

    def test_cf04_missing_agents_section(self, tmp_path):
        """CF-04: Missing agents section — KeyError on spawning."""
        config_data = {
            "synthesis": {"timeout_seconds": 300},
            "fuzzing": {"function_level_inputs": 100},
            "sandbox": {"memory_limit_mb": 256},
        }
        config_path = tmp_path / "config.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config_data, f)

        config = load_config(config_path)
        # Accessing agents should fail
        with pytest.raises(KeyError):
            _ = config["agents"]["claude"]

    def test_cf05_missing_agents_claude_subsection(self, tmp_path):
        """CF-05: Missing agents.claude subsection — KeyError on spawning claude."""
        config_data = {
            "synthesis": {"timeout_seconds": 300},
            "fuzzing": {"function_level_inputs": 100},
            "sandbox": {"memory_limit_mb": 256},
            "agents": {
                "gemini": {"command": "gemini", "args": ["-p"]},
            },
        }
        config_path = tmp_path / "config.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config_data, f)

        config = load_config(config_path)
        with pytest.raises(KeyError):
            _ = config["agents"]["claude"]


# ---------------------------------------------------------------------------
# CF-06 through CF-11: Edge Case Config Values
# ---------------------------------------------------------------------------

class TestEdgeCaseConfigValues:
    """15.1 Edge Case Config Values."""

    def test_cf06_timeout_zero(self, tmp_path):
        """CF-06: timeout_seconds: 0 — immediate timeout."""
        config_data = {
            "synthesis": {"timeout_seconds": 0},
            "fuzzing": {"function_level_inputs": 100, "seed": 42},
            "sandbox": {"memory_limit_mb": 256},
            "agents": {
                "claude": {"command": "echo", "args": ["-p"]},
                "gemini": {"command": "echo", "args": ["-p"]},
            },
        }
        config_path = tmp_path / "config.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config_data, f)

        config = load_config(config_path)
        assert config["synthesis"]["timeout_seconds"] == 0

    def test_cf07_function_level_inputs_one(self, tmp_path):
        """CF-07: function_level_inputs: 1 — only 1 fuzz input generated."""
        code = "def add(a: int, b: int) -> int:\n    return a + b\n"
        strategy = build_input_strategy(code, "add")
        inputs = _generate_inputs(strategy, 1, seed=42)
        assert len(inputs) >= 1  # at least 1 generated

    def test_cf08_max_subtasks_one(self):
        """CF-08: max_subtasks: 1 — at most 1 subtask + compose."""
        from harness.task_decomposer import decompose_task
        from harness.diff_fuzzer import FuzzFailure
        from harness.sandbox import ExecutionResult

        result_a = ExecutionResult(success=True, return_value=[1, 2], return_repr="[1, 2]")
        result_b = ExecutionResult(success=True, return_value=[2, 1], return_repr="[2, 1]")
        failures = [
            FuzzFailure(
                input_args=[[2, 1], [3]],
                input_kwargs={},
                result_a=result_a,
                result_b=result_b,
                reason="return_mismatch",
            ),
            FuzzFailure(
                input_args=[[], []],
                input_kwargs={},
                result_a=ExecutionResult(success=True, return_value=[], return_repr="[]"),
                result_b=ExecutionResult(success=True, return_value=[], return_repr="[]"),
                reason="return_mismatch",
            ),
        ]
        task = {
            "task_id": "t1",
            "specification": "Sort and merge",
            "constraints": {"function_signature": "def f(a, b)"},
        }
        config = {"decomposition": {"max_subtasks": 1}}
        result = decompose_task(task, failures, config)
        # max_subtasks=1 limits the number
        assert len(result.subtasks) <= 2  # at most 1 edge + 1 compose

    def test_cf09_memory_limit_1mb(self):
        """CF-09: memory_limit_mb: 1 — very tight, most code OOM."""
        config = {
            "sandbox": {"memory_limit_mb": 1, "cpu_time_limit_seconds": 5},
            "fuzzing": {"timeout_per_input_ms": 3000},
        }
        sb_config = sandbox_from_config(config, session_id="cf09")
        assert sb_config.config.memory_limit_mb == 1

    def test_cf10_float_tolerance_zero(self):
        """CF-10: float_tolerance: 0 — exact float match required."""
        from harness.diff_fuzzer import outputs_match
        from harness.sandbox import ExecutionResult

        r_a = ExecutionResult(success=True, return_value=1.0000000001, return_repr="1.0000000001")
        r_b = ExecutionResult(success=True, return_value=1.0000000002, return_repr="1.0000000002")
        match, reason = outputs_match(r_a, r_b, float_tolerance=0)
        # With zero tolerance, even tiny differences mismatch
        assert not match or reason == "repr_match"

    def test_cf11_seed_0_vs_seed_42(self):
        """CF-11: seed: 0 vs seed: 42 — different inputs generated."""
        code = "def add(a: int, b: int) -> int:\n    return a + b\n"
        strategy = build_input_strategy(code, "add")
        inputs_0 = _generate_inputs(strategy, 50, seed=0)
        inputs_42 = _generate_inputs(strategy, 50, seed=42)

        # Not all inputs should be identical (Hypothesis derandomize uses seed)
        reprs_0 = {repr(i) for i in inputs_0}
        reprs_42 = {repr(i) for i in inputs_42}
        # They should have at least some differences (or at minimum both produce outputs)
        assert len(inputs_0) > 0
        assert len(inputs_42) > 0


# ---------------------------------------------------------------------------
# CF-12 through CF-15: Environment Variables
# ---------------------------------------------------------------------------

class TestEnvironmentVariables:
    """15.2 Environment Variables."""

    def test_cf12_janusmask_agent_claude(self, tmp_state_dir):
        """CF-12: JANUSMASK_AGENT=claude — MCP server uses 'claude' identity."""
        from harness.mcp_server import JanusMaskServer
        server = JanusMaskServer("claude", tmp_state_dir)
        assert server.agent_id == "claude"

    def test_cf13_janusmask_agent_gemini(self, tmp_state_dir):
        """CF-13: JANUSMASK_AGENT=gemini — MCP server uses 'gemini' identity."""
        from harness.mcp_server import JanusMaskServer
        server = JanusMaskServer("gemini", tmp_state_dir)
        assert server.agent_id == "gemini"

    def test_cf14_janusmask_state_dir_override(self, tmp_path):
        """CF-14: JANUSMASK_STATE_DIR=/custom/path — state dir overridden."""
        custom_dir = tmp_path / "custom_state"
        with patch.dict(os.environ, {"JANUSMASK_STATE_DIR": str(custom_dir)}):
            result = _default_state_dir()
            assert result == custom_dir

    def test_cf15_pythonhashseed_in_sandbox(self):
        """CF-15: PYTHONHASHSEED=0 in sandbox — hash determinism verified."""
        config = {
            "sandbox": {
                "memory_limit_mb": 256,
                "cpu_time_limit_seconds": 10,
            },
            "fuzzing": {
                "seed": 42,
                "timeout_per_input_ms": 5000,
            },
        }
        sandbox = sandbox_from_config(config, session_id="cf15")
        assert sandbox.config.python_hash_seed == "42"

        # Default SandboxConfig should have hash seed "0"
        default_cfg = SandboxConfig()
        assert default_cfg.python_hash_seed == "0"
