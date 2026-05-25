"""P4 invariant: orchestrator -> worker --settings / --admin-policy
pointer flip (HOOK-41).

The worker command line must point every spawn at the hook-declaring
config that P2/P3 landed, not the MCP-era config in
``harness/config.yaml``. ``config.yaml`` stays unchanged (outside the
P4 allow-list); the rewrite happens in ``_build_agent_command`` so a
later shadow/parity run (sub-plan 06 §1) can toggle the whole block
via a feature flag without touching the YAML.

Mapping (sub-plan 04 §3.11):

    claude (synthesis)   -> config/claude_worker_hooks.json
    claude (planning)    -> config/claude_worker_planning_hooks.json
    gemini (synthesis)   -> config/gemini_worker_policy.toml            (unchanged)
    gemini (planning)    -> config/gemini_worker_policy_planning.toml   (unchanged)

Gemini hooks register via ``config/gemini_settings.json`` which
``HOOK-40`` exports as ``JANUSMASK_GEMINI_SETTINGS`` — covered by a
separate invariant file.
"""

from __future__ import annotations

import os
import pathlib
import sys

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from harness.orchestrator import _build_agent_command  # noqa: E402

_CFG = _REPO / "config"
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
    "--include-partial-messages",
    "--settings", _CLAUDE_WORKER,
    "--mcp-config", _CLAUDE_MCP,
    "--strict-mcp-config",
    "--setting-sources", "",
]

_GEMINI_ARGS = [
    "-p",
    "-o", "stream-json",
    "--admin-policy",
    _GEMINI_POLICY,
    "--allowed-mcp-server-names", "janusmask",
    "--approval-mode", "yolo",
]


def _base_config() -> dict:
    return {
        "agents": {
            "claude": {"command": "claude", "args": list(_CLAUDE_ARGS)},
            "gemini": {"command": "gemini", "args": list(_GEMINI_ARGS)},
        }
    }


@pytest.fixture(autouse=True)
def _clear_mode(monkeypatch):
    monkeypatch.delenv("JANUSMASK_MODE", raising=False)


def test_claude_synthesis_uses_hooks_config():
    cmd = _build_agent_command("claude", "PROMPT", _base_config())
    assert _CLAUDE_WORKER_HOOKS in cmd


def test_claude_planning_uses_planning_hooks_config(monkeypatch):
    monkeypatch.setenv("JANUSMASK_MODE", "planning")
    cmd = _build_agent_command("claude", "PROMPT", _base_config())
    assert (
        _CLAUDE_WORKER_PLANNING_HOOKS
        in cmd
    )


def test_claude_reconciliation_uses_planning_hooks_config(monkeypatch):
    # reconciliation shares the planning config (it's just another
    # non-synthesis mode; the TOML/JSON carve-outs are shared).
    monkeypatch.setenv("JANUSMASK_MODE", "reconciliation")
    cmd = _build_agent_command("claude", "PROMPT", _base_config())
    assert (
        _CLAUDE_WORKER_PLANNING_HOOKS
        in cmd
    )


def test_claude_synthesis_drops_legacy_worker_json():
    cmd = _build_agent_command("claude", "PROMPT", _base_config())
    assert _CLAUDE_WORKER not in cmd


def test_claude_planning_drops_legacy_planning_json(monkeypatch):
    monkeypatch.setenv("JANUSMASK_MODE", "planning")
    cmd = _build_agent_command("claude", "PROMPT", _base_config())
    assert _CLAUDE_WORKER not in cmd


def test_gemini_synthesis_keeps_policy_toml():
    cmd = _build_agent_command("gemini", "PROMPT", _base_config())
    assert (
        _GEMINI_POLICY in cmd
    )
    assert (
        _GEMINI_POLICY_PLANNING
        not in cmd
    )


def test_gemini_planning_flips_to_planning_policy(monkeypatch):
    monkeypatch.setenv("JANUSMASK_MODE", "planning")
    cmd = _build_agent_command("gemini", "PROMPT", _base_config())
    assert (
        _GEMINI_POLICY_PLANNING
        in cmd
    )
    assert (
        _GEMINI_POLICY not in cmd
    )


def test_prompt_injected_after_dash_p():
    cmd = _build_agent_command("claude", "PROMPT-A", _base_config())
    i = cmd.index("-p")
    assert cmd[i + 1] == "PROMPT-A"


def test_command_prefix_is_agent_command():
    cmd = _build_agent_command("claude", "PROMPT", _base_config())
    assert cmd[0] == "claude"
    cmd2 = _build_agent_command("gemini", "PROMPT", _base_config())
    assert cmd2[0] == "gemini"


def test_hooks_config_files_actually_exist():
    # The pointer flip is only meaningful if the files it points at exist.
    # If someone deletes config/claude_worker_hooks.json in a later
    # refactor, the synthesis branch will spawn a worker that can't
    # load its settings — catch that here rather than in a live run.
    _REPO = pathlib.Path(__file__).resolve().parents[3]
    for name in (
        "claude_worker_hooks.json",
        "claude_worker_planning_hooks.json",
        "gemini_worker_policy.toml",
        "gemini_worker_policy_planning.toml",
    ):
        p = _REPO / "config" / name
        assert p.is_file(), f"missing config: {p}"
