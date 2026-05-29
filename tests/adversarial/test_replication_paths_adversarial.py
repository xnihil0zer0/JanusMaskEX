"""Adversarial pins — replication: bootstrap / setup-agents / agent_workroot
(Plan 04, CASE-O). Static greps + agent_workroot() path equality. No execution.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


class TestBootstrapDroppedWorkdirs:
    def test_bootstrap_no_longer_makes_state_workdirs(self):
        src = (_REPO / "scripts" / "bootstrap.sh").read_text()
        assert "state/workdirs" not in src, (
            "bootstrap.sh still mkdirs state/workdirs — workdirs were relocated "
            "OUTSIDE the repo by AGENT_ISOLATION §3.7"
        )


class TestAgentWorkroot:
    def test_default_resolves_outside_repo(self, monkeypatch):
        from harness.paths import agent_workroot, PROJECT_ROOT
        monkeypatch.delenv("JANUSMASK_AGENT_WORKROOT", raising=False)
        wr = agent_workroot()
        assert wr == PROJECT_ROOT.parent / f"{PROJECT_ROOT.name}_agentwork"
        # Must NOT be inside the repo tree.
        assert PROJECT_ROOT.resolve() not in wr.resolve().parents
        assert wr.resolve() != PROJECT_ROOT.resolve()

    def test_env_override_absolute_not_expanduser(self, monkeypatch, tmp_path):
        from harness.paths import agent_workroot
        target = tmp_path / "wr"
        monkeypatch.setenv("JANUSMASK_AGENT_WORKROOT", str(target))
        assert agent_workroot() == target.resolve()

    def test_env_override_does_not_expanduser_tilde(self, monkeypatch):
        from harness.paths import agent_workroot
        # A literal '~' is resolved relative to CWD (NOT $HOME) — pin no expanduser.
        monkeypatch.setenv("JANUSMASK_AGENT_WORKROOT", "~/notexpanded")
        wr = agent_workroot()
        assert "notexpanded" in str(wr)
        # If expanduser ran, the path would start with the real $HOME; it must not.
        import os
        home = os.path.expanduser("~")
        assert not str(wr).startswith(home + "/notexpanded"), (
            "agent_workroot expanduser'd ~ — breaks clone portability contract"
        )


class TestSetupAgentsPins:
    def test_setup_agents_vendors_agy_and_claude_code(self):
        src = (_REPO / "scripts" / "setup-agents.sh").read_text()
        assert ".agents/agy/agy" in src
        assert ".agents/claude-code" in src
        # Version pins present.
        assert "AGY_VERSION_EXPECTED" in src
        assert "CLAUDE_CODE_PIN" in src

    def test_setup_agents_documents_node_shim_caveat(self):
        src = (_REPO / "scripts" / "setup-agents.sh").read_text()
        # The claude shim needs node on PATH at spawn — caveat must be documented.
        assert "node" in src.lower(), "node-on-PATH caveat for claude shim missing"

    def test_config_yaml_ships_tokens_not_host_paths(self):
        import yaml
        raw = yaml.safe_load((_REPO / "harness" / "config.yaml").read_text())
        # The YAML must carry ${PROJECT_ROOT} tokens, NOT resolved /home paths.
        for a in ("antigravity", "claude", "claude_fallback", "gemini"):
            cmd = raw["agents"][a]["command"]
            assert cmd.startswith("${PROJECT_ROOT}"), (
                f"{a}.command should ship a token, got {cmd!r}"
            )
