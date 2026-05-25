"""Unit tests for the harness/hook_pre_tool.py retire-to-shim (HOOK-27 / P2).

The shim dual-dispatches:
  * payloads WITH ``hook_event_name`` (Claude Code native schema)
    delegate to harness.hooks.claude.pre_tool.main — the full HOOK-22
    decision matrix.
  * payloads WITHOUT ``hook_event_name`` (legacy MCP-era test shape)
    keep the old allow-mcp__janusmask__execute behaviour so existing
    tests/test_hook_pre_tool.py keeps passing (the file is P4 clean-up).

Gate 3 partner: imports harness.hook_pre_tool literally.
"""

from __future__ import annotations

import io
import json
from unittest.mock import patch

import pytest

import harness.hook_pre_tool
from harness import hook_pre_tool as shim


def _run(payload: str) -> dict:
    stdout = io.StringIO()
    with patch("sys.stdin", io.StringIO(payload)), patch("sys.stdout", stdout):
        shim.main()
    return json.loads(stdout.getvalue())


class TestLegacyPathPreserved:
    def test_legacy_mcp_execute_allowed(self):
        out = _run(json.dumps({"tool_name": "mcp__janusmask__execute"}))
        assert out["decision"] == "allow"

    def test_legacy_random_tool_blocked(self):
        out = _run(json.dumps({"tool_name": "random_tool"}))
        assert out["decision"] == "deny"


class TestNewStyleDelegates:
    def _stage(self, tmp_path, monkeypatch, mode="synthesis"):
        state = tmp_path / "state"
        state.mkdir()
        workdir = state / "workdirs" / "claude" / "sess"
        (workdir / "inbox").mkdir(parents=True)
        (workdir / "outbox").mkdir(parents=True)
        (workdir / "inbox" / "task.json").write_text(json.dumps({"task_id": "T"}))
        (state / "STATE.json").write_text(
            json.dumps({"round": 1, "phase": mode, "task_id": "T"})
        )
        monkeypatch.setenv("JANUSMASK_STATE_DIR", str(state))
        monkeypatch.setenv("JANUSMASK_WORK_DIR", str(workdir))
        monkeypatch.setenv("JANUSMASK_AGENT", "claude")
        monkeypatch.setenv("JANUSMASK_MODE", mode)
        return state, workdir

    def test_new_style_mcp_execute_denied(self, tmp_path, monkeypatch):
        """Regression guard: under new-schema payloads, mcp__janusmask__execute
        must be denied (matches HOOK-22 allowlist)."""
        self._stage(tmp_path, monkeypatch)
        payload = json.dumps({
            "hook_event_name": "PreToolUse",
            "session_id": "sess",
            "tool_name": "mcp__janusmask__execute",
            "tool_input": {},
        })
        out = _run(payload)
        assert out["decision"] == "deny"

    def test_new_style_read_allowed(self, tmp_path, monkeypatch):
        state, workdir = self._stage(tmp_path, monkeypatch)
        payload = json.dumps({
            "hook_event_name": "PreToolUse",
            "session_id": "sess",
            "tool_name": "Read",
            "tool_input": {"file_path": str(workdir / "inbox" / "task.json")},
        })
        out = _run(payload)
        assert out["decision"] == "allow"


class TestSymbolPassthrough:
    def test_main_importable(self):
        assert callable(shim.main)

    def test_legacy_allowed_tools_constant_preserved(self):
        # Legacy API pin: `ALLOWED_TOOLS` exists and still includes the
        # mcp verb for any external code still grepping for it.
        assert "mcp__janusmask__execute" in shim.ALLOWED_TOOLS
