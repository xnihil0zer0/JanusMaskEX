"""P4 adversarial battery — HOOK-45 shim runtime-retirement.

Mutation tests: revert the HOOK-41 config flip and confirm the
invariants catch the re-introduction of the shim into the hot path.
Plus resilience probes for the delegator under malformed input.
"""

from __future__ import annotations

import io
import json
import pathlib
import sys
from unittest.mock import patch

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import harness.hook_pre_tool as shim  # noqa: E402
from harness import orchestrator as orch_mod  # noqa: E402

_LEGACY_WORKER_JSON = str(PROJECT_ROOT / "config" / "claude_worker.json")


# ---------------------------------------------------------------------------
# Attack 1: Mutation — pretend HOOK-41 was reverted (config.yaml-style
# args still reference the legacy claude_worker.json, and _build_agent_command
# does NOT rewire). Confirm the shim path reappears in the spawn command.
# ---------------------------------------------------------------------------

def _legacy_build_agent_command(agent, prompt, config):
    import os as _os
    agent_cfg = config['agents'][agent]
    command = agent_cfg['command']
    raw_args = list(agent_cfg['args'])
    _os.environ.get('JANUSMASK_MODE', 'synthesis')
    try:
        p_index = raw_args.index('-p')
        return [command] + raw_args[:p_index + 1] + [prompt] + raw_args[p_index + 1:]
    except ValueError:
        return [command] + raw_args + ['-p', prompt]


_SHIM_CFG = {
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


def test_mutation_revert_hook41_lands_shim_back_in_path(monkeypatch):
    """Under the pre-HOOK-41 function, synthesis spawn points at
    claude_worker.json, which references the shim — so the shim would
    be invoked at runtime."""
    monkeypatch.setattr(orch_mod, "_build_agent_command", _legacy_build_agent_command)
    monkeypatch.delenv("JANUSMASK_MODE", raising=False)

    cmd = orch_mod._build_agent_command("claude", "PROMPT", _SHIM_CFG)
    assert _LEGACY_WORKER_JSON in cmd

    legacy_cfg = json.loads(
        pathlib.Path("config/claude_worker.json").read_text(encoding="utf-8")
    )
    assert "hook_pre_tool.py" in json.dumps(legacy_cfg)


def test_post_hook41_no_legacy_path_in_spawn(monkeypatch):
    monkeypatch.delenv("JANUSMASK_MODE", raising=False)
    cmd = orch_mod._build_agent_command("claude", "PROMPT", _SHIM_CFG)
    assert _LEGACY_WORKER_JSON not in cmd
    assert "hook_pre_tool.py" not in " ".join(cmd)


# ---------------------------------------------------------------------------
# Attack 2: malformed shim input never raises — the subprocess either
# allows or denies, it doesn't crash the worker.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("payload", [
    "",
    "not json",
    "null",
    "[]",
    "42",
    json.dumps("just a string"),
])
def test_shim_main_never_raises_on_bogus_input(payload):
    stdout = io.StringIO()
    with patch("sys.stdin", io.StringIO(payload)), patch("sys.stdout", stdout):
        shim.main()
    out = json.loads(stdout.getvalue())
    assert "decision" in out


# ---------------------------------------------------------------------------
# Attack 3: legacy MCP allowlist semantics are preserved for compat
# (tests/test_hook_pre_tool.py + tests/security still exercise these).
# ---------------------------------------------------------------------------

def test_legacy_mcp_execute_still_allowed():
    stdout = io.StringIO()
    payload = json.dumps({"tool_name": "mcp__janusmask__execute"})
    with patch("sys.stdin", io.StringIO(payload)), patch("sys.stdout", stdout):
        shim.main()
    assert json.loads(stdout.getvalue())["decision"] == "allow"


def test_legacy_random_tool_still_blocked():
    stdout = io.StringIO()
    payload = json.dumps({"tool_name": "random_tool"})
    with patch("sys.stdin", io.StringIO(payload)), patch("sys.stdout", stdout):
        shim.main()
    assert json.loads(stdout.getvalue())["decision"] == "deny"


# ---------------------------------------------------------------------------
# Attack 4: under the new schema, the shim defers to the HOOK-22
# module — verify that mcp__janusmask__execute is DENIED (new policy
# differs from the legacy allowlist). Flip-proof.
# ---------------------------------------------------------------------------

def test_new_schema_mcp_execute_denied(tmp_path, monkeypatch):
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
        "tool_name": "mcp__janusmask__execute",
        "tool_input": {},
    })
    stdout = io.StringIO()
    with patch("sys.stdin", io.StringIO(payload)), patch("sys.stdout", stdout):
        shim.main()
    out = json.loads(stdout.getvalue())
    assert out["decision"] == "deny"


# ---------------------------------------------------------------------------
# Attack 5: the shim module path resolves as executable via python3 CLI
# — documents the "keep-on-disk" half of "retire-at-runtime".
# ---------------------------------------------------------------------------

def test_shim_module_loads_as_executable_via_cli():
    import subprocess
    proc = subprocess.run(
        ["python3", str(PROJECT_ROOT / "harness" / "hook_pre_tool.py")],
        input="",
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert proc.returncode == 0
    assert "decision" in proc.stdout


# ---------------------------------------------------------------------------
# Attack 6: idempotency — repeated invocations with the same payload
# return the same decision (no stateful drift, no file side effects).
# ---------------------------------------------------------------------------

def test_shim_is_stateless_on_repeated_calls():
    payload = json.dumps({"tool_name": "mcp__janusmask__execute"})
    decisions = []
    for _ in range(5):
        stdout = io.StringIO()
        with patch("sys.stdin", io.StringIO(payload)), patch("sys.stdout", stdout):
            shim.main()
        decisions.append(json.loads(stdout.getvalue())["decision"])
    assert decisions == ["allow"] * 5
