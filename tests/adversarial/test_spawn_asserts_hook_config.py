"""CONTAIN C5 — fail-closed hook-load assertion at spawn time.

The PreToolUse hook is the (now audit-grade) submission-confinement layer. C2
(jail) and C4 (--tools) are the load-bearing barriers, but a missing/typo'd
``--settings`` file is a misconfiguration we must REFUSE to launch into rather
than spawn an agent with no gate at all. ``_assert_claude_hook_config`` reads the
effective (post-rewire) ``--settings`` file and aborts if it does not declare a
PreToolUse hook.

Fix-detector: RED before C5 (no such assertion), GREEN after.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import harness.orchestrator as orch


def test_helper_exists():
    assert hasattr(orch, "_assert_claude_hook_config"), \
        "CONTAIN C5: orchestrator must expose a fail-closed hook-config assertion"


def test_real_synthesis_config_passes(monkeypatch):
    monkeypatch.setenv("JANUSMASK_MODE", "synthesis")
    config = orch.load_config(Path("harness/config.yaml"))
    cmd = orch._build_agent_command("claude", "P", config)
    # Effective settings is the rewired claude_worker_hooks.json which has PreToolUse.
    orch._assert_claude_hook_config(cmd)  # must not raise


def test_missing_pretooluse_aborts(tmp_path):
    bad = tmp_path / "no_hooks.json"
    bad.write_text(json.dumps({"permissions": {"allow": ["Write"]}, "hooks": {}}))
    cmd = ["claude", "-p", "x", "--settings", str(bad)]
    with pytest.raises(Exception):
        orch._assert_claude_hook_config(cmd)


def test_missing_settings_file_aborts(tmp_path):
    cmd = ["claude", "-p", "x", "--settings", str(tmp_path / "does_not_exist.json")]
    with pytest.raises(Exception):
        orch._assert_claude_hook_config(cmd)


def test_no_settings_flag_aborts():
    cmd = ["claude", "-p", "x"]
    with pytest.raises(Exception):
        orch._assert_claude_hook_config(cmd)


def test_pretooluse_present_passes(tmp_path):
    good = tmp_path / "ok.json"
    good.write_text(json.dumps({
        "hooks": {"PreToolUse": [{"matcher": "*", "hooks": [
            {"type": "command", "command": "python3 -m harness.hooks.claude.pre_tool"}]}]}
    }))
    cmd = ["claude", "-p", "x", "--settings", str(good)]
    orch._assert_claude_hook_config(cmd)  # must not raise
