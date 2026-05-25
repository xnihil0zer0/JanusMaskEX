"""Tests for harness/hook_pre_tool.py — PreToolUse hook enforcement."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

HOOK_SCRIPT = str(Path(__file__).resolve().parent.parent / "harness" / "hook_pre_tool.py")

import io
from unittest.mock import patch
from harness.hook_pre_tool import main

def _run_hook(payload: str) -> dict:
    """Run the hook script logic in-process via mocked sys.stdin/stdout."""
    mock_stdin = io.StringIO(payload)
    mock_stdout = io.StringIO()
    with patch("sys.stdin", mock_stdin), patch("sys.stdout", mock_stdout):
        main()
    return json.loads(mock_stdout.getvalue())

def test_hook_pre_tool_basic():
    """Basic coverage of hook_pre_tool."""
    # Hook executes without errors on valid input and outputs correct state
    resp_allow = _run_hook(json.dumps({"tool_name": "mcp__janusmask__execute"}))
    assert resp_allow["decision"] == "allow"

    # Hook executes without errors on invalid tool and outputs correct blocked state
    resp_block = _run_hook(json.dumps({"tool_name": "random_tool"}))
    assert resp_block["decision"] == "deny"
    assert "Blocked tool: random_tool" in resp_block["reason"]


# ── Normal Operation ────────────────────────────────────────────────────

class TestAllowedTool:
    def test_allows_janusmask_execute(self):
        resp = _run_hook(json.dumps({"tool_name": "mcp__janusmask__execute"}))
        assert resp["decision"] == "allow"


class TestBlockedTools:
    @pytest.mark.parametrize("tool", [
        "Bash", "Read", "Edit", "Write", "Agent",
        "WebFetch", "WebSearch", "Glob", "Grep", "NotebookEdit",
        "TodoRead", "TodoWrite", "AskUserQuestion",
        "TaskCreate", "TaskUpdate", "EnterPlanMode",
    ])
    def test_blocks_native_tool(self, tool):
        resp = _run_hook(json.dumps({"tool_name": tool}))
        assert resp["decision"] == "deny"
        assert tool in resp["reason"]


# ── Edge Cases ──────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_stdin(self):
        # Empty stdin intentionally returns allow: Claude Code sometimes
        # flushes empty stdin on hook startup; blocking would deadlock.
        # See harness/hook_pre_tool.py:49-51.
        resp = _run_hook("")
        assert resp["decision"] == "allow"

    def test_invalid_json(self):
        resp = _run_hook("NOT JSON {{{}}")
        assert resp["decision"] == "deny"

    def test_tool_name_is_integer(self):
        # Non-string tool_name is not in the allowlist, so it is blocked.
        # The reason string is the generic "Blocked tool: 42 ..." form after
        # the shim consolidation (HOOK-50).
        resp = _run_hook(json.dumps({"tool_name": 42}))
        assert resp["decision"] == "deny"
        assert "Blocked tool" in resp["reason"]

    def test_tool_name_absent(self):
        resp = _run_hook(json.dumps({"other_key": "value"}))
        assert resp["decision"] == "deny"

    def test_tool_name_empty_string(self):
        resp = _run_hook(json.dumps({"tool_name": ""}))
        assert resp["decision"] == "deny"

    def test_tool_name_trailing_space(self):
        resp = _run_hook(json.dumps({"tool_name": "mcp__janusmask__execute "}))
        assert resp["decision"] == "deny"

    def test_tool_name_uppercase(self):
        resp = _run_hook(json.dumps({"tool_name": "MCP__JANUSMASK__EXECUTE"}))
        assert resp["decision"] == "deny"

    def test_very_long_tool_name(self):
        resp = _run_hook(json.dumps({"tool_name": "x" * 10000}))
        assert resp["decision"] == "deny"

    def test_tool_name_null(self):
        resp = _run_hook(json.dumps({"tool_name": None}))
        assert resp["decision"] == "deny"

    def test_extra_keys_ignored(self):
        resp = _run_hook(json.dumps({
            "tool_name": "mcp__janusmask__execute",
            "extra": "data",
            "more": 123,
        }))
        assert resp["decision"] == "allow"

    def test_unexpected_error(self):
        # The shim consolidated all failure paths under
        # "Malformed hook input: {exc}" (hook_pre_tool.py:53-58).
        mock_stdin = io.StringIO("")
        mock_stdin.read = lambda *args: (_ for _ in ()).throw(RuntimeError("boom"))
        mock_stdout = io.StringIO()
        with patch("sys.stdin", mock_stdin), patch("sys.stdout", mock_stdout):
            main()
        resp = json.loads(mock_stdout.getvalue())
        assert resp["decision"] == "deny"
        assert "Malformed" in resp["reason"]


# ── Process Behavior ────────────────────────────────────────────────────

class TestProcessBehavior:
    def test_exit_code_zero_on_allow(self):
        result = subprocess.run(
            [sys.executable, HOOK_SCRIPT],
            input=json.dumps({"tool_name": "mcp__janusmask__execute"}),
            capture_output=True, text=True, timeout=5,
        )
        assert result.returncode == 0

    def test_exit_code_zero_on_block(self):
        result = subprocess.run(
            [sys.executable, HOOK_SCRIPT],
            input=json.dumps({"tool_name": "Bash"}),
            capture_output=True, text=True, timeout=5,
        )
        assert result.returncode == 0

    def test_output_is_valid_json(self):
        result = subprocess.run(
            [sys.executable, HOOK_SCRIPT],
            input=json.dumps({"tool_name": "Bash"}),
            capture_output=True, text=True, timeout=5,
        )
        parsed = json.loads(result.stdout)
        assert "decision" in parsed

    def test_no_stderr_on_normal_input(self):
        result = subprocess.run(
            [sys.executable, HOOK_SCRIPT],
            input=json.dumps({"tool_name": "mcp__janusmask__execute"}),
            capture_output=True, text=True, timeout=5,
        )
        assert result.stderr == ""
