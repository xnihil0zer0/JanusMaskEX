"""Adversarial battery for HOOK-26-settings-authoritative (Phase 2).

Pins the regressions sub-plan 06 §4 and sub-plan 02 §9 flag as
high-risk during the P5→P6 drain: accidental re-permitting of
``mcp__janusmask__execute``, mode confusion between the two
configs, and dangerous tools slipping back into ``allow``.
"""

from __future__ import annotations

import json
import pathlib

import pytest


PROJECT = pathlib.Path(__file__).resolve().parents[3]
SYNTH = PROJECT / "config" / "claude_worker_hooks.json"
PLANNING = PROJECT / "config" / "claude_worker_planning_hooks.json"


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


class TestMcpExecuteDenyRegressionGuard:
    def test_neither_config_allows_mcp_execute(self):
        for p in (SYNTH, PLANNING):
            cfg = _load(p)
            assert "mcp__janusmask__execute" not in cfg["permissions"]["allow"]
            assert "mcp__janusmask__execute" in cfg["permissions"]["deny"]


class TestDangerousToolsStayDenied:
    DANGEROUS = {
        "Bash",
        "Edit",
        "WebFetch",
        "WebSearch",
        "NotebookEdit",
        "TodoWrite",
        "AskUserQuestion",
        "CronCreate",
        "CronDelete",
        "SendMessage",
        "GoogleWebSearch",
    }

    def test_synthesis_denies_all_dangerous(self):
        deny = set(_load(SYNTH)["permissions"]["deny"])
        missing = self.DANGEROUS - deny
        assert not missing, f"synthesis deny missing: {missing}"

    def test_planning_denies_all_dangerous(self):
        deny = set(_load(PLANNING)["permissions"]["deny"])
        missing = self.DANGEROUS - deny
        assert not missing, f"planning deny missing: {missing}"


class TestModeMismatchImpossibleByShape:
    def test_synthesis_config_never_sets_mode_to_planning(self):
        cfg = _load(SYNTH)
        assert cfg["env"]["JANUSMASK_MODE"] != "planning"
        assert cfg["env"]["JANUSMASK_MODE"] != "reconciliation"

    def test_planning_config_never_sets_mode_to_synthesis(self):
        cfg = _load(PLANNING)
        assert cfg["env"]["JANUSMASK_MODE"] != "synthesis"


class TestAgentToolPolicyDifference:
    def test_synthesis_denies_agent_planning_allows(self):
        s_allow = set(_load(SYNTH)["permissions"]["allow"])
        p_allow = set(_load(PLANNING)["permissions"]["allow"])
        # Synthesis must not permit sub-agents (forbids Explore/Task).
        assert "Agent" not in s_allow
        # Planning permits sub-agents (matches sub-plan 02 §3.13 planning bypass).
        assert "Agent" in p_allow


class TestHookCommandsNotSpoofed:
    def test_no_hook_command_invokes_legacy_hook_pre_tool(self):
        for p in (SYNTH, PLANNING):
            cfg = _load(p)
            for stanzas in cfg["hooks"].values():
                for stanza in stanzas:
                    for h in stanza["hooks"]:
                        # Legacy `harness.hook_pre_tool` is the retire-to-shim
                        # target (HOOK-27); the authoritative hook configs
                        # must route to the new modules directly.
                        assert "hook_pre_tool" not in h["command"]
                        assert "harness.hooks.claude." in h["command"]
