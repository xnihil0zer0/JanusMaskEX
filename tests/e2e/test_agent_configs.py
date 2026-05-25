"""E2E Agent Configuration Validation Tests (E-13 through E-21) for JanusMask.

Validates agent settings files, config.yaml structure, and design document
compliance.
"""

import ast
import json
import os
import shutil
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


# ---------------------------------------------------------------------------
# E-13 through E-15: Gemini Settings Validation
# ---------------------------------------------------------------------------

class TestGeminiSettings:
    """12.3 Gemini Agent Configuration Validation."""

    def test_e13_gemini_settings_valid_json(self):
        """E-13: config/gemini_settings.json is valid JSON."""
        settings_path = PROJECT_ROOT / "config" / "gemini_settings.json"
        assert settings_path.is_file(), "gemini_settings.json must exist"
        with open(settings_path) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_e14_gemini_native_tools_in_exclude_list(self):
        """E-14: All Gemini native tools in exclude list."""
        settings_path = PROJECT_ROOT / "config" / "gemini_settings.json"
        with open(settings_path) as f:
            data = json.load(f)

        exclude_list = data.get("tools", {}).get("exclude", [])
        excluded_set = set(exclude_list)

        # Core Gemini tools that should be excluded (from design doc)
        required_excluded = {
            "run_shell_command", "glob", "grep_search",
            "list_directory", "read_file", "read_many_files",
            "replace", "write_file",
            "google_web_search", "web_fetch",
        }

        missing = required_excluded - excluded_set
        assert not missing, f"These Gemini tools should be excluded: {missing}"

    @pytest.mark.skip(reason="Superseded by P3 MCP migration; see test_P3_worker_settings.TestLegacyMcpRegression")
    def test_e15_gemini_mcp_server_configured(self):
        """E-15: Gemini MCP server configured — janusmask entry present."""
        settings_path = PROJECT_ROOT / "config" / "gemini_settings.json"
        with open(settings_path) as f:
            data = json.load(f)

        mcp_servers = data.get("mcpServers", {})
        assert "janusmask" in mcp_servers, (
            "janusmask MCP server must be configured in gemini_settings.json"
        )

        jm = mcp_servers["janusmask"]
        assert "command" in jm, "MCP server must have a command"
        assert "args" in jm, "MCP server must have args"
        assert "env" in jm, "MCP server must have env"
        assert jm["env"].get("JANUSMASK_AGENT") == "gemini"


# ---------------------------------------------------------------------------
# E-16 through E-17: harness/config.yaml Validation
# ---------------------------------------------------------------------------

class TestHarnessConfig:
    """12.3 Config.yaml Validation."""

    def test_e16_config_yaml_valid(self):
        """E-16: harness/config.yaml is valid YAML with all required keys."""
        config_path = PROJECT_ROOT / "harness" / "config.yaml"
        assert config_path.is_file()

        with open(config_path) as f:
            config = yaml.safe_load(f)

        assert isinstance(config, dict)

        required_keys = {
            "synthesis", "fuzzing", "sandbox",
            "cross_examination", "decomposition", "agents",
        }
        for key in required_keys:
            assert key in config, f"Missing required key: {key}"

        # Check nested required keys
        assert "timeout_seconds" in config["synthesis"]
        assert "function_level_inputs" in config["fuzzing"]
        assert "memory_limit_mb" in config["sandbox"]
        assert "max_rounds" in config["cross_examination"]
        assert "max_subtasks" in config["decomposition"]
        assert "claude" in config["agents"]
        assert "gemini" in config["agents"]

    def test_e17_agent_commands_reference_real_binaries(self):
        """E-17: Agent commands in config.yaml reference real binaries.
        Note: binaries may not be installed in test environments."""
        config_path = PROJECT_ROOT / "harness" / "config.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)

        for agent in ("claude", "gemini"):
            command = config["agents"][agent]["command"]
            binary = shutil.which(command)
            if binary is None:
                pytest.skip(
                    f"E-17: {command} binary not found in PATH. "
                    "This is expected in CI/test environments without the agent CLIs."
                )
            else:
                assert os.path.isfile(binary)


# ---------------------------------------------------------------------------
# E-18 through E-21: Design Document Compliance
# ---------------------------------------------------------------------------

class TestDesignDocCompliance:
    """12.4 Design Document Compliance."""

    def test_e18_state_machine_transitions(self):
        """E-18: State machine transitions match Section 11.3 table.

        Validates that VALID_PHASES in state.py covers the phases used
        in the orchestrator pipeline.
        """
        from harness.state import VALID_PHASES

        # The design doc Section 11.3 defines transitions between these phases.
        # Our implementation uses these phase names:
        orchestrator_phases = {
            "idle",
            "synthesis",
            "ast_validation",
            "fuzzing",
            "cross_examination",
            "decomposition",
            "accepted",
            "rejected",
        }

        # All orchestrator phases must be valid
        missing = orchestrator_phases - VALID_PHASES
        assert not missing, (
            f"Orchestrator uses phases not in VALID_PHASES: {missing}"
        )

        # Verify that the orchestrator's state transitions are present
        # by checking the orchestrator code uses set_phase with valid phases
        orch_path = PROJECT_ROOT / "harness" / "orchestrator.py"
        content = orch_path.read_text()

        # These are the phase transitions from the pipeline
        expected_transitions = [
            "synthesis",
            "ast_validation",
            "fuzzing",
            "cross_examination",
            "decomposition",
            "accepted",
            "rejected",
        ]
        for phase in expected_transitions:
            # Match set_phase(phase="X"|phase='X') or state["phase"|'phase']="X"|'X'
            assert (
                f'phase="{phase}"' in content
                or f"phase='{phase}'" in content
                or f'"phase"] = "{phase}"' in content
                or f"'phase'] = '{phase}'" in content
            ), (
                f"Phase transition to '{phase}' not found in orchestrator.py"
            )

    def test_e19_initial_state_matches_design_doc(self):
        """E-19: INITIAL_STATE matches Section 3.7 JSON."""
        from harness.state import INITIAL_STATE

        # From design doc Section 3.7:
        expected_keys = {
            "task_id",
            "round",
            "phase",
            "claude_status",
            "gemini_status",
            "antigravity_status",
            "status_updated_at_epoch",
            "fuzz_results",
            "cross_exam_round",
            "decomposed",
            "parent_task",
            "children",
        }

        actual_keys = set(INITIAL_STATE.keys())
        assert actual_keys == expected_keys, (
            f"INITIAL_STATE keys mismatch.\n"
            f"Missing: {expected_keys - actual_keys}\n"
            f"Extra: {actual_keys - expected_keys}"
        )

        # Check default values
        assert INITIAL_STATE["task_id"] is None
        assert INITIAL_STATE["round"] == 0
        assert INITIAL_STATE["phase"] == "idle"
        assert INITIAL_STATE["claude_status"] == "pending"
        assert INITIAL_STATE["gemini_status"] == "pending"
        assert INITIAL_STATE["fuzz_results"] is None
        assert INITIAL_STATE["cross_exam_round"] == 0
        assert INITIAL_STATE["decomposed"] is False
        assert INITIAL_STATE["parent_task"] is None
        assert INITIAL_STATE["children"] == []

    def test_e20_mcp_tool_schema(self):
        """E-20: MCP tool schema matches Section 5.1."""
        from harness.mcp_server import EXECUTE_TOOL

        assert EXECUTE_TOOL["name"] == "execute"
        schema = EXECUTE_TOOL["inputSchema"]
        assert schema["type"] == "object"

        props = schema["properties"]
        assert "command" in props
        assert "args" in props

        # Check command enum (5 commands from design doc)
        command_enum = props["command"]["enum"]
        expected_commands = {
            "get_task",
            "submit_code",
            "request_clarification",
            "report_error",
            "get_feedback",
        }
        assert set(command_enum) == expected_commands

        # Check required fields
        assert "command" in schema.get("required", [])

    def test_e21_directory_structure(self):
        """E-21: Harness directory structure matches Section 12.1."""
        # Required files from design doc Section 12.1
        required_files = [
            "harness/orchestrator.py",
            "harness/mcp_server.py",
            "harness/hook_pre_tool.py",
            "harness/ast_enforcer.py",
            "harness/diff_fuzzer.py",
            "harness/cross_examiner.py",
            "harness/task_decomposer.py",
            "harness/sandbox.py",
            "harness/state.py",
            "config/gemini_settings.json",
        ]

        for rel_path in required_files:
            full_path = PROJECT_ROOT / rel_path
            assert full_path.is_file(), (
                f"Required file missing: {rel_path}"
            )

        # Required directories
        required_dirs = [
            "harness",
            "config",
        ]

        for rel_dir in required_dirs:
            full_dir = PROJECT_ROOT / rel_dir
            assert full_dir.is_dir(), (
                f"Required directory missing: {rel_dir}"
            )
