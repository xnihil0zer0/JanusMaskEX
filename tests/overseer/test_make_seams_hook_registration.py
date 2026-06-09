"""RED oracle: make_seams registers the PreToolUse hook + exports the phase.

The overseer's agent-boundary hard-block hook (``overseer/procedure_hook.py``)
is inert unless two things happen at spawn time:

  1. it is REGISTERED into the spawn -- Claude Code auto-discovers project hooks
     from ``$CLAUDE_PROJECT_DIR/.claude/settings.json`` (and ``make_seams`` sets
     ``CLAUDE_PROJECT_DIR = work_dir`` + spawns with ``cwd=work_dir``), so
     writing ``procedure_hook.SETTINGS_FRAGMENT`` to
     ``work_dir/.claude/settings.json`` wires it with NO argv / jail change, and
  2. it can SEE the active phase -- ``env_builder`` must export the live
     ``conversation['procedure_phase']`` as ``JANUSMASK_PROCEDURE_PHASE`` so the
     hook subprocess (which only receives ``tool_name``/``tool_input``) can read
     it.

When the conversation has no ``procedure_phase`` (observe / non-procedure modes)
NO env var is exported -- the spawn behaves exactly as before. The MCP/jail argv
must stay byte-for-byte unchanged (no ``--settings`` token added).

Hermetic: no real agent, network, or model call.
"""
from __future__ import annotations

import json
from pathlib import Path

from overseer import turn_runner, procedure_hook


def _make(tmp_path, monkeypatch, *, bwrap=False):
    # Pin a clean, empty $HOME so the operator's real mcpServers never leak into
    # this hermetic test -- make_seams reads $HOME/.claude.json for MCP wiring.
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    repo = tmp_path / "repo"
    state = tmp_path / "repo" / "state"
    work = tmp_path / "work"
    for d in (repo, state, work):
        d.mkdir(parents=True, exist_ok=True)
    config = {"agent_sandbox": {"bwrap": bool(bwrap)}, "agents": {"claude": {}}}
    seams = turn_runner.make_seams(
        config=config, repo_root=repo, state_dir=state, work_dir=work)
    return seams, work


def test_env_builder_exports_live_procedure_phase(tmp_path, monkeypatch):
    """A conversation with a procedure_phase exports JANUSMASK_PROCEDURE_PHASE."""
    (_, env_builder, _, _), _work = _make(tmp_path, monkeypatch)
    env = env_builder({"procedure_phase": "ORACLE"})
    assert env["JANUSMASK_PROCEDURE_PHASE"] == "ORACLE"


def test_env_builder_no_phase_exports_nothing(tmp_path, monkeypatch):
    """A conversation with no procedure_phase exports NO phase env (fail-safe)."""
    (_, env_builder, _, _), _work = _make(tmp_path, monkeypatch)
    env = env_builder({})
    assert "JANUSMASK_PROCEDURE_PHASE" not in env
    # and explicitly None must not leak a "None" string either
    env2 = env_builder({"procedure_phase": None})
    assert "JANUSMASK_PROCEDURE_PHASE" not in env2


def test_make_seams_writes_settings_with_hook_fragment(tmp_path, monkeypatch):
    """make_seams writes procedure_hook.SETTINGS_FRAGMENT to work_dir settings."""
    _seams, work = _make(tmp_path, monkeypatch)
    settings = work / ".claude" / "settings.json"
    assert settings.exists(), "make_seams must register the hook via settings.json"
    assert json.loads(settings.read_text()) == procedure_hook.SETTINGS_FRAGMENT


def test_jail_builder_argv_unchanged_no_settings_token(tmp_path, monkeypatch):
    """The jail/argv path is byte-for-byte: no --settings token is injected.

    With a clean $HOME (no operator mcpServers) the inner argv is returned with
    only the binary resolved -- proving the hook is registered via settings.json,
    NOT by mutating the spawn argv.
    """
    (_, _, jail_builder, _), _work = _make(tmp_path, monkeypatch)
    out = jail_builder(["claude", "-p", "--tools", "Read"])
    assert "--settings" not in out
    assert out[1:] == ["-p", "--tools", "Read"]
