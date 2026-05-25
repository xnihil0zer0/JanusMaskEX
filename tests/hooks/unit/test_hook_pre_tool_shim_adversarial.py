"""Adversarial battery for HOOK-27-hook-pre-tool-shim (Phase 2).

Pins the dual-dispatch property: the shim cannot accidentally leak
new-schema behaviour onto legacy callers, or vice versa.
"""

from __future__ import annotations

import io
import json
from unittest.mock import patch

import pytest

import harness.hook_pre_tool as shim


def _run(payload: str, env: dict | None = None) -> dict:
    stdout = io.StringIO()
    with patch("sys.stdin", io.StringIO(payload)), patch("sys.stdout", stdout):
        shim.main()
    return json.loads(stdout.getvalue())


class TestDualDispatchIsolation:
    def test_legacy_payload_ignores_hook_event_name_absence(self, tmp_path, monkeypatch):
        """Legacy caller passes only {tool_name}; shim MUST use legacy path
        regardless of env state."""
        monkeypatch.setenv("JANUSMASK_MODE", "synthesis")
        out = _run(json.dumps({"tool_name": "mcp__janusmask__execute"}))
        # Legacy path says allow for mcp__janusmask__execute.
        assert out["decision"] == "allow"

    def test_new_style_payload_routes_to_claude_hook(self, tmp_path, monkeypatch):
        """Presence of hook_event_name triggers new-schema path —
        mcp_execute must be denied here."""
        state = tmp_path / "state"
        state.mkdir()
        workdir = state / "workdirs" / "claude" / "sess-x"
        (workdir / "inbox").mkdir(parents=True)
        (workdir / "outbox").mkdir(parents=True)
        (workdir / "inbox" / "task.json").write_text("{}")
        (state / "STATE.json").write_text(json.dumps({"round": 1, "phase": "synthesis"}))
        monkeypatch.setenv("JANUSMASK_STATE_DIR", str(state))
        monkeypatch.setenv("JANUSMASK_WORK_DIR", str(workdir))
        monkeypatch.setenv("JANUSMASK_AGENT", "claude")
        monkeypatch.setenv("JANUSMASK_MODE", "synthesis")
        payload = json.dumps({
            "hook_event_name": "PreToolUse",
            "session_id": "sess-x",
            "tool_name": "mcp__janusmask__execute",
            "tool_input": {},
        })
        out = _run(payload)
        assert out["decision"] == "deny"


class TestMalformedPayload:
    def test_non_json_input_gives_block_decision(self, tmp_path, monkeypatch):
        out = _run("not json at all")
        # Legacy pattern: deny with a malformed-input reason.
        assert out["decision"] == "deny"


class TestPlanningBypassViaLegacyEnv:
    def test_legacy_planning_mode_allows_subagent_tools(self, monkeypatch):
        """Legacy planning-mode bypass stays — sub-plan 04 §3.13:
        'Planning-mode bypass (hook_pre_tool.py:29-39) stays.'"""
        monkeypatch.setenv("JANUSMASK_MODE", "planning")
        out = _run(json.dumps({"tool_name": "Read"}))
        # Legacy path allows Read in planning mode.
        assert out["decision"] == "allow"
