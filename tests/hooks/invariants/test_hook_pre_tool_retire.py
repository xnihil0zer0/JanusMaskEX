"""P4 invariant: ``harness/hook_pre_tool.py`` shim is runtime-retired
(HOOK-45).

After HOOK-41, the orchestrator's ``_build_agent_command`` points the
Claude worker at ``config/claude_worker_hooks.json`` (synthesis) or
``config/claude_worker_planning_hooks.json`` (planning/reconciliation).
Both of those configs register ``python3 -m harness.hooks.claude.pre_tool``
as the PreToolUse handler — the shim at ``harness/hook_pre_tool.py`` is
never invoked by a post-HOOK-41 worker.

The shim module intentionally remains on disk for compat with legacy
configs (``config/claude_worker.json`` + ``tests/test_hook_pre_tool.py``
per Appendix A.16), but any runtime path reachable via the live
orchestrator must go straight to the authoritative
``harness.hooks.claude.pre_tool`` module.
"""

from __future__ import annotations

import io
import json
import pathlib
import sys
from unittest.mock import patch

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import harness.hook_pre_tool as shim  # noqa: E402
from harness import orchestrator as orch_mod  # noqa: E402

_LEGACY_WORKER_JSON = str(_REPO / "config" / "claude_worker.json")


_HOOK_CONFIGS = (
    "claude_worker_hooks.json",
    "claude_worker_planning_hooks.json",
)

_LEGACY_CONFIGS = (
    "claude_worker.json",
)


def _load_config(name: str) -> dict:
    return json.loads((_REPO / "config" / name).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Invariant 1: no hook-era config invokes the shim path. Every
# PreToolUse handler routes directly to harness.hooks.claude.pre_tool.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("config_name", _HOOK_CONFIGS)
def test_hook_era_config_routes_directly_to_new_module(config_name):
    cfg = _load_config(config_name)
    entries = cfg.get("hooks", {}).get("PreToolUse", [])
    assert entries, f"{config_name} has no PreToolUse entries"
    for entry in entries:
        for h in entry.get("hooks", []):
            cmd = h.get("command", "")
            assert "hook_pre_tool.py" not in cmd, (
                f"{config_name} still invokes the shim: {cmd}"
            )
            assert "harness.hooks.claude.pre_tool" in cmd, (
                f"{config_name} PreToolUse does not route to the new "
                f"module: {cmd}"
            )


# ---------------------------------------------------------------------------
# Invariant 2: the orchestrator's post-HOOK-41 spawn command points at a
# hook-era config for Claude (both synthesis and planning/reconciliation).
# ---------------------------------------------------------------------------

def _cfg() -> dict:
    return {
        "agents": {
            "claude": {
                "command": "claude",
                "args": [
                    "-p",
                    "--settings",
                    _LEGACY_WORKER_JSON,
                ],
            },
            "gemini": {"command": "gemini", "args": ["-p"]},
        }
    }


def test_synthesis_spawn_never_references_shim(monkeypatch):
    monkeypatch.delenv("JANUSMASK_MODE", raising=False)
    cmd = orch_mod._build_agent_command("claude", "PROMPT", _cfg())
    joined = " ".join(cmd)
    assert "harness/hook_pre_tool.py" not in joined
    assert "claude_worker_hooks.json" in joined


def test_planning_spawn_never_references_shim(monkeypatch):
    monkeypatch.setenv("JANUSMASK_MODE", "planning")
    cmd = orch_mod._build_agent_command("claude", "PROMPT", _cfg())
    joined = " ".join(cmd)
    assert "harness/hook_pre_tool.py" not in joined
    assert "claude_worker_planning_hooks.json" in joined


# ---------------------------------------------------------------------------
# Invariant 3: the shim's delegation path forwards new-Claude-schema
# payloads to the authoritative module verbatim. This is the compat
# contract: the shim must NOT silently rewrite the decision.
# ---------------------------------------------------------------------------

def test_shim_delegates_new_schema_to_new_module(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    workdir = state / "workdirs" / "claude" / "sess"
    (workdir / "inbox").mkdir(parents=True)
    (workdir / "outbox").mkdir(parents=True)
    (workdir / "inbox" / "task.json").write_text(
        json.dumps({"task_id": "T"}), encoding="utf-8"
    )
    (state / "STATE.json").write_text(
        json.dumps({"round": 1, "phase": "synthesis", "task_id": "T"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("JANUSMASK_STATE_DIR", str(state))
    monkeypatch.setenv("JANUSMASK_WORK_DIR", str(workdir))
    monkeypatch.setenv("JANUSMASK_AGENT", "claude")
    monkeypatch.setenv("JANUSMASK_MODE", "synthesis")

    payload = json.dumps({
        "hook_event_name": "PreToolUse",
        "session_id": "sess",
        "tool_name": "Read",
        "tool_input": {"file_path": str(workdir / "inbox" / "task.json")},
    })
    stdout = io.StringIO()
    with patch("sys.stdin", io.StringIO(payload)), patch("sys.stdout", stdout):
        shim.main()
    out = json.loads(stdout.getvalue())
    # Read of the inbox task file is allowed by the authoritative
    # harness.hooks.claude.pre_tool HOOK-22 policy — if the shim broke
    # the delegation, this would flip.
    assert out["decision"] == "allow"


# ---------------------------------------------------------------------------
# Invariant 4: the shim still has a callable ``main`` symbol and keeps
# the legacy ``ALLOWED_TOOLS`` constant. External integrations still
# import these (tests/e2e, tests/security).
# ---------------------------------------------------------------------------

def test_shim_module_retains_legacy_api_surface():
    assert callable(shim.main)
    assert "mcp__janusmask__execute" in shim.ALLOWED_TOOLS


# ---------------------------------------------------------------------------
# Invariant 5: the legacy configs (used by some pre-P4 tests) still
# reference the shim by path — deleting the shim file would strand
# those tests. Guards the "retire-at-runtime, keep-on-disk" decision.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", _LEGACY_CONFIGS)
def test_legacy_config_still_references_shim_path(name):
    cfg = _load_config(name)
    serialized = json.dumps(cfg)
    assert "hook_pre_tool.py" in serialized, (
        f"legacy {name} no longer references the shim — either the shim "
        f"was deleted without updating legacy tests, or the config was "
        f"re-written outside HOOK-45 scope. Verify intent."
    )


# ---------------------------------------------------------------------------
# Invariant 6: harness/hook_pre_tool.py still exists on disk.
# ---------------------------------------------------------------------------

def test_shim_file_exists_on_disk():
    assert (_REPO / "harness" / "hook_pre_tool.py").is_file()
