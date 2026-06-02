"""Adversarial test for PHASE_ABSTRACT_SOCKET_WARN:
At daemon start, if the host DBUS_SESSION_BUS_ADDRESS contains "unix:abstract=",
emit a WARNING telemetry row (event "abstract_bus_residual_warning").
It must be a NO-OP when the host bus is a path socket.
"""

from __future__ import annotations

import os
import pytest
from pathlib import Path

import harness.autowork_daemon as dae
import harness.agent_jail as agent_jail
import harness.dbus_proxy as dbus_proxy

_SENTINEL_SOCK = "/tmp/sec1_once_failflag-sentinel/proxy.sock"


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
    """Ensure the module globals start unset for each test; tolerant of them not existing yet on HEAD."""
    if hasattr(dae, "_SELFHEAL_DBUS_SOCKET"):
        monkeypatch.setattr(dae, "_SELFHEAL_DBUS_SOCKET", None, raising=False)
    if hasattr(dae, "_SELFHEAL_DBUS_STACK"):
        monkeypatch.setattr(dae, "_SELFHEAL_DBUS_STACK", None, raising=False)
    monkeypatch.setattr(dae, "_SELFHEAL_DBUS_PROXY_FAILED", False, raising=False)


def test_abstract_socket_warn_positive(tmp_path, monkeypatch):
    _reset_singleton(monkeypatch)

    # Monkeypatch agent_jail.sandbox_enabled -> True
    monkeypatch.setattr(agent_jail, "sandbox_enabled", lambda config: True)

    # Recording _FakeProxyCM context manager for proxied_session_bus
    record = {"proxy_enters": 0, "proxy_exits": 0}
    fake_cm = _FakeProxyCM(record)
    monkeypatch.setattr(dbus_proxy, "proxied_session_bus", fake_cm)
    monkeypatch.setattr(dae, "proxied_session_bus", fake_cm, raising=False)

    # Stub _install_sigterm_handler, _iteration
    monkeypatch.setattr(dae, "_install_sigterm_handler", lambda: None)
    monkeypatch.setattr(dae, "_iteration", lambda *a, **k: None)

    # CAPTURE telemetry
    emitted = []
    def fake_emit_telemetry(state_dir, task_id, event, detail=""):
        emitted.append((event, detail))
    monkeypatch.setattr(dae, "_emit_telemetry", fake_emit_telemetry)

    # Use monkeypatch.setenv for DBUS_SESSION_BUS_ADDRESS so it auto-restores
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:abstract=/tmp/dbus-AbCdEf")

    # Make state_dir
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True)

    # Run main --once
    rc = dae.main(['--state-dir', str(state_dir), '--once'])
    assert rc == 0

    # Assert that an emitted event == 'abstract_bus_residual_warning' is present
    events = [event for event, detail in emitted]
    assert "abstract_bus_residual_warning" in events, (
        f"Expected abstract_bus_residual_warning event, but only got events: {events}"
    )


def test_abstract_socket_warn_negative(tmp_path, monkeypatch):
    _reset_singleton(monkeypatch)

    # Monkeypatch agent_jail.sandbox_enabled -> True
    monkeypatch.setattr(agent_jail, "sandbox_enabled", lambda config: True)

    # Recording _FakeProxyCM context manager for proxied_session_bus
    record = {"proxy_enters": 0, "proxy_exits": 0}
    fake_cm = _FakeProxyCM(record)
    monkeypatch.setattr(dbus_proxy, "proxied_session_bus", fake_cm)
    monkeypatch.setattr(dae, "proxied_session_bus", fake_cm, raising=False)

    # Stub _install_sigterm_handler, _iteration
    monkeypatch.setattr(dae, "_install_sigterm_handler", lambda: None)
    monkeypatch.setattr(dae, "_iteration", lambda *a, **k: None)

    # CAPTURE telemetry
    emitted = []
    def fake_emit_telemetry(state_dir, task_id, event, detail=""):
        emitted.append((event, detail))
    monkeypatch.setattr(dae, "_emit_telemetry", fake_emit_telemetry)

    # Use monkeypatch.setenv for DBUS_SESSION_BUS_ADDRESS
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1000/bus")

    # Make state_dir
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True)

    # Run main --once
    rc = dae.main(['--state-dir', str(state_dir), '--once'])
    assert rc == 0

    # Assert NO 'abstract_bus_residual_warning' event was emitted
    events = [event for event, detail in emitted]
    assert "abstract_bus_residual_warning" not in events, (
        f"Expected NO abstract_bus_residual_warning event, but got: {events}"
    )
