"""Adversarial oracle for SEC1 (DBUS_SESSION_BUS_ADDRESS override).

Test that build_jail_argv overrides DBUS_SESSION_BUS_ADDRESS inside the jail
when dbus_proxy_socket is provided, pointing it to the bound filtering proxy.
"""

from __future__ import annotations

import os
import shutil
from harness.agent_jail import build_jail_argv


def test_dbusaddr_override_proxy_mode(tmp_path, monkeypatch):
    """Test PROXY mode: DBUS_SESSION_BUS_ADDRESS is overridden in jail."""
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    (home_dir / ".nvm").mkdir()
    (home_dir / ".gemini").mkdir()
    (home_dir / ".claude").mkdir()

    repo_root = tmp_path / "repo"
    work_dir = tmp_path / "work"
    state_dir = tmp_path / "state"
    repo_root.mkdir()
    work_dir.mkdir()
    state_dir.mkdir()

    # Mock XDG_RUNTIME_DIR on disk
    mock_xdg = tmp_path / "run_user_mock"
    mock_xdg.mkdir()

    # Fake bus and keyring files/dirs
    real_bus = mock_xdg / "bus"
    real_bus.touch()
    keyring = mock_xdg / "keyring"
    keyring.mkdir()

    monkeypatch.setenv("XDG_RUNTIME_DIR", str(mock_xdg))
    monkeypatch.setattr(shutil, "which", lambda cmd: "/usr/bin/bwrap" if cmd == "bwrap" else None)

    # Set sentinel DBUS_SESSION_BUS_ADDRESS on host
    sentinel = "unix:abstract=/tmp/host-bus-SHOULD-NOT-APPEAR"
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", sentinel)

    # Proxy socket path
    proxy_socket = tmp_path / "proxy.sock"
    proxy_socket.touch()

    argv = build_jail_argv(
        cmd=["python", "-c", "print(1)"],
        repo_root=repo_root,
        work_dir=work_dir,
        state_dir=state_dir,
        home=home_dir,
        dbus_proxy_socket=str(proxy_socket),
    )

    # Parse argv for --setenv triples (token == "--setenv" -> next two are name, value)
    setenv_triples = []
    for i, tok in enumerate(argv):
        if tok == "--setenv" and i + 2 < len(argv):
            setenv_triples.append((tok, argv[i + 1], argv[i + 2]))

    expected_bus_path = os.path.join(str(mock_xdg), "bus")
    expected_value = "unix:path=" + expected_bus_path

    # Assert ("DBUS_SESSION_BUS_ADDRESS", "unix:path=<xdg>/bus") is present
    has_expected_override = False
    for _, name, val in setenv_triples:
        if name == "DBUS_SESSION_BUS_ADDRESS" and val == expected_value:
            has_expected_override = True
            break

    assert has_expected_override, (
        f"Expected override ('DBUS_SESSION_BUS_ADDRESS', '{expected_value}') not found in triples: {setenv_triples}"
    )

    # Assert the sentinel does not appear anywhere in argv
    for tok in argv:
        assert sentinel not in tok, f"Sentinel host DBUS address leaked into argv token: {tok}"


def test_dbusaddr_override_default_mode(tmp_path, monkeypatch):
    """Test DEFAULT mode: no proxy socket, DBUS_SESSION_BUS_ADDRESS is not overridden."""
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    (home_dir / ".nvm").mkdir()
    (home_dir / ".gemini").mkdir()
    (home_dir / ".claude").mkdir()

    repo_root = tmp_path / "repo"
    work_dir = tmp_path / "work"
    state_dir = tmp_path / "state"
    repo_root.mkdir()
    work_dir.mkdir()
    state_dir.mkdir()

    # Mock XDG_RUNTIME_DIR on disk
    mock_xdg = tmp_path / "run_user_mock"
    mock_xdg.mkdir()

    # Fake bus and keyring files/dirs
    real_bus = mock_xdg / "bus"
    real_bus.touch()
    keyring = mock_xdg / "keyring"
    keyring.mkdir()

    monkeypatch.setenv("XDG_RUNTIME_DIR", str(mock_xdg))
    monkeypatch.setattr(shutil, "which", lambda cmd: "/usr/bin/bwrap" if cmd == "bwrap" else None)

    # Set sentinel DBUS_SESSION_BUS_ADDRESS on host
    sentinel = "unix:abstract=/tmp/host-bus-SHOULD-NOT-APPEAR"
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", sentinel)

    argv = build_jail_argv(
        cmd=["python", "-c", "print(1)"],
        repo_root=repo_root,
        work_dir=work_dir,
        state_dir=state_dir,
        home=home_dir,
    )

    # Parse argv for --setenv triples
    setenv_triples = []
    for i, tok in enumerate(argv):
        if tok == "--setenv" and i + 2 < len(argv):
            setenv_triples.append((tok, argv[i + 1], argv[i + 2]))

    # Assert no --setenv override for DBUS_SESSION_BUS_ADDRESS is emitted
    for _, name, val in setenv_triples:
        assert name != "DBUS_SESSION_BUS_ADDRESS", (
            f"Should not override DBUS_SESSION_BUS_ADDRESS in default mode, but got: {val}"
        )
