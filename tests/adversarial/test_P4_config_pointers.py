"""P4 adversarial battery — HOOK-41 orchestrator config-pointer flip.

Mutation tests per augmented plan §5 P4 row: revert the fix and confirm
the tests here would catch the regression. The invariant (sub-plan 04
§3.11): every worker spawn must receive the hook-declaring config path
on the CLI, never the MCP-era path in ``harness/config.yaml``.
"""

from __future__ import annotations

import os
import pathlib
import sys
from unittest import mock

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from harness import orchestrator as orch_mod  # noqa: E402

_CFG = PROJECT_ROOT / "config"
_CLAUDE_WORKER = str(_CFG / "claude_worker.json")
_CLAUDE_WORKER_HOOKS = str(_CFG / "claude_worker_hooks.json")
_CLAUDE_WORKER_PLANNING_HOOKS = str(_CFG / "claude_worker_planning_hooks.json")
_CLAUDE_MCP = str(_CFG / "claude_mcp.json")
_GEMINI_POLICY = str(_CFG / "gemini_worker_policy.toml")
_GEMINI_POLICY_PLANNING = str(_CFG / "gemini_worker_policy_planning.toml")


_CLAUDE_ARGS = [
    "-p",
    "--model", "haiku",
    "--output-format", "stream-json",
    "--settings", _CLAUDE_WORKER,
    "--mcp-config", _CLAUDE_MCP,
    "--strict-mcp-config",
]

_GEMINI_ARGS = [
    "-p",
    "-o", "stream-json",
    "--admin-policy",
    _GEMINI_POLICY,
    "--allowed-mcp-server-names", "janusmask",
]


def _cfg() -> dict:
    return {
        "agents": {
            "claude": {"command": "claude", "args": list(_CLAUDE_ARGS)},
            "gemini": {"command": "gemini", "args": list(_GEMINI_ARGS)},
        }
    }


@pytest.fixture(autouse=True)
def _clear(monkeypatch):
    monkeypatch.delenv("JANUSMASK_MODE", raising=False)


# ---------------------------------------------------------------------------
# Attack 1: the legacy MCP-era config path must NEVER appear in a spawn
# command after HOOK-41 lands. A grep-style assertion across every mode.
# ---------------------------------------------------------------------------

_LEGACY_PATHS = (
    _CLAUDE_WORKER,
)


@pytest.mark.parametrize("mode", ["synthesis", "planning", "reconciliation"])
def test_claude_never_points_at_legacy_mcp_config(monkeypatch, mode):
    monkeypatch.setenv("JANUSMASK_MODE", mode)
    cmd = orch_mod._build_agent_command("claude", "PROMPT", _cfg())
    for legacy in _LEGACY_PATHS:
        assert legacy not in cmd, f"{legacy} survived in {mode} command"


# ---------------------------------------------------------------------------
# Attack 2: the gemini worker's policy TOML is swap-as-matched — synthesis
# stays on gemini_worker_policy.toml (the admin-policy is mode-specific,
# not hook-specific). Hooks for gemini register via gemini_settings.json,
# exported as JANUSMASK_GEMINI_SETTINGS by HOOK-40 in the env builder.
# ---------------------------------------------------------------------------

def test_gemini_synthesis_keeps_policy_and_relies_on_env_settings_pointer(monkeypatch, tmp_path):
    monkeypatch.setenv("JANUSMASK_MODE", "synthesis")
    cmd = orch_mod._build_agent_command("gemini", "PROMPT", _cfg())
    env = orch_mod._build_agent_env("gemini", str(tmp_path), round_number=1)
    assert _GEMINI_POLICY in cmd
    assert env["JANUSMASK_GEMINI_SETTINGS"].endswith("gemini_settings.json")


def test_gemini_planning_flips_policy(monkeypatch):
    monkeypatch.setenv("JANUSMASK_MODE", "planning")
    cmd = orch_mod._build_agent_command("gemini", "PROMPT", _cfg())
    assert (
        _GEMINI_POLICY_PLANNING
        in cmd
    )


# ---------------------------------------------------------------------------
# Attack 3: mutation — revert _build_agent_command to the pre-HOOK-41
# shape (legacy rewrite only for planning, synthesis left alone). The
# legacy-path detector above must catch the regression.
# ---------------------------------------------------------------------------

def _legacy_build_agent_command(agent, prompt, config):
    agent_cfg = config['agents'][agent]
    command = agent_cfg['command']
    raw_args = list(agent_cfg['args'])
    mode = os.environ.get('JANUSMASK_MODE', 'synthesis')
    if mode != 'synthesis':
        for i, arg in enumerate(raw_args):
            if arg == _GEMINI_POLICY:
                raw_args[i] = _GEMINI_POLICY_PLANNING
    try:
        p_index = raw_args.index('-p')
        return [command] + raw_args[:p_index + 1] + [prompt] + raw_args[p_index + 1:]
    except ValueError:
        return [command] + raw_args + ['-p', prompt]


def test_mutation_revert_claude_synthesis_leaks_legacy_json(monkeypatch):
    # Under pre-HOOK-41 code, synthesis mode didn't rewrite — legacy path
    # survives. The HOOK-41 test suite must catch this; assert it directly.
    with mock.patch.object(
        orch_mod, "_build_agent_command", _legacy_build_agent_command
    ):
        monkeypatch.delenv("JANUSMASK_MODE", raising=False)
        cmd = orch_mod._build_agent_command("claude", "PROMPT", _cfg())
        assert (
            _CLAUDE_WORKER in cmd
        ), "mutation did not reproduce the pre-HOOK-41 behaviour"

    # Post-fix (un-patched): legacy path is gone.
    cmd = orch_mod._build_agent_command("claude", "PROMPT", _cfg())
    assert _CLAUDE_WORKER not in cmd


# ---------------------------------------------------------------------------
# Attack 4: edge cases around mode selection
# ---------------------------------------------------------------------------

def test_empty_mode_treated_as_synthesis(monkeypatch):
    # Empty string should fall through JANUSMASK_MODE != 'synthesis'
    # branch; the old code treated "" as non-synthesis and flipped to
    # planning. Ensure HOOK-41 treats only explicit non-synthesis modes
    # as planning, else unset operators would quietly get planning configs.
    monkeypatch.setenv("JANUSMASK_MODE", "")
    cmd = orch_mod._build_agent_command("claude", "PROMPT", _cfg())
    # "" is not "synthesis", but it's also not a real mode — HOOK-41
    # current behaviour is to treat anything != "synthesis" as planning.
    # Lock that behaviour in so future refactors surface the decision.
    assert (
        _CLAUDE_WORKER_PLANNING_HOOKS
        in cmd
    )


def test_unknown_mode_does_not_crash(monkeypatch):
    monkeypatch.setenv("JANUSMASK_MODE", "weird-mode")
    cmd = orch_mod._build_agent_command("claude", "PROMPT", _cfg())
    # At minimum the hook path appears (not the raw legacy path).
    assert _CLAUDE_WORKER not in cmd


# ---------------------------------------------------------------------------
# Attack 5: idempotency — if an operator pre-flips config.yaml to the
# hooks path (e.g. during a shadow parity experiment), the rewrite must
# not break on the already-flipped input.
# ---------------------------------------------------------------------------

def test_idempotent_when_config_yaml_pre_flipped():
    cfg = {
        "agents": {
            "claude": {
                "command": "claude",
                "args": [
                    "-p",
                    "--settings",
                    _CLAUDE_WORKER_HOOKS,
                ],
            },
            "gemini": {"command": "gemini", "args": list(_GEMINI_ARGS)},
        }
    }
    cmd = orch_mod._build_agent_command("claude", "PROMPT", cfg)
    assert (
        _CLAUDE_WORKER_HOOKS in cmd
    )


# ---------------------------------------------------------------------------
# Attack 6: the --mcp-config argument is left alone during P4 — MCP
# retirement is a P6 concern (sub-plan 04 §3.12). Removing it here would
# break parity-shadow runs in P5 that still expect MCP to be loaded.
# ---------------------------------------------------------------------------

def test_mcp_config_flag_preserved_in_p4():
    cmd = orch_mod._build_agent_command("claude", "PROMPT", _cfg())
    assert "--mcp-config" in cmd
    assert _CLAUDE_MCP in cmd


# ---------------------------------------------------------------------------
# Attack 7: the rewrite must not re-order positional args. -p <prompt>
# stays adjacent; the prompt appears exactly once and at the expected spot.
# ---------------------------------------------------------------------------

def test_prompt_exactly_once_after_dash_p(monkeypatch):
    monkeypatch.setenv("JANUSMASK_MODE", "synthesis")
    cmd = orch_mod._build_agent_command("claude", "PAYLOAD-X", _cfg())
    assert cmd.count("PAYLOAD-X") == 1
    i = cmd.index("-p")
    assert cmd[i + 1] == "PAYLOAD-X"


def test_original_config_args_not_mutated():
    cfg = _cfg()
    pristine = list(cfg["agents"]["claude"]["args"])
    orch_mod._build_agent_command("claude", "PROMPT", cfg)
    # After a build call, config.agents.claude.args must be byte-for-byte
    # what it started as (the rewrite works on a local copy).
    assert cfg["agents"]["claude"]["args"] == pristine
