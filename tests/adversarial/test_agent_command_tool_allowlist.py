"""CONTAIN C4 — tighten the claude CLI tool surface (defense in depth).

``permissions.deny`` is unreliable in ``-p`` mode (upstream #6699/#27040). The
reliable in-CLI levers are ``--tools`` (built-ins not listed are never even
presented to the model) and ``--disallowedTools``. Write MUST stay -- the
submission flow writes ``outbox/submission.py`` and the harness never reads stdout.

Permission-mode note: the plan called for switching acceptEdits->default, but
claude-code >=2.1.114 silently drops hook-granted permission verbs under headless
-p (the vendored claude is 2.1.156), so 'default' would deny Write-to-outbox and
break all synthesis. acceptEdits is KEPT; the containment it would have ceded is
delivered by --tools (no Bash/Edit available) + the C2 jail (repo read-only). So
this fix-detector asserts the tool-surface hardening, NOT the removal of acceptEdits.

RED before C4 (no --tools/--disallowedTools), GREEN after.
"""
from __future__ import annotations

from pathlib import Path

import harness.orchestrator as orch


def _claude_cmd(monkeypatch):
    monkeypatch.setenv("JANUSMASK_MODE", "synthesis")
    config = orch.load_config(Path("harness/config.yaml"))
    return orch._build_agent_command("claude", "THE_PROMPT", config)


def _val(cmd, flag):
    return cmd[cmd.index(flag) + 1] if flag in cmd else None


def test_tools_restricted_to_safe_builtins(monkeypatch):
    cmd = _claude_cmd(monkeypatch)
    assert "--tools" in cmd, "claude spawn must pass --tools to bound the available set"
    tools = _val(cmd, "--tools")
    names = set(tools.replace(",", " ").split())
    assert names == {"Read", "Glob", "Grep", "Write"}, f"unexpected tool set: {tools}"
    assert "Write" in names, "Write must stay -- it is the sole submission mechanism"
    assert "Bash" not in names and "Edit" not in names


def test_dangerous_tools_disallowed(monkeypatch):
    cmd = _claude_cmd(monkeypatch)
    assert "--disallowedTools" in cmd
    disallowed = _val(cmd, "--disallowedTools").replace(",", " ").split()
    for t in ("Bash", "Edit", "Task", "NotebookEdit", "WebFetch", "WebSearch"):
        assert t in disallowed, f"{t} must be disallowed"


def test_submission_levers_preserved(monkeypatch):
    cmd = _claude_cmd(monkeypatch)
    # acceptEdits is intentionally retained (see module docstring) so Write-to-outbox
    # is not dropped under headless -p on claude-code 2.1.156.
    assert cmd[cmd.index("--permission-mode") + 1] == "acceptEdits"
    # strict-mcp-config stays (janusmask MCP allow is separate from built-ins).
    assert "--strict-mcp-config" in cmd
    # The prompt is still threaded after -p.
    assert "THE_PROMPT" in cmd
