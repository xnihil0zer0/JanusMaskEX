"""Oracle: the overseer agent spawn inherits the operator's MCP servers.

`overseer.turn_runner.make_seams` builds the four real seams for the driver.
This oracle pins the contract that its ``jail_builder`` seam wires the SAME MCP
servers the operator's Claude Code uses -- the set declared in
``$HOME/.claude.json``'s ``mcpServers`` -- into every overseer spawn:

  1. the ``mcp__<server>`` tool tokens are appended to the agent's ``--tools``
     allowlist (so the withheld-by-default MCP tools become callable), and
  2. the host paths each stdio MCP server needs (its command/arg/env paths, and
     any ``--user-data-dir``) are bound into the bubblewrap jail -- read-only,
     except a ``--user-data-dir`` which is read-write -- so the stdio servers
     can actually spawn inside the jail.

The tokens are granted regardless of mode (no per-mode rationing). When the
operator has no ``mcpServers`` the spawn is byte-for-byte unchanged.

All fixtures are hermetic: a tmp ``$HOME`` with a synthetic ``.claude.json`` and
tmp server install paths; no real agent, network, or model call.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from overseer import turn_runner


# --- helpers ---------------------------------------------------------------

def _tools_value(argv):
    """Return the comma-joined value following ``--tools`` (or '' if absent)."""
    if "--tools" in argv:
        i = argv.index("--tools")
        if i + 1 < len(argv):
            return argv[i + 1]
    return ""


def _binds(argv, flag):
    """Collect the source path of every ``flag SRC DST`` triple in argv."""
    out = []
    for i, tok in enumerate(argv):
        if tok == flag and i + 2 < len(argv):
            out.append(argv[i + 1])
    return out


def _seed_home(tmp_path):
    """Build a tmp $HOME whose .claude.json declares two stdio MCP servers.

    The referenced command/arg/env/profile paths are created on disk so the jail
    binder (which skips non-existent sources) actually emits their binds.
    """
    home = tmp_path / "home"
    # alpha: an absolute-command server -> command dir is the ro bind.
    alpha_dir = home / "alpha"
    alpha_dir.mkdir(parents=True)
    (alpha_dir / "alpha-server").write_text("#!bin\n")
    # beta: python -m style; absolute script arg + PYTHONPATH env + a profile.
    beta_lib = home / "betalib"
    (beta_lib / "pkg").mkdir(parents=True)
    beta_script = beta_lib / "server.py"
    beta_script.write_text("# server\n")
    beta_profile = home / "beta-profile"
    beta_profile.mkdir(parents=True)
    servers = {
        "alpha": {
            "type": "stdio",
            "command": str(alpha_dir / "alpha-server"),
            "args": [],
            "env": {},
        },
        "beta": {
            "type": "stdio",
            "command": "python3",
            "args": [str(beta_script), "--user-data-dir=" + str(beta_profile)],
            "env": {"PYTHONPATH": str(beta_lib)},
        },
    }
    (home / ".claude.json").write_text(json.dumps({"mcpServers": servers}))
    return home, {
        "alpha_dir": str(alpha_dir),
        "beta_lib": str(beta_lib),
        "beta_script_dir": str(beta_lib),
        "beta_profile": str(beta_profile),
    }


def _make_seams(tmp_path, *, bwrap, home):
    repo = tmp_path / "repo"
    state = tmp_path / "repo" / "state"
    work = tmp_path / "work"
    for d in (repo, state, work):
        d.mkdir(parents=True, exist_ok=True)
    config = {"agent_sandbox": {"bwrap": bool(bwrap)}, "agents": {"claude": {}}}
    return turn_runner.make_seams(
        config=config, repo_root=repo, state_dir=state, work_dir=work)


# --- tests -----------------------------------------------------------------

def test_mcp_tool_tokens_appended_to_tools(monkeypatch, tmp_path):
    """Every operator mcpServers entry yields an mcp__<name> token in --tools."""
    home, _ = _seed_home(tmp_path)
    monkeypatch.setenv("HOME", str(home))
    _, _, jail_builder, _ = _make_seams(tmp_path, bwrap=False, home=home)

    out = jail_builder(["claude", "-p", "--tools", "Read,Grep,Glob"])
    tools = _tools_value(out).split(",")
    assert "mcp__alpha" in tools
    assert "mcp__beta" in tools
    # the per-mode allowlist is preserved, not replaced.
    assert "Read" in tools and "Grep" in tools and "Glob" in tools


def test_mcp_server_paths_bound_into_jail(monkeypatch, tmp_path):
    """Stdio server command/arg/env paths are ro-bound; --user-data-dir is rw."""
    if shutil.which("bwrap") is None:
        pytest.skip("bwrap not available")
    home, paths = _seed_home(tmp_path)
    monkeypatch.setenv("HOME", str(home))
    _, _, jail_builder, _ = _make_seams(tmp_path, bwrap=True, home=home)

    out = jail_builder(["claude", "-p", "--tools", "Read"])
    assert out[0].endswith("bwrap")
    ro = _binds(out, "--ro-bind")
    rw = _binds(out, "--bind")
    # alpha command dir + beta script dir + beta PYTHONPATH are read-only binds.
    assert paths["alpha_dir"] in ro
    assert paths["beta_script_dir"] in ro
    assert paths["beta_lib"] in ro
    # the playwright-style --user-data-dir profile is a read-WRITE bind.
    assert paths["beta_profile"] in rw
    # the profile must NOT also be a read-only bind (rw wins).
    assert paths["beta_profile"] not in ro
    # tokens still injected on the jailed path.
    assert "mcp__beta" in _tools_value(out).split(",")


def test_no_servers_leaves_spawn_unchanged(monkeypatch, tmp_path):
    """With no operator mcpServers, no mcp token and no extra bind appear."""
    home = tmp_path / "emptyhome"
    home.mkdir()
    (home / ".claude.json").write_text(json.dumps({"mcpServers": {}}))
    monkeypatch.setenv("HOME", str(home))
    _, _, jail_builder, _ = _make_seams(tmp_path, bwrap=False, home=home)

    out = jail_builder(["claude", "-p", "--tools", "Read,Grep"])
    assert "mcp__" not in _tools_value(out)
    assert _tools_value(out) == "Read,Grep"


def test_missing_claude_json_is_tolerated(monkeypatch, tmp_path):
    """A $HOME with no .claude.json must not break seam construction."""
    home = tmp_path / "barehome"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    _, _, jail_builder, _ = _make_seams(tmp_path, bwrap=False, home=home)

    out = jail_builder(["claude", "-p", "--tools", "Read"])
    assert "mcp__" not in _tools_value(out)
    assert _tools_value(out) == "Read"
