"""Oracle for T_RETARGET.

Tests that external tasks retarget repo_root in spawn_agent, and short-circuit
_maybe_push_and_rebase_pin with a no-op reason.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import pytest

import harness.orchestrator as orch
import harness.autowork_daemon as ad
import harness.paths as paths


class FakeProxyCM:
    """Recording context manager standing in for proxied_session_bus()."""

    def __init__(self, sock="/tmp/fake-dbus-proxy.sock"):
        self.sock = sock
        self.entered = False
        self.exited = False

    def __enter__(self):
        self.entered = True
        return self.sock

    def __exit__(self, exc_type, exc, tb):
        self.exited = True
        return False


class FakePopen:
    """Minimal Popen stand-in for faking agent process creation."""

    def __init__(self, cmd, **kwargs):
        self.cmd = cmd
        self.kwargs = kwargs
        self.pid = 4321
        self.returncode = 0

    def poll(self) -> int | None:
        return None


def _claude_config(state_dir: pathlib.Path) -> dict:
    return {
        "state_dir": str(state_dir),
        "agent_sandbox": {"bwrap": True},
        "agents": {
            "claude": {
                "command": "claude",
                "args": ["-p", "--settings", "x"],
            }
        },
    }


def test_external_repo_root_retarget(monkeypatch, tmp_path):
    """Test A: External task retargets build_jail_argv repo_root to effective_target_root."""
    captured = {}
    import harness.agent_jail as agent_jail

    monkeypatch.setattr(agent_jail, "sandbox_enabled", lambda config: True)

    def fake_build_jail_argv(cmd, **kw):
        captured["repo_root"] = kw.get("repo_root")
        captured["dbus_proxy_socket"] = kw.get("dbus_proxy_socket")
        return list(cmd)

    monkeypatch.setattr(agent_jail, "build_jail_argv", fake_build_jail_argv)

    import harness.dbus_proxy as dbus_proxy

    def fake_proxied_session_bus(*a, **k):
        return FakeProxyCM()

    monkeypatch.setattr(dbus_proxy, "proxied_session_bus", fake_proxied_session_bus)

    monkeypatch.setattr(orch, "start_stream_threads", lambda *a, **k: ())
    monkeypatch.setattr(orch.control_gate, "record_agent_pid", lambda *a, **k: None)
    monkeypatch.setattr(orch, "_assert_claude_hook_config", lambda cmd: None)
    monkeypatch.setattr(orch.subprocess, "Popen", FakePopen)

    external_dir = tmp_path / "external_target_dir"
    external_dir.mkdir()

    monkeypatch.setenv("JANUSMASK_AGENT_WORKROOT", str(tmp_path / "agentwork"))
    monkeypatch.setenv("JANUSMASK_TASK_ID", "T_RETARGET_TEST")
    monkeypatch.setenv("JANUSMASK_WORKING_DIR", str(external_dir))

    cfg = _claude_config(tmp_path / "state")
    (tmp_path / "state").mkdir(exist_ok=True)

    orch.spawn_agent("claude", "dummy_prompt", cfg, round_number=1)

    assert "repo_root" in captured, "build_jail_argv was not called"
    expected_root = paths.effective_target_root(external_dir)
    assert pathlib.Path(captured["repo_root"]) == expected_root, (
        f"Expected repo_root to be {expected_root}, got {captured['repo_root']}"
    )
    assert pathlib.Path(captured["repo_root"]) != orch.PROJECT_DIR, (
        f"repo_root was not retargeted away from PROJECT_DIR: {captured['repo_root']}"
    )


def test_self_repo_root_unchanged(monkeypatch, tmp_path):
    """Test B: Self task (no working dir) keeps repo_root at PROJECT_DIR."""
    captured = {}
    import harness.agent_jail as agent_jail

    monkeypatch.setattr(agent_jail, "sandbox_enabled", lambda config: True)

    def fake_build_jail_argv(cmd, **kw):
        captured["repo_root"] = kw.get("repo_root")
        captured["dbus_proxy_socket"] = kw.get("dbus_proxy_socket")
        return list(cmd)

    monkeypatch.setattr(agent_jail, "build_jail_argv", fake_build_jail_argv)

    import harness.dbus_proxy as dbus_proxy

    def fake_proxied_session_bus(*a, **k):
        return FakeProxyCM()

    monkeypatch.setattr(dbus_proxy, "proxied_session_bus", fake_proxied_session_bus)

    monkeypatch.setattr(orch, "start_stream_threads", lambda *a, **k: ())
    monkeypatch.setattr(orch.control_gate, "record_agent_pid", lambda *a, **k: None)
    monkeypatch.setattr(orch, "_assert_claude_hook_config", lambda cmd: None)
    monkeypatch.setattr(orch.subprocess, "Popen", FakePopen)

    monkeypatch.setenv("JANUSMASK_AGENT_WORKROOT", str(tmp_path / "agentwork"))
    monkeypatch.setenv("JANUSMASK_TASK_ID", "T_RETARGET_TEST")
    monkeypatch.delenv("JANUSMASK_WORKING_DIR", raising=False)

    cfg = _claude_config(tmp_path / "state")
    (tmp_path / "state").mkdir(exist_ok=True)

    orch.spawn_agent("claude", "dummy_prompt", cfg, round_number=1)

    assert "repo_root" in captured, "build_jail_argv was not called"
    assert pathlib.Path(captured["repo_root"]) == orch.PROJECT_DIR, (
        f"Expected repo_root to remain PROJECT_DIR, got {captured['repo_root']}"
    )


def test_external_push_noop(monkeypatch, tmp_path):
    """Test C: External push no-op short-circuits to return {'pushed': False, 'reason': 'external_noop'}."""
    external_dir = tmp_path / "external_target_dir"
    external_dir.mkdir()

    monkeypatch.setenv("JANUSMASK_WORKING_DIR", str(external_dir))

    def _boom(*a, **kw):
        raise AssertionError(f"subprocess.run must not be called when working_dir is external: {a!r}")

    monkeypatch.setattr(ad.subprocess, "run", _boom)

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    state_dir = tmp_path / "state"
    (state_dir / "control" / "autowork").mkdir(parents=True)
    (state_dir / "control" / "autowork" / "push.enabled").write_text("", encoding="utf-8")

    res = ad._maybe_push_and_rebase_pin(repo_root, state_dir)
    assert res == {"pushed": False, "reason": "external_noop"}, (
        f"Expected external_noop reason, got {res}"
    )


def test_self_push_unchanged(monkeypatch, tmp_path):
    """Test D: Self push unchanged is still disabled by default (no push.enabled flag)."""
    monkeypatch.delenv("JANUSMASK_WORKING_DIR", raising=False)

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    state_dir = tmp_path / "state"
    (state_dir / "control" / "autowork").mkdir(parents=True)

    res = ad._maybe_push_and_rebase_pin(repo_root, state_dir)
    assert res == {"pushed": False, "reason": "disabled"}, (
        f"Expected disabled reason, got {res}"
    )
