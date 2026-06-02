"""Adversarial test for PHASE_DAEMON_ONCE_PROXY:
Verify that the D-Bus proxy daemon-lifetime singleton is initialized and reaped on main --once.
"""

from __future__ import annotations

import pytest
from pathlib import Path

import harness.autowork_daemon as dae
import harness.agent_jail as agent_jail
import harness.dbus_proxy as dbus_proxy

_SENTINEL_SOCK = "/tmp/sec1c-daemon-sentinel/proxy.sock"


class _FakeProxyCM:
    """Recording context manager standing in for proxied_session_bus.
    Yields a sentinel socket; counts enters/exits so a leaked/early-reaped proxy
    is detectable. No process is spawned."""

    def __init__(self, record):
        self._record = record

    def __call__(self, *args, **kwargs):
        return self

    def __enter__(self):
        self._record["proxy_enters"] += 1
        return _SENTINEL_SOCK

    def __exit__(self, *exc):
        self._record["proxy_exits"] += 1
        return False


def _reset_singleton(monkeypatch):
    """Ensure the module global (once the feature exists) starts unset for each
    test; tolerant of it not existing yet on HEAD."""
    if hasattr(dae, "_SELFHEAL_DBUS_SOCKET"):
        monkeypatch.setattr(dae, "_SELFHEAL_DBUS_SOCKET", None, raising=False)
    if hasattr(dae, "_SELFHEAL_DBUS_STACK"):
        monkeypatch.setattr(dae, "_SELFHEAL_DBUS_STACK", None, raising=False)


def test_once_inits_and_reaps_proxy_when_sandbox_enabled(tmp_path, monkeypatch):
    _reset_singleton(monkeypatch)
    
    # Monkeypatch agent_jail.sandbox_enabled -> True
    monkeypatch.setattr(agent_jail, "sandbox_enabled", lambda config: True)
    
    # Recording _FakeProxyCM context manager for proxied_session_bus
    record = {"proxy_enters": 0, "proxy_exits": 0}
    fake_cm = _FakeProxyCM(record)
    monkeypatch.setattr(dbus_proxy, "proxied_session_bus", fake_cm)
    monkeypatch.setattr(dae, "proxied_session_bus", fake_cm, raising=False)
    
    # Stub _install_sigterm_handler, _emit_telemetry to no-op
    monkeypatch.setattr(dae, "_install_sigterm_handler", lambda: None)
    monkeypatch.setattr(dae, "_emit_telemetry", lambda *a, **k: None)
    
    # Stub dae._iteration to a lambda that snapshots the singleton socket
    captured = {}
    def fake_iteration(repo_root, state_dir, cap, dry_run=False, config=None):
        captured["live_socket"] = getattr(dae, "_SELFHEAL_DBUS_SOCKET", None)
    monkeypatch.setattr(dae, "_iteration", fake_iteration)
    
    # Call main with --once
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True)
    
    rc = dae.main(['--state-dir', str(state_dir), '--once'])
    assert rc == 0
    
    # Assertions
    assert record["proxy_enters"] == 1, "proxied_session_bus() must enter exactly once"
    assert captured.get("live_socket") == _SENTINEL_SOCK, "captured live socket during iteration must match sentinel"
    assert record["proxy_exits"] == 1, "proxied_session_bus() must exit exactly once"
    assert getattr(dae, "_SELFHEAL_DBUS_SOCKET", None) is None, "socket must be reset to None after main returns"


def test_once_no_proxy_when_sandbox_disabled(tmp_path, monkeypatch):
    _reset_singleton(monkeypatch)
    
    # Monkeypatch agent_jail.sandbox_enabled -> False
    monkeypatch.setattr(agent_jail, "sandbox_enabled", lambda config: False)
    
    # Recording _FakeProxyCM context manager for proxied_session_bus
    record = {"proxy_enters": 0, "proxy_exits": 0}
    fake_cm = _FakeProxyCM(record)
    monkeypatch.setattr(dbus_proxy, "proxied_session_bus", fake_cm)
    monkeypatch.setattr(dae, "proxied_session_bus", fake_cm, raising=False)
    
    # Stub _install_sigterm_handler, _emit_telemetry to no-op
    monkeypatch.setattr(dae, "_install_sigterm_handler", lambda: None)
    monkeypatch.setattr(dae, "_emit_telemetry", lambda *a, **k: None)
    
    # Stub dae._iteration to no-op
    monkeypatch.setattr(dae, "_iteration", lambda *a, **k: None)
    
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True)
    
    rc = dae.main(['--state-dir', str(state_dir), '--once'])
    assert rc == 0
    
    # Assertions
    assert record["proxy_enters"] == 0, "proxied_session_bus() must not enter when sandbox is disabled"
    assert getattr(dae, "_SELFHEAL_DBUS_SOCKET", None) is None, "socket must remain None"
