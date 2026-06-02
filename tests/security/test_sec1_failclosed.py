"""SEC-1 fail-closed oracle: D-Bus proxy must fail-closed on security-critical spawns.

Asserts that if the sandbox is enabled and xdg-dbus-proxy fails to start:
1. spawn_agent refuses to spawn (raises RuntimeError) instead of falling back to the unfiltered host bus.
2. _contain_selfheal refuses the self-heal spawn (raises RuntimeError).

Asserts graceful behavior when xdg-dbus-proxy binary is absent (not installed) or when daemon is never started.
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess
from pathlib import Path

import pytest

import harness.orchestrator as orch
import harness.autowork_daemon as dae
import harness.agent_jail as agent_jail
import harness.dbus_proxy as dbus_proxy


class FailsProxyCM:
    """A mock context manager for proxied_session_bus that raises RuntimeError on enter."""
    def __enter__(self):
        raise RuntimeError("Fake D-Bus proxy failure: xdg-dbus-proxy failed to start.")
    def __exit__(self, exc_type, exc, tb):
        return False


def test_synthesis_spawn_fails_closed_when_proxy_raises_and_binary_present(monkeypatch, tmp_path):
    """
    (a) test_synthesis_spawn_fails_closed_when_proxy_raises_and_binary_present:
    monkeypatch harness.dbus_proxy.proxied_session_bus to a CM whose __enter__ raises RuntimeError;
    monkeypatch agent_jail.sandbox_enabled->True;
    monkeypatch shutil.which so 'xdg-dbus-proxy' returns '/usr/bin/xdg-dbus-proxy';
    spy agent_jail.build_jail_argv to record calls;
    monkeypatch orch.subprocess.Popen, start_stream_threads, control_gate.record_agent_pid, _assert_claude_hook_config to no-ops.
    Call orch.spawn_agent('claude', 'x', cfg) and assert it RAISES (pytest.raises) AND that
    build_jail_argv was NEVER called with dbus_proxy_socket=None.
    """
    jail_calls = []
    def spy_build_jail_argv(cmd, **kwargs):
        jail_calls.append(kwargs.get("dbus_proxy_socket"))
        return list(cmd)
    monkeypatch.setattr(agent_jail, "build_jail_argv", spy_build_jail_argv)

    # Force sandbox enabled
    monkeypatch.setattr(agent_jail, "sandbox_enabled", lambda config: True)

    # Mock xdg-dbus-proxy to be present
    original_which = shutil.which
    def mock_which(binary):
        if binary == "xdg-dbus-proxy":
            return "/usr/bin/xdg-dbus-proxy"
        if binary == "bwrap":
            return "/usr/bin/bwrap"
        return original_which(binary)
    monkeypatch.setattr(shutil, "which", mock_which)

    # Mock proxied_session_bus to fail
    monkeypatch.setattr(dbus_proxy, "proxied_session_bus", lambda: FailsProxyCM())

    # Neuter subprocessing and stream threads
    monkeypatch.setattr(orch, "start_stream_threads", lambda *a, **k: ())
    monkeypatch.setattr(orch.control_gate, "record_agent_pid", lambda *a, **k: None)
    monkeypatch.setattr(orch, "_assert_claude_hook_config", lambda cmd: None)

    class FakePopen:
        def __init__(self, cmd, **kwargs):
            self.cmd = cmd
            self.kwargs = kwargs
            self.pid = 9999
            self.returncode = 0
            self._dbus_stack = None
        def poll(self):
            return 0
    monkeypatch.setattr(orch.subprocess, "Popen", FakePopen)

    cfg = {
        "state_dir": str(tmp_path / "state"),
        "agent_sandbox": {"bwrap": True},
        "agents": {
            "claude": {
                "command": "claude",
                "args": ["-p", "--settings", "x"]
            }
        }
    }
    monkeypatch.setenv("JANUSMASK_AGENT_WORKROOT", str(tmp_path / "agentwork"))
    monkeypatch.setenv("JANUSMASK_TASK_ID", "FAILCLOSED_TEST")
    (tmp_path / "agentwork").mkdir(parents=True, exist_ok=True)
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)

    with pytest.raises(RuntimeError) as excinfo:
        orch.spawn_agent('claude', 'x', cfg)
    assert "filtered D-Bus proxy failed to start" in str(excinfo.value)
    assert None not in jail_calls


def test_synthesis_spawn_graceful_when_proxy_binary_absent(monkeypatch, tmp_path):
    """
    (b) test_synthesis_spawn_graceful_when_proxy_binary_absent:
    same but monkeypatch shutil.which to return None for 'xdg-dbus-proxy'.
    Assert spawn_agent does NOT raise and build_jail_argv received dbus_proxy_socket=None.
    """
    jail_calls = []
    def spy_build_jail_argv(cmd, **kwargs):
        jail_calls.append(kwargs.get("dbus_proxy_socket"))
        return list(cmd)
    monkeypatch.setattr(agent_jail, "build_jail_argv", spy_build_jail_argv)

    # Force sandbox enabled
    monkeypatch.setattr(agent_jail, "sandbox_enabled", lambda config: True)

    # Mock xdg-dbus-proxy to be absent
    original_which = shutil.which
    def mock_which(binary):
        if binary == "xdg-dbus-proxy":
            return None
        if binary == "bwrap":
            return "/usr/bin/bwrap"
        return original_which(binary)
    monkeypatch.setattr(shutil, "which", mock_which)

    # Mock proxied_session_bus to fail
    monkeypatch.setattr(dbus_proxy, "proxied_session_bus", lambda: FailsProxyCM())

    # Neuter subprocessing and stream threads
    monkeypatch.setattr(orch, "start_stream_threads", lambda *a, **k: ())
    monkeypatch.setattr(orch.control_gate, "record_agent_pid", lambda *a, **k: None)
    monkeypatch.setattr(orch, "_assert_claude_hook_config", lambda cmd: None)

    class FakePopen:
        def __init__(self, cmd, **kwargs):
            self.cmd = cmd
            self.kwargs = kwargs
            self.pid = 9999
            self.returncode = 0
            self._dbus_stack = None
        def poll(self):
            return 0
    monkeypatch.setattr(orch.subprocess, "Popen", FakePopen)

    cfg = {
        "state_dir": str(tmp_path / "state"),
        "agent_sandbox": {"bwrap": True},
        "agents": {
            "claude": {
                "command": "claude",
                "args": ["-p", "--settings", "x"]
            }
        }
    }
    monkeypatch.setenv("JANUSMASK_AGENT_WORKROOT", str(tmp_path / "agentwork"))
    monkeypatch.setenv("JANUSMASK_TASK_ID", "FAILCLOSED_TEST")
    (tmp_path / "agentwork").mkdir(parents=True, exist_ok=True)
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)

    proc = orch.spawn_agent('claude', 'x', cfg)
    assert proc is not None
    assert jail_calls == [None]


def test_selfheal_fails_closed_when_proxy_attempted_failed_and_binary_present(monkeypatch, tmp_path):
    """
    (c) test_selfheal_fails_closed_when_proxy_attempted_failed_and_binary_present:
    set dae._SELFHEAL_DBUS_PROXY_FAILED=True (raising=False), sandbox->True, shutil.which->'/usr/bin/xdg-dbus-proxy';
    assert _contain_selfheal(cmd, env, work_dir, state_dir, config, agent='') RAISES.
    """
    monkeypatch.setattr(dae, "_SELFHEAL_DBUS_PROXY_FAILED", True, raising=False)
    monkeypatch.setattr(agent_jail, "sandbox_enabled", lambda config: True)

    original_which = shutil.which
    def mock_which(binary):
        if binary == "xdg-dbus-proxy":
            return "/usr/bin/xdg-dbus-proxy"
        if binary == "bwrap":
            return "/usr/bin/bwrap"
        return original_which(binary)
    monkeypatch.setattr(shutil, "which", mock_which)

    cmd = ["echo", "hello"]
    env = {}
    work_dir = tmp_path / "work"
    state_dir = tmp_path / "state"
    config = {}

    with pytest.raises(RuntimeError) as excinfo:
        dae._contain_selfheal(cmd, env, work_dir, state_dir, config, agent='')
    assert "filtered D-Bus proxy failed to start" in str(excinfo.value)


def test_selfheal_graceful_when_daemon_never_started(monkeypatch, tmp_path):
    """
    (d) test_selfheal_graceful_when_daemon_never_started:
    do NOT set the flag (delattr or monkeypatch to None/absent), sandbox->True, which present;
    assert _contain_selfheal does NOT raise and returns a jail-wrapped cmd (build_jail_argv reached).
    """
    if hasattr(dae, "_SELFHEAL_DBUS_PROXY_FAILED"):
        monkeypatch.delattr(dae, "_SELFHEAL_DBUS_PROXY_FAILED")
    if hasattr(dae, "_SELFHEAL_DBUS_SOCKET"):
        monkeypatch.setattr(dae, "_SELFHEAL_DBUS_SOCKET", None)

    monkeypatch.setattr(agent_jail, "sandbox_enabled", lambda config: True)

    original_which = shutil.which
    def mock_which(binary):
        if binary == "xdg-dbus-proxy":
            return "/usr/bin/xdg-dbus-proxy"
        if binary == "bwrap":
            return "/usr/bin/bwrap"
        return original_which(binary)
    monkeypatch.setattr(shutil, "which", mock_which)

    jail_calls = []
    def spy_build_jail_argv(cmd, **kwargs):
        jail_calls.append(kwargs.get("dbus_proxy_socket"))
        return ["jailed"] + list(cmd)
    monkeypatch.setattr(agent_jail, "build_jail_argv", spy_build_jail_argv)

    cmd = ["echo", "hello"]
    env = {}
    work_dir = tmp_path / "work"
    state_dir = tmp_path / "state"
    config = {}

    res_cmd = dae._contain_selfheal(cmd, env, work_dir, state_dir, config, agent='')
    assert res_cmd[0] == "jailed"
    assert jail_calls == [None]
