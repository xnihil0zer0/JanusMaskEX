"""Unit tests for config/gemini_* authoritative settings (HOOK-35 / P3).

Pins the shape of the three settings files sub-plan 03 §3 prescribes:
  * config/gemini_worker_policy.toml (synthesis admin-policy)
  * config/gemini_worker_policy_planning.toml (planning admin-policy
    with sub-agent carve-outs)
  * config/gemini_settings.json (hooks block + folderTrust)

P4/P6 will flip the orchestrator onto these configs; the tests guard
against structural drift before that flip happens.
"""

from __future__ import annotations

import json
import pathlib

import pytest


PROJECT = pathlib.Path(__file__).resolve().parents[3]
SYNTH_POLICY = PROJECT / "config" / "gemini_worker_policy.toml"
PLANNING_POLICY = PROJECT / "config" / "gemini_worker_policy_planning.toml"
SETTINGS = PROJECT / "config" / "gemini_settings.json"


def _load_toml(path: pathlib.Path) -> dict:
    # Python 3.11+ has tomllib in the stdlib.
    import tomllib

    return tomllib.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def synth_policy() -> dict:
    return _load_toml(SYNTH_POLICY)


@pytest.fixture(scope="module")
def planning_policy() -> dict:
    return _load_toml(PLANNING_POLICY)


@pytest.fixture(scope="module")
def settings() -> dict:
    return json.loads(SETTINGS.read_text(encoding="utf-8"))


class TestFilesExistAndParse:
    def test_synth_policy_exists(self):
        assert SYNTH_POLICY.exists()

    def test_planning_policy_exists(self):
        assert PLANNING_POLICY.exists()

    def test_settings_exists(self):
        assert SETTINGS.exists()


class TestSynthesisPolicy:
    def test_allows_native_write_file(self, synth_policy):
        rules = synth_policy.get("rule") or []
        allows = [
            r
            for r in rules
            if r.get("toolName") == "write_file"
            and r.get("decision") == "allow"
        ]
        assert allows

    def test_allows_native_replace(self, synth_policy):
        rules = synth_policy.get("rule") or []
        allows = [
            r
            for r in rules
            if r.get("toolName") == "replace"
            and r.get("decision") == "allow"
        ]
        assert allows

    def test_allows_read_family(self, synth_policy):
        allowed = {"read_file", "read_many_files", "glob", "grep_search", "list_directory"}
        rules = synth_policy.get("rule") or []
        named_allows = {
            r.get("toolName")
            for r in rules
            if r.get("decision") == "allow"
        }
        assert allowed.issubset(named_allows)

    def test_hard_denies_web_and_memory(self, synth_policy):
        denied = {"google_web_search", "web_fetch", "write_todos", "save_memory", "cli_help"}
        rules = synth_policy.get("rule") or []
        named_denies = {
            r.get("toolName")
            for r in rules
            if r.get("decision") == "deny"
        }
        assert denied.issubset(named_denies)

    def test_mcp_wildcard_denied(self, synth_policy):
        rules = synth_policy.get("rule") or []
        mcp_deny = [
            r
            for r in rules
            if r.get("mcpName") == "*"
            and r.get("toolName") == "*"
            and r.get("decision") == "deny"
        ]
        assert mcp_deny, "must block all MCP servers post-migration"

    def test_janusmask_mcp_allow_rule_removed(self, synth_policy):
        rules = synth_policy.get("rule") or []
        janusmask_allow = [
            r
            for r in rules
            if r.get("mcpName") == "janusmask"
            and r.get("decision") == "allow"
        ]
        assert not janusmask_allow, (
            "allow-rule for mcp janusmask must be removed in hook-mode"
        )


class TestPlanningPolicy:
    def test_subagents_allowed_in_planning_only(self, planning_policy):
        rules = planning_policy.get("rule") or []
        generalist = [
            r
            for r in rules
            if r.get("toolName") == "generalist"
            and r.get("decision") == "allow"
        ]
        cb_invest = [
            r
            for r in rules
            if r.get("toolName") == "codebase_investigator"
            and r.get("decision") == "allow"
        ]
        assert generalist
        assert cb_invest

    def test_subagent_carve_outs_preserved(self, planning_policy):
        rules = planning_policy.get("rule") or []
        pairs = [
            (r.get("subagent"), r.get("toolName"))
            for r in rules
            if r.get("decision") == "allow" and r.get("subagent")
        ]
        for sa in ("generalist", "codebase_investigator"):
            for tool in ("read_file", "list_directory", "grep_search", "glob"):
                assert (sa, tool) in pairs

    def test_planning_also_allows_native_write_tools(self, planning_policy):
        # Planning agent still needs to write plan_draft.json via write_file
        # — the hook gates the outbox basename per mode.
        rules = planning_policy.get("rule") or []
        allowed = {
            r.get("toolName")
            for r in rules
            if r.get("decision") == "allow" and not r.get("subagent")
        }
        assert "write_file" in allowed


class TestSettings:
    def test_folder_trust_enabled(self, settings):
        assert (
            settings["security"]["folderTrust"]["enabled"] is True
        )

    def test_mcpServers_does_not_contain_janusmask(self, settings):
        mcp = settings.get("mcpServers") or {}
        assert "janusmask" not in mcp

    def test_hooks_block_covers_all_gemini_events(self, settings):
        hooks = settings.get("hooks") or {}
        # SessionStart, BeforeTool, AfterTool, SessionEnd are the
        # four events the Gemini twin wires. BeforeToolSelection /
        # BeforeModel / etc. are optional.
        for evt in ("SessionStart", "BeforeTool", "AfterTool", "SessionEnd"):
            assert evt in hooks, f"{evt} missing from hooks block"
            assert hooks[evt], f"{evt} is empty"

    def test_hook_commands_route_to_harness_gemini_modules(self, settings):
        hooks = settings.get("hooks") or {}
        # Flatten all command strings and check they name the expected
        # python -m modules. That way a typo in one matcher is caught.
        commands: list[str] = []
        for event_matchers in hooks.values():
            for matcher in event_matchers:
                for h in matcher.get("hooks", []):
                    commands.append(h.get("command", ""))
        joined = " ".join(commands)
        for mod in (
            "harness.hooks.gemini.session_start",
            "harness.hooks.gemini.user_prompt_submit",
            "harness.hooks.gemini.pre_tool",
            "harness.hooks.gemini.post_tool",
            "harness.hooks.gemini.stop",
        ):
            assert mod in joined, f"command for {mod} missing"

    def test_hook_timeouts_are_bounded(self, settings):
        hooks = settings.get("hooks") or {}
        for event_matchers in hooks.values():
            for matcher in event_matchers:
                for h in matcher.get("hooks", []):
                    to = h.get("timeout")
                    assert to is not None
                    # Bound timeouts so a stuck hook can't wedge a
                    # worker indefinitely. 60 seconds is the Gemini
                    # default.
                    assert 1 <= to <= 60000

    def test_model_config_preserved(self, settings):
        # Fallback model chain is preserved verbatim (sub-plan 03 §3.3
        # note: "Model chain / experimental.dynamicModelConfiguration
        # block is preserved verbatim from the existing file").
        assert "modelConfigs" in settings
