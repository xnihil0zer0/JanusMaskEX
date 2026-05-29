"""Adversarial pins — ${PROJECT_ROOT}/${CONFIG_DIR}/${STATE_DIR} interpolation
across every config-command consumer (Plan 04, CASE-A/B/C).

The AGENT_ISOLATION hand-edit (9e0fc64) re-pointed all 4 agent commands in
``harness/config.yaml`` from bare ``agy``/``claude`` to vendored ABSOLUTE TOKENS
(``${PROJECT_ROOT}/.agents/agy/agy`` etc). The YAML now ships tokens, not host
paths, so EVERY consumer must interpolate or it spawns a literal nonexistent
path. These tests pin the YAML->runtime contract at each consumer:

  CASE-A: orchestrator.load_config fully resolves all 4 agents (regression pin).
  CASE-B: autowork_daemon self-heal spawn interpolates despite raw _load_config
          (and asserts _load_config itself stays raw — documents the asymmetry).
  CASE-C: planner.adversarial_review does NOT interpolate locally -> raw token
          yields a "Command not found" synthetic failure (GAP-2 foot-gun);
          interpolated path proceeds to spawn_agent.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import pytest
import yaml

_REPO = pathlib.Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_AGENTS = ("antigravity", "claude", "claude_fallback", "gemini")
_TOKENS = ("${PROJECT_ROOT}", "${CONFIG_DIR}", "${STATE_DIR}", "${HARNESS_DIR}")


# ------------------------------------------------------------------- CASE-A


class TestLoadConfigInterpolatesAllAgents:
    def test_real_config_no_residual_tokens_in_any_agent(self):
        from harness.orchestrator import load_config

        cfg = load_config()
        agents = cfg["agents"]
        for a in _AGENTS:
            assert a in agents, f"config.yaml lost agent {a!r}"
            cmd = agents[a]["command"]
            assert isinstance(cmd, str)
            for tok in _TOKENS:
                assert tok not in cmd, f"{a}.command still contains {tok}: {cmd!r}"
            for arg in agents[a].get("args", []):
                if isinstance(arg, str):
                    for tok in _TOKENS:
                        assert tok not in arg, f"{a}.args still contains {tok}: {arg!r}"

    def test_load_config_command_resolves_under_project_root(self):
        from harness.orchestrator import load_config
        from harness.paths import PROJECT_ROOT_STR

        cfg = load_config()
        for a in _AGENTS:
            cmd = cfg["agents"][a]["command"]
            assert cmd.startswith(PROJECT_ROOT_STR), (
                f"{a}.command not anchored under PROJECT_ROOT: {cmd!r}"
            )


# ------------------------------------------------------------------- CASE-B


class TestDaemonSelfHealInterpolates:
    def test_raw_load_config_keeps_tokens(self):
        """OBSERVATION: autowork_daemon._load_config does NOT interpolate.
        This is intentional (the spawn site does its own subst); double-
        interpolating here would break the spawn-site subst. Pin it so a
        refactor that 'helpfully' interpolates _load_config is caught."""
        from harness.autowork_daemon import _load_config

        raw = _load_config(_REPO / "harness" / "config.yaml")
        cmd = raw["agents"]["claude"]["command"]
        assert "${PROJECT_ROOT}" in cmd, (
            "_load_config now interpolates — would DOUBLE-interpolate at the "
            "spawn-site subst(); revert or update CASE-B"
        )

    def test_escalate_spawn_argv_is_fully_resolved(self, tmp_path, monkeypatch):
        """The self-heal spawn site (_escalate_to_autobrief) must subst tokens
        before Popen, and cwd must be an agent_workroot() subdir (outside repo)."""
        import harness.autowork_daemon as daemon

        # Stage a non-degenerate blocked task so the degenerate-escalation guard
        # (lines 586-589) does not short-circuit before the spawn.
        state_dir = tmp_path / "state"
        blocked = state_dir / "tasks" / "blocked"
        blocked.mkdir(parents=True)
        import json
        (blocked / "T_HEAL.json").write_text(json.dumps({
            "task_id": "T_HEAL",
            "objective": "fix the thing",
            "files_touched": ["harness/x.py"],
        }))

        captured: dict = {}

        class _FakePopen:
            def __init__(self, cmd, *a, **kw):
                captured["cmd"] = cmd
                captured["cwd"] = kw.get("cwd")
                self.pid = 4242

            def poll(self):
                return 0

        # _escalate_to_autobrief does `import subprocess` locally — same module
        # object, so patching subprocess.Popen captures the spawn.
        monkeypatch.setattr(subprocess, "Popen", _FakePopen)
        # Pin agent_workroot to tmp so we can assert cwd lands there.
        monkeypatch.setenv("JANUSMASK_AGENT_WORKROOT", str(tmp_path / "agentwork"))
        # Force the canonical claude command path (antigravity_mode would pick
        # antigravity; either way the token must resolve). Read the REAL config
        # relative to repo root (the function uses pathlib.Path('harness/config.yaml')).
        monkeypatch.chdir(_REPO)

        daemon._escalate_to_autobrief(state_dir, "T_HEAL", "max_retries")

        assert "cmd" in captured, "spawn never happened — guard tripped?"
        cmd0 = captured["cmd"][0]
        for tok in _TOKENS:
            assert tok not in cmd0, f"spawn command[0] still has {tok}: {cmd0!r}"
        # cwd must be the isolated workroot, NOT inside the repo.
        cwd = pathlib.Path(captured["cwd"]).resolve()
        workroot = (tmp_path / "agentwork").resolve()
        assert str(cwd).startswith(str(workroot)), (
            f"self-heal cwd {cwd} not under isolated workroot {workroot}"
        )
        assert _REPO.resolve() not in cwd.parents and cwd != _REPO.resolve(), (
            "self-heal cwd is INSIDE the repo tree — isolation broken"
        )


# ------------------------------------------------------------------- CASE-C


class TestAdversarialReviewCommandCheck:
    def _base_config(self, command: str) -> dict:
        return {
            "agents": {"claude": {"command": command, "args": ["-p"], "env": {}}},
            "planning_timeout_seconds": 5,
        }

    def test_raw_token_command_yields_synthetic_failure(self, tmp_path, monkeypatch):
        """GAP-2: adversarial_review reads command from derived_config and runs
        shutil.which() WITHOUT local interpolation. A caller that forgot
        load_config passes the raw token -> spurious 'Command not found'."""
        import json
        from harness.planner import adversarial_review

        spawned = {"called": False}
        monkeypatch.setattr(
            adversarial_review, "spawn_agent",
            lambda *a, **k: spawned.__setitem__("called", True),
        )
        cfg = self._base_config("${PROJECT_ROOT}/.agents/agy/agy")
        out_path = adversarial_review.run_adversarial_review(
            {"tasks": []}, cfg, tmp_path / "state", reviewer="claude",
        )
        data = json.loads(out_path.read_text())
        msgs = [f["message"] for f in data["findings"]]
        assert any("Command not found" in m for m in msgs), (
            f"expected synthetic 'Command not found', got {msgs!r}"
        )
        # The raw token should appear verbatim — proving NO interpolation happened.
        assert any("${PROJECT_ROOT}" in m for m in msgs)
        assert spawned["called"] is False, "spawn_agent must NOT run for missing cmd"

    def test_interpolated_existing_command_proceeds_to_spawn(self, tmp_path, monkeypatch):
        """Control: an interpolated absolute path that EXISTS (and is executable)
        passes shutil.which and reaches spawn_agent."""
        from harness.planner import adversarial_review

        stub = tmp_path / "agy_stub"
        stub.write_text("#!/bin/sh\nexit 0\n")
        stub.chmod(0o755)

        spawned = {"called": False}

        class _FakeProc:
            _work_dir = None

        def _fake_spawn(*a, **k):
            spawned["called"] = True
            # Short-circuit the downstream poll loop. run_adversarial_review wraps
            # the body in try/except and writes a synthetic failure rather than
            # propagating — that's fine; we only need to prove spawn was REACHED
            # (i.e. the existing executable passed shutil.which, no synthetic
            # 'Command not found').
            raise RuntimeError("stop-after-spawn")

        monkeypatch.setattr(adversarial_review, "spawn_agent", _fake_spawn)
        monkeypatch.setattr(adversarial_review, "kill_agent", lambda *a, **k: None)
        cfg = self._base_config(str(stub))
        out_path = adversarial_review.run_adversarial_review(
            {"tasks": []}, cfg, tmp_path / "state", reviewer="claude",
        )
        assert spawned["called"] is True, "executable command must reach spawn_agent"
        # And the synthetic failure (if any) must NOT be the command-not-found one.
        import json
        msgs = [f["message"] for f in json.loads(out_path.read_text())["findings"]]
        assert not any("Command not found" in m for m in msgs), (
            f"executable command wrongly flagged as not found: {msgs!r}"
        )
