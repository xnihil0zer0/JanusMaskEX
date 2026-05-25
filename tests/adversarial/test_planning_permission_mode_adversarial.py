"""Adversarial pin for ``harness/orchestrator.py:155`` permission-mode parity.

META-PLAN-PERMISSION-MODE: planning-mode claude spawns previously missed
``--permission-mode acceptEdits`` because the auto-append was gated on
``mode == 'synthesis'``. In ``-p`` mode that left claude waiting on an
interactive permission prompt and stopping with ``end_turn`` without
submitting (see logs/plan_hooks_webui_scoping.pre_fix.stderr). The fix
drops the mode clause so both planning and synthesis claude spawns receive
the flag; gemini remains unaffected (no permission-mode flag for gemini).

This file pins:
    1. claude planning gets ``--permission-mode acceptEdits``.
    2. claude synthesis still gets it (no synthesis regression).
    3. gemini never gets it, in either mode.
    4. an explicit ``--permission-mode`` already in args is not doubled
       (idempotence guard).
    5. static-source pin — the gate condition must NOT mention
       ``mode == 'synthesis'`` (catches a re-introduction of the bug).
"""
from __future__ import annotations

import inspect
import pathlib
import sys

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from harness import orchestrator as orch_mod  # noqa: E402
from harness.orchestrator import _build_agent_command  # noqa: E402

_CFG = _REPO / "config"
_CLAUDE_BASE_ARGS = [
    "-p",
    "--model", "haiku",
    "--output-format", "stream-json",
    "--include-partial-messages",
    "--settings", str(_CFG / "claude_worker.json"),
    "--mcp-config", str(_CFG / "claude_mcp.json"),
    "--strict-mcp-config",
    "--setting-sources", "",
]
_GEMINI_BASE_ARGS = [
    "-p",
    "-o", "stream-json",
    "--admin-policy", str(_CFG / "gemini_worker_policy.toml"),
    "--allowed-mcp-server-names", "janusmask",
    "--approval-mode", "yolo",
]


def _cfg() -> dict:
    return {
        "agents": {
            "claude": {"command": "claude", "args": list(_CLAUDE_BASE_ARGS)},
            "gemini": {"command": "gemini", "args": list(_GEMINI_BASE_ARGS)},
        }
    }


@pytest.fixture(autouse=True)
def _clear_mode(monkeypatch):
    monkeypatch.delenv("JANUSMASK_MODE", raising=False)


def test_claude_planning_gets_permission_mode_accept_edits(monkeypatch):
    monkeypatch.setenv("JANUSMASK_MODE", "planning")
    cmd = _build_agent_command("claude", "PROMPT", _cfg())
    assert "--permission-mode" in cmd
    idx = cmd.index("--permission-mode")
    assert cmd[idx + 1] == "acceptEdits"


def test_claude_synthesis_keeps_permission_mode_accept_edits(monkeypatch):
    monkeypatch.setenv("JANUSMASK_MODE", "synthesis")
    cmd = _build_agent_command("claude", "PROMPT", _cfg())
    assert "--permission-mode" in cmd
    idx = cmd.index("--permission-mode")
    assert cmd[idx + 1] == "acceptEdits"


def test_claude_default_mode_gets_permission_mode_accept_edits():
    # JANUSMASK_MODE unset (autouse fixture clears it) — defaults to synthesis
    # at the env-read site, but the gate must not depend on the mode value.
    cmd = _build_agent_command("claude", "PROMPT", _cfg())
    assert "--permission-mode" in cmd
    assert cmd[cmd.index("--permission-mode") + 1] == "acceptEdits"


@pytest.mark.parametrize("mode", ["planning", "synthesis", "reconciliation"])
def test_gemini_never_gets_permission_mode(monkeypatch, mode):
    monkeypatch.setenv("JANUSMASK_MODE", mode)
    cmd = _build_agent_command("gemini", "PROMPT", _cfg())
    assert "--permission-mode" not in cmd
    assert "acceptEdits" not in cmd


def test_explicit_permission_mode_not_doubled(monkeypatch):
    """If the operator pre-seeds ``--permission-mode`` in args, the
    auto-append must NOT add a second one."""
    monkeypatch.setenv("JANUSMASK_MODE", "planning")
    cfg = _cfg()
    cfg["agents"]["claude"]["args"] = (
        list(_CLAUDE_BASE_ARGS) + ["--permission-mode", "default"]
    )
    cmd = _build_agent_command("claude", "PROMPT", cfg)
    assert cmd.count("--permission-mode") == 1
    # Operator-seeded value wins (auto-append is conditional on absence).
    assert cmd[cmd.index("--permission-mode") + 1] == "default"


def test_static_source_no_mode_synthesis_clause():
    """Catch a regression of the original bug: the gate at
    orchestrator.py:155 must depend only on agent and arg-presence, NOT on
    mode == 'synthesis'."""
    src = inspect.getsource(_build_agent_command)
    # The gate line containing the auto-append condition:
    gate_lines = [
        line for line in src.splitlines()
        if "'--permission-mode' not in raw_args" in line
    ]
    assert len(gate_lines) == 1, (
        f"expected exactly one auto-append gate line, found {len(gate_lines)}: "
        f"{gate_lines}"
    )
    gate = gate_lines[0]
    assert "agent == 'claude'" in gate, gate
    # The bug: gate was originally "agent == 'claude' and mode == 'synthesis' and ..."
    assert "mode == 'synthesis'" not in gate, (
        "regression: orchestrator.py:155 re-introduced the mode-gated clause "
        "that blocked planning-mode claude spawns from auto-accepting edits. "
        f"Current gate: {gate!r}"
    )
    assert "mode ==" not in gate, (
        f"regression: orchestrator.py:155 gates auto-append on mode again: {gate!r}"
    )
