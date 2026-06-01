"""SEC-1c-SPAWN oracle: the agent synthesis spawn threads the filtered D-Bus proxy.

Wraps the AUTH-CRITICAL synthesis spawn in spawn_agent in a contextlib.ExitStack
that enters ``harness.dbus_proxy.proxied_session_bus`` (FAIL-OPEN) and passes the
resulting filtered socket into ``build_jail_argv`` via ``dbus_proxy_socket=``.

RED on HEAD: spawn_agent never enters proxied_session_bus, build_jail_argv
receives ``dbus_proxy_socket=None`` (the param defaults to None), and the
returned claude proc carries no ``_dbus_stack`` attribute.

GREEN after the fix:
  - both the agy (gemini) and claude spawns enter proxied_session_bus and pass a
    non-None ``dbus_proxy_socket`` into build_jail_argv;
  - the AGY path (synchronous) reaps the proxy by the time spawn_agent returns,
    on BOTH the normal return AND the TimeoutExpired branch;
  - the CLAUDE path (detached) attaches the live ExitStack to the proc, and
    ``kill_agent`` closes it when the agent is reaped (both the normal reap path
    AND the proc.poll()-already-exited early-return path).

Deterministic: NO real agent / bwrap / xdg-dbus-proxy is spawned. The proxy CM,
build_jail_argv, subprocess.Popen and sandbox_enabled are all monkeypatched.
"""
from __future__ import annotations

import signal
import subprocess
from pathlib import Path

import pytest

import harness.orchestrator as orch


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
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


class FakePopenBase:
    """Minimal Popen stand-in. Subclasses set _is_timeout / detached behaviour."""

    _is_timeout = False
    _poll_value = None  # claude path: alive (None) so kill_agent runs the reap

    def __init__(self, cmd, **kwargs):
        self.cmd = cmd
        self.kwargs = kwargs
        self.pid = 4321
        self.returncode = 0
        self.kill_called = False
        self.wait_called = False

    # agy path
    def communicate(self, input=None, timeout=None):
        if self._is_timeout:
            raise subprocess.TimeoutExpired(cmd=self.cmd, timeout=timeout)
        return ("```python\n# Placeholder\n```", "")

    def kill(self):
        self.kill_called = True

    def wait(self, timeout=None):
        self.wait_called = True
        return 0

    # kill_agent path
    def poll(self):
        return self._poll_value

    def terminate(self):
        pass


@pytest.fixture
def patched(monkeypatch, tmp_path):
    """Common monkeypatches: force sandbox on, spy build_jail_argv, fake the proxy
    CM, neuter stream threads / pid recording / hook assertion."""
    captured = {"jail_calls": [], "proxy_cms": []}

    # spawn_agent does ``from harness import agent_jail`` lazily, so patch the
    # source module (orch has no module-level ``agent_jail`` attribute).
    import harness.agent_jail as agent_jail

    # Force the sandboxed path so the proxy is entered.
    monkeypatch.setattr(agent_jail, "sandbox_enabled", lambda config: True)

    # Spy build_jail_argv: record dbus_proxy_socket, return a trivial argv so no
    # real bwrap is constructed.
    def fake_build_jail_argv(cmd, **kw):
        captured["jail_calls"].append(kw.get("dbus_proxy_socket", "MISSING"))
        return list(cmd)

    monkeypatch.setattr(agent_jail, "build_jail_argv", fake_build_jail_argv)

    # Fake proxied_session_bus on the dbus_proxy module (spawn_agent imports it
    # lazily from harness.dbus_proxy).
    import harness.dbus_proxy as dbus_proxy

    def fake_proxied_session_bus(*a, **k):
        cm = FakeProxyCM()
        captured["proxy_cms"].append(cm)
        return cm

    monkeypatch.setattr(dbus_proxy, "proxied_session_bus", fake_proxied_session_bus)

    # No real OS plumbing.
    monkeypatch.setattr(orch, "start_stream_threads", lambda *a, **k: ())
    monkeypatch.setattr(orch.control_gate, "record_agent_pid", lambda *a, **k: None)
    # claude path: skip the fail-closed settings-file assertion (no real file).
    monkeypatch.setattr(orch, "_assert_claude_hook_config", lambda cmd: None)

    monkeypatch.setenv("JANUSMASK_AGENT_WORKROOT", str(tmp_path / "agentwork"))
    monkeypatch.setenv("JANUSMASK_TASK_ID", "SEC1C_SPAWN_TEST")

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    captured["state_dir"] = state_dir
    return captured


def _agy_config(state_dir):
    return {
        "state_dir": str(state_dir),
        "agent_sandbox": {"bwrap": True},
        "agents": {"gemini": {"command": "agy", "args": ["-p", "--sandbox"]}},
    }


def _claude_config(state_dir):
    return {
        "state_dir": str(state_dir),
        "agent_sandbox": {"bwrap": True},
        "agents": {"claude": {"command": "claude", "args": ["-p", "--settings", "x"]}},
    }


# --------------------------------------------------------------------------- #
# AGY path (synchronous) — proxy entered, socket threaded, reaped on return
# --------------------------------------------------------------------------- #
def test_agy_normal_threads_proxy_socket_and_reaps(patched, monkeypatch):
    class P(FakePopenBase):
        _is_timeout = False

    monkeypatch.setattr(orch.subprocess, "Popen", P)
    cfg = _agy_config(patched["state_dir"])

    proc = orch.spawn_agent("gemini", "dummy", cfg, round_number=1)

    # Proxy CM was created + entered, and the filtered socket reached build_jail_argv.
    assert len(patched["proxy_cms"]) == 1, "proxied_session_bus was never entered"
    cm = patched["proxy_cms"][0]
    assert cm.entered, "proxy CM __enter__ never ran"
    assert patched["jail_calls"] == [cm.sock], (
        f"build_jail_argv did not receive the filtered proxy socket: {patched['jail_calls']}"
    )
    # Synchronous reap: the proxy is closed by the time spawn_agent returns.
    assert cm.exited, "AGY normal path: proxy CM __exit__ must run before spawn_agent returns"
    assert proc is not None


def test_agy_timeout_branch_still_reaps_proxy(patched, monkeypatch):
    # Cover the :425 timeout return path.
    monkeypatch.setattr(orch.os, "getpgid", lambda pid: 12345)
    monkeypatch.setattr(orch.os, "killpg", lambda pgid, sig: None)

    class P(FakePopenBase):
        _is_timeout = True

    monkeypatch.setattr(orch.subprocess, "Popen", P)
    cfg = _agy_config(patched["state_dir"])

    proc = orch.spawn_agent("gemini", "dummy", cfg, round_number=1)

    assert len(patched["proxy_cms"]) == 1
    cm = patched["proxy_cms"][0]
    assert cm.entered
    assert patched["jail_calls"] == [cm.sock]
    # Even on the timeout return, the synchronous proxy must be reaped.
    assert cm.exited, "AGY timeout path: proxy CM __exit__ must run before spawn_agent returns"
    assert proc.kill_called and proc.wait_called  # timeout-reap unchanged


# --------------------------------------------------------------------------- #
# CLAUDE path (detached) — proxy outlives spawn_agent, closed by kill_agent
# --------------------------------------------------------------------------- #
def test_claude_attaches_stack_and_kill_agent_closes_it(patched, monkeypatch):
    class P(FakePopenBase):
        _poll_value = None  # alive -> kill_agent runs the full reap path

    monkeypatch.setattr(orch.subprocess, "Popen", P)
    # Neuter the real kill plumbing in kill_agent.
    monkeypatch.setattr(orch.os, "getpgid", lambda pid: 12345)
    monkeypatch.setattr(orch.os, "killpg", lambda pgid, sig: None)
    cfg = _claude_config(patched["state_dir"])

    proc = orch.spawn_agent("claude", "dummy", cfg, round_number=1)

    # Socket threaded for the claude spawn too.
    assert len(patched["proxy_cms"]) == 1
    cm = patched["proxy_cms"][0]
    assert cm.entered
    assert patched["jail_calls"] == [cm.sock]

    # Detached: the proxy must NOT be reaped yet (agent still running OAuth).
    assert not cm.exited, "CLAUDE path: proxy must outlive spawn_agent (not reaped on return)"
    # The live ExitStack is attached to the proc for the reaper.
    assert getattr(proc, "_dbus_stack", None) is not None, "claude proc missing _dbus_stack"

    # kill_agent reaps the agent AND closes the attached proxy stack.
    orch.kill_agent(proc, "claude", reason="handoff")
    assert cm.exited, "kill_agent must close the attached proxy ExitStack"


def test_claude_kill_agent_early_return_still_closes_stack(patched, monkeypatch):
    # kill_agent early-returns when proc.poll() is already set; the stack must
    # still be closed on that path.
    class P(FakePopenBase):
        _poll_value = 0  # already exited -> kill_agent early-returns

    monkeypatch.setattr(orch.subprocess, "Popen", P)
    cfg = _claude_config(patched["state_dir"])

    proc = orch.spawn_agent("claude", "dummy", cfg, round_number=1)
    assert getattr(proc, "_dbus_stack", None) is not None
    cm = patched["proxy_cms"][0]
    assert not cm.exited

    orch.kill_agent(proc, "claude", reason="handoff")
    assert cm.exited, "kill_agent early-return (proc already exited) must still close the proxy stack"
