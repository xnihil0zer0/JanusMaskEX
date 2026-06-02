"""Adversarial/Security test for PHASE_SEC1_ONCE_FAILFLAG:
Verify that the D-Bus proxy failure flag (_SELFHEAL_DBUS_PROXY_FAILED) is correctly set
under main --once.
"""

from __future__ import annotations

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

    def __init__(self, record, raise_on_enter=False):
        self._record = record
        self._raise_on_enter = raise_on_enter

    def __call__(self, *args, **kwargs):
        return self

    def __enter__(self):
        self._record["proxy_enters"] += 1
        if self._raise_on_enter:
            raise RuntimeError("Fake proxy spawn failure")
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


def test_once_sets_failed_flag_when_proxy_raises(tmp_path, monkeypatch):
    _reset_singleton(monkeypatch)

    # Monkeypatch agent_jail.sandbox_enabled -> True
    monkeypatch.setattr(agent_jail, "sandbox_enabled", lambda config: True)

    # Recording _FakeProxyCM context manager for proxied_session_bus (raises RuntimeError)
    record = {"proxy_enters": 0, "proxy_exits": 0}
    fake_cm = _FakeProxyCM(record, raise_on_enter=True)
    monkeypatch.setattr(dbus_proxy, "proxied_session_bus", fake_cm)
    monkeypatch.setattr(dae, "proxied_session_bus", fake_cm, raising=False)

    # Stub _install_sigterm_handler, _emit_telemetry to no-op
    monkeypatch.setattr(dae, "_install_sigterm_handler", lambda: None)
    monkeypatch.setattr(dae, "_emit_telemetry", lambda *a, **k: None)

    # Stub dae._iteration to a lambda
    monkeypatch.setattr(dae, "_iteration", lambda *a, **k: None)

    # Make state_dir
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True)

    # Run main --once
    rc = dae.main(['--state-dir', str(state_dir), '--once'])
    assert rc == 0

    # ASSERT getattr(dae, '_SELFHEAL_DBUS_PROXY_FAILED', False) is True
    assert getattr(dae, "_SELFHEAL_DBUS_PROXY_FAILED", False) is True, (
        "Expected _SELFHEAL_DBUS_PROXY_FAILED to be True on proxy spawn failure"
    )


def test_once_failed_flag_false_on_successful_proxy(tmp_path, monkeypatch):
    _reset_singleton(monkeypatch)

    # Monkeypatch agent_jail.sandbox_enabled -> True
    monkeypatch.setattr(agent_jail, "sandbox_enabled", lambda config: True)

    # Recording _FakeProxyCM context manager for proxied_session_bus (succeeds)
    record = {"proxy_enters": 0, "proxy_exits": 0}
    fake_cm = _FakeProxyCM(record, raise_on_enter=False)
    monkeypatch.setattr(dbus_proxy, "proxied_session_bus", fake_cm)
    monkeypatch.setattr(dae, "proxied_session_bus", fake_cm, raising=False)

    # Stub _install_sigterm_handler, _emit_telemetry to no-op
    monkeypatch.setattr(dae, "_install_sigterm_handler", lambda: None)
    monkeypatch.setattr(dae, "_emit_telemetry", lambda *a, **k: None)

    # Stub dae._iteration to a lambda
    monkeypatch.setattr(dae, "_iteration", lambda *a, **k: None)

    # Make state_dir
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True)

    # Run main --once
    rc = dae.main(['--state-dir', str(state_dir), '--once'])
    assert rc == 0

    # Assertions
    assert record["proxy_enters"] == 1
    assert record["proxy_exits"] == 1
    assert getattr(dae, "_SELFHEAL_DBUS_PROXY_FAILED", False) is False, (
        "Expected _SELFHEAL_DBUS_PROXY_FAILED to be False on successful proxy spawn"
    )
