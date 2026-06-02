"""Adversarial test for BINARY_ABSENT_REFUSE (REV22 §2b / CR-8).

When the host D-Bus session bus is ACTIVE (DBUS_SESSION_BUS_ADDRESS set) but
``xdg-dbus-proxy`` is ABSENT (shutil.which -> None), the jail degrades to
``dbus_proxy_socket=None`` and mounts the REAL host session bus unjailed
(agent_jail.py:287 region) -- a systemd1/D-Bus escape that survives even when
sandbox_enabled() is True. With full_stop gone, the daemon-start path
(run_daemon AND main --once) MUST refuse to run unattended (raise RuntimeError)
unless the operator opts in via JANUSMASK_ALLOW_HOSTBUS=1.

These tests exercise the REAL daemon-start hooks (the same ones that carry the
PHASE_ABSTRACT_SOCKET_WARN block); they mirror test_abstract_socket_warn.py for
the invocation pattern (stub _install_sigterm_handler/_iteration/_emit_telemetry,
fake proxied_session_bus, monkeypatch the bus env).
"""

from __future__ import annotations

import os
import pytest
from pathlib import Path

import harness.autowork_daemon as dae
import harness.agent_jail as agent_jail
import harness.dbus_proxy as dbus_proxy


_SENTINEL_SOCK = "/tmp/binary_absent_refuse-sentinel/proxy.sock"


class _FakeProxyCM:
    """Recording context manager standing in for proxied_session_bus.
    Yields a sentinel socket; no process is spawned."""

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
    if hasattr(dae, "_SELFHEAL_DBUS_SOCKET"):
        monkeypatch.setattr(dae, "_SELFHEAL_DBUS_SOCKET", None, raising=False)
    if hasattr(dae, "_SELFHEAL_DBUS_STACK"):
        monkeypatch.setattr(dae, "_SELFHEAL_DBUS_STACK", None, raising=False)
    monkeypatch.setattr(dae, "_SELFHEAL_DBUS_PROXY_FAILED", False, raising=False)


def _common_stubs(monkeypatch):
    _reset_singleton(monkeypatch)
    monkeypatch.setattr(agent_jail, "sandbox_enabled", lambda config: True)
    record = {"proxy_enters": 0, "proxy_exits": 0}
    fake_cm = _FakeProxyCM(record)
    monkeypatch.setattr(dbus_proxy, "proxied_session_bus", fake_cm)
    monkeypatch.setattr(dae, "proxied_session_bus", fake_cm, raising=False)
    monkeypatch.setattr(dae, "_install_sigterm_handler", lambda: None)
    monkeypatch.setattr(dae, "_emit_telemetry", lambda *a, **k: None)

    # run_daemon resets _shutdown_requested=False at the top and then loops; make a
    # single iteration return a clean result and request shutdown so the poll loop
    # exits after exactly one pass (no infinite loop, no sleeps). main(--once) calls
    # _iteration once outside the loop, so the same stub serves both paths.
    def _one_shot_iteration(*a, **k):
        dae._shutdown_requested = True
        return {"would_launch": [], "free_slots": 0, "cap": 0,
                "paused": False, "extracts": 0, "plan_kickoffs": 0}
    monkeypatch.setattr(dae, "_iteration", _one_shot_iteration)
    # Neutralize the rest of the single-pass loop body so it never touches the FS.
    monkeypatch.setattr(dae, "_maybe_push_and_rebase_pin", lambda *a, **k: None)
    monkeypatch.setattr(dae, "_check_inactivity_watchdog", lambda *a, **k: None)
    monkeypatch.setattr(dae, "_has_active_rebuild_job", lambda *a, **k: False)
    monkeypatch.setattr(dae, "_drain_running", lambda *a, **k: None)
    monkeypatch.setattr(dae, "_resume_or_kill_orphaned_workers", lambda *a, **k: None)
    return record


def _fake_which_absent(name):
    """shutil.which stub: xdg-dbus-proxy is ABSENT, everything else present."""
    if name == "xdg-dbus-proxy":
        return None
    return "/usr/bin/" + name


def _fake_which_present(name):
    return "/usr/bin/" + name


# ---------- main(--once) path ----------

def test_once_refuses_when_proxy_absent_and_host_bus_active(tmp_path, monkeypatch):
    _common_stubs(monkeypatch)
    monkeypatch.setattr("shutil.which", _fake_which_absent)
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1000/bus")
    monkeypatch.delenv("JANUSMASK_ALLOW_HOSTBUS", raising=False)
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True)
    with pytest.raises(RuntimeError):
        dae.main(["--state-dir", str(state_dir), "--once"])


def test_once_no_refuse_when_proxy_present(tmp_path, monkeypatch):
    _common_stubs(monkeypatch)
    monkeypatch.setattr("shutil.which", _fake_which_present)
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1000/bus")
    monkeypatch.delenv("JANUSMASK_ALLOW_HOSTBUS", raising=False)
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True)
    rc = dae.main(["--state-dir", str(state_dir), "--once"])
    assert rc == 0


def test_once_no_refuse_when_opt_in_set(tmp_path, monkeypatch):
    _common_stubs(monkeypatch)
    monkeypatch.setattr("shutil.which", _fake_which_absent)
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1000/bus")
    monkeypatch.setenv("JANUSMASK_ALLOW_HOSTBUS", "1")
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True)
    rc = dae.main(["--state-dir", str(state_dir), "--once"])
    assert rc == 0


def test_once_no_refuse_when_no_host_bus(tmp_path, monkeypatch):
    _common_stubs(monkeypatch)
    monkeypatch.setattr("shutil.which", _fake_which_absent)
    monkeypatch.delenv("DBUS_SESSION_BUS_ADDRESS", raising=False)
    monkeypatch.delenv("JANUSMASK_ALLOW_HOSTBUS", raising=False)
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True)
    rc = dae.main(["--state-dir", str(state_dir), "--once"])
    assert rc == 0


# ---------- run_daemon path ----------

def test_run_daemon_refuses_when_proxy_absent_and_host_bus_active(tmp_path, monkeypatch):
    _common_stubs(monkeypatch)
    monkeypatch.setattr("shutil.which", _fake_which_absent)
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:abstract=/tmp/dbus-AbCdEf")
    monkeypatch.delenv("JANUSMASK_ALLOW_HOSTBUS", raising=False)
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True)
    with pytest.raises(RuntimeError):
        dae.run_daemon(Path.cwd(), state_dir, {})


def test_run_daemon_no_refuse_when_proxy_present(tmp_path, monkeypatch):
    _common_stubs(monkeypatch)
    monkeypatch.setattr("shutil.which", _fake_which_present)
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1000/bus")
    monkeypatch.delenv("JANUSMASK_ALLOW_HOSTBUS", raising=False)
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True)
    rc = dae.run_daemon(Path.cwd(), state_dir, {})
    assert rc == 0
