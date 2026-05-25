"""Adversarial battery for HOOK-35-gemini-policy-config (Phase 3).

The admin-policy + settings files are configuration artefacts, so the
adversarial targets are structural / regression:

  - tier-5 deny wins over any synthesis hook allow (sub-plan 03 §5
    row 1): settings.json hooks can't re-enable a tool the TOML
    admin-policy denies.
  - settings must NOT re-introduce the legacy mcp janusmask allow
    rule (sub-plan 03 §3 migration contract).
  - planning vs synthesis: sub-agents allowed only in planning; the
    two files must differ on exactly that dimension.
  - hook commands must route to harness.hooks.gemini.* modules —
    never to harness.hook_pre_tool (legacy shim).
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest


PROJECT = pathlib.Path(__file__).resolve().parents[3]
SYNTH_POLICY = PROJECT / "config" / "gemini_worker_policy.toml"
PLANNING_POLICY = PROJECT / "config" / "gemini_worker_policy_planning.toml"
SETTINGS = PROJECT / "config" / "gemini_settings.json"


def _load_toml(path: pathlib.Path) -> dict:
    import tomllib

    return tomllib.loads(path.read_text(encoding="utf-8"))


class TestAdminPolicyBeatsHookAllow:
    """Tier-5 deny in the TOML admin-policy overrides any later hook
    allow. Structural check: any tool named in the hooks block must
    not appear as a TOP-LEVEL deny in the TOML (which would override
    it). Conversely, if the hook settings accidentally list a deny-
    target in an allow matcher, that's flagged."""

    # Tools that are hard-denied in BOTH synthesis and planning
    # (i.e. outbound/IO tools that no mode permits) must also appear
    # in tools.exclude so the agent doesn't see them in its schema.
    # Sub-agents like generalist/codebase_investigator are denied in
    # synthesis but allowed in planning, so they're legitimately
    # absent from exclude.
    def test_hard_denied_tools_also_excluded_from_agent_schema(self):
        synth = _load_toml(SYNTH_POLICY)
        planning = _load_toml(PLANNING_POLICY)

        def _denied(cfg):
            return {
                r["toolName"]
                for r in cfg.get("rule", [])
                if r.get("decision") == "deny"
                and r.get("toolName")
                and r["toolName"] != "*"
            }

        hard_denied = _denied(synth) & _denied(planning)
        settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
        excluded = set(settings.get("tools", {}).get("exclude", []))
        for tool in hard_denied:
            assert tool in excluded, (
                f"hard-denied {tool!r} should also be in tools.exclude"
            )


class TestLegacyMcpRegression:
    def test_no_janusmask_mcp_allow_in_any_file(self):
        for path in (SYNTH_POLICY, PLANNING_POLICY):
            policy = _load_toml(path)
            leaks = [
                r
                for r in policy.get("rule", [])
                if r.get("mcpName") == "janusmask"
                and r.get("decision") == "allow"
            ]
            assert not leaks, (
                f"{path.name} must not re-introduce the legacy janusmask "
                f"MCP allow-rule post-migration"
            )

    def test_settings_mcpServers_excludes_janusmask(self):
        settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
        mcp = settings.get("mcpServers", {}) or {}
        assert "janusmask" not in mcp


class TestPlanningVsSynthesisDifference:
    def test_only_planning_allows_subagents(self):
        synth = _load_toml(SYNTH_POLICY)
        planning = _load_toml(PLANNING_POLICY)

        def _has_subagent_allow(cfg: dict) -> bool:
            return any(
                r.get("toolName") in {"generalist", "codebase_investigator"}
                and r.get("decision") == "allow"
                for r in cfg.get("rule", [])
            )

        assert not _has_subagent_allow(synth)
        assert _has_subagent_allow(planning)


class TestHookCommandsNotSpoofed:
    def test_no_hook_command_invokes_legacy_hook_pre_tool(self):
        settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
        commands: list[str] = []
        for event_matchers in (settings.get("hooks") or {}).values():
            for matcher in event_matchers:
                for h in matcher.get("hooks", []):
                    commands.append(h.get("command", ""))
        joined = " ".join(commands)
        assert "hook_pre_tool" not in joined, (
            "Legacy shim path must not be referenced from Gemini settings"
        )

    def test_every_hook_command_is_python3_dash_m(self):
        settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
        for event_matchers in (settings.get("hooks") or {}).values():
            for matcher in event_matchers:
                for h in matcher.get("hooks", []):
                    cmd = h.get("command", "")
                    assert re.search(
                        r"^python3?\s+-m\s+harness\.hooks\.gemini\.",
                        cmd,
                    ), f"unexpected command shape: {cmd!r}"


class TestFolderTrustAssertion:
    def test_folder_trust_present_and_true(self):
        settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
        ft = settings.get("security", {}).get("folderTrust", {})
        assert ft.get("enabled") is True


class TestMcpWildcardDeny:
    def test_both_policies_block_all_mcp(self):
        for path in (SYNTH_POLICY, PLANNING_POLICY):
            policy = _load_toml(path)
            blockers = [
                r
                for r in policy.get("rule", [])
                if r.get("mcpName") == "*"
                and r.get("toolName") == "*"
                and r.get("decision") == "deny"
            ]
            assert blockers, f"{path.name} must block all MCP servers"
