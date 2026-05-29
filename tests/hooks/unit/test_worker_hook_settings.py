"""Unit tests for config/claude_worker*_hooks.json (HOOK-26 / P2).

Pins the shape of the two authoritative settings files sub-plan 02 §9
prescribes. P4/P6 will flip workers onto these configs; the tests
guard against structural drift before that flip happens.
"""

from __future__ import annotations

import json
import pathlib

import pytest


PROJECT = pathlib.Path(__file__).resolve().parents[3]
SYNTH = PROJECT / "config" / "claude_worker_hooks.json"
PLANNING = PROJECT / "config" / "claude_worker_planning_hooks.json"


@pytest.fixture(scope="module")
def synth_cfg() -> dict:
    return json.loads(SYNTH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def planning_cfg() -> dict:
    return json.loads(PLANNING.read_text(encoding="utf-8"))


class TestFilesExistAndParse:
    def test_synthesis_file_exists(self):
        assert SYNTH.exists()

    def test_planning_file_exists(self):
        assert PLANNING.exists()

    def test_both_are_valid_json(self):
        json.loads(SYNTH.read_text(encoding="utf-8"))
        json.loads(PLANNING.read_text(encoding="utf-8"))


class TestPermissions:
    def test_synthesis_allow_is_exact_subset(self, synth_cfg):
        assert synth_cfg["permissions"]["allow"] == ["Read", "Glob", "Grep", "Write"]

    def test_planning_allows_agent_in_addition(self, planning_cfg):
        allow = planning_cfg["permissions"]["allow"]
        assert set(allow) >= {"Read", "Glob", "Grep", "Write"}
        assert "Agent" in allow  # sub-agents allowed in planning only

    def test_mcp_janusmask_execute_denied_both(self, synth_cfg, planning_cfg):
        for cfg in (synth_cfg, planning_cfg):
            assert "mcp__janusmask__execute" in cfg["permissions"]["deny"]

    def test_default_mode_denyAll(self, synth_cfg, planning_cfg):
        for cfg in (synth_cfg, planning_cfg):
            assert cfg["permissions"]["defaultMode"] == "denyAll"

    def test_bash_and_edit_denied_both(self, synth_cfg, planning_cfg):
        for cfg in (synth_cfg, planning_cfg):
            deny = cfg["permissions"]["deny"]
            assert "Bash" in deny
            assert "Edit" in deny


class TestEnv:
    def test_mode_differs_between_configs(self, synth_cfg, planning_cfg):
        assert synth_cfg["env"]["JANUSMASK_MODE"] == "synthesis"
        assert planning_cfg["env"]["JANUSMASK_MODE"] == "planning"

    def test_both_stamp_agent_claude(self, synth_cfg, planning_cfg):
        for cfg in (synth_cfg, planning_cfg):
            assert cfg["env"]["JANUSMASK_AGENT"] == "claude"

    def test_no_claude_project_dir_derived_env(self, synth_cfg, planning_cfg):
        """CONTAIN C1: the worker hook config must NOT derive JANUSMASK_* or
        PYTHONPATH from ${CLAUDE_PROJECT_DIR}. CLAUDE_PROJECT_DIR now points at the
        outside-repo work_dir (closing the project-root leak), so any
        ${CLAUDE_PROJECT_DIR}-interpolated path here would repoint the harness vars
        off the repo. The orchestrator process env supplies JANUSMASK_PROJECT_DIR,
        JANUSMASK_STATE_DIR, JANUSMASK_WORK_DIR and PYTHONPATH explicitly instead."""
        for cfg in (synth_cfg, planning_cfg):
            env = cfg["env"]
            for leaked in ("JANUSMASK_PROJECT_DIR", "JANUSMASK_STATE_DIR",
                           "JANUSMASK_WORK_DIR", "PYTHONPATH"):
                assert leaked not in env, (
                    f"{leaked} must not be set in the worker hook config "
                    f"(decoupled from ${{CLAUDE_PROJECT_DIR}} by CONTAIN C1)"
                )
            # No remaining value may interpolate the (now outside-repo) project dir.
            for k, v in env.items():
                assert "${CLAUDE_PROJECT_DIR}" not in str(v), (
                    f"env[{k}]={v!r} still interpolates ${{CLAUDE_PROJECT_DIR}}"
                )


class TestHooksWiring:
    EVENTS = (
        "SessionStart",
        "UserPromptSubmit",
        "PreToolUse",
        "PostToolUse",
        "Stop",
        "PreCompact",
    )

    def test_all_events_registered_synthesis(self, synth_cfg):
        for ev in self.EVENTS:
            assert ev in synth_cfg["hooks"], f"{ev} missing in synthesis hooks"

    def test_all_events_registered_planning(self, planning_cfg):
        for ev in self.EVENTS:
            assert ev in planning_cfg["hooks"], f"{ev} missing in planning hooks"

    def test_hook_commands_route_to_harness_hooks_claude(self, synth_cfg):
        expected = {
            "SessionStart": "harness.hooks.claude.session_start",
            "UserPromptSubmit": "harness.hooks.claude.user_prompt_submit",
            "PreToolUse": "harness.hooks.claude.pre_tool",
            "PostToolUse": "harness.hooks.claude.post_tool",
            "Stop": "harness.hooks.claude.stop",
            "PreCompact": "harness.hooks.claude.pre_compact",
        }
        for ev, module in expected.items():
            stanza = synth_cfg["hooks"][ev][0]
            cmd = stanza["hooks"][0]["command"]
            assert module in cmd, f"{ev} should invoke {module}; got {cmd}"

    def test_hook_timeouts_are_bounded(self, synth_cfg):
        for ev, stanzas in synth_cfg["hooks"].items():
            for stanza in stanzas:
                for hook in stanza["hooks"]:
                    t = hook.get("timeout", 0)
                    assert 1 <= t <= 60, f"{ev} timeout={t} out of bounds"
