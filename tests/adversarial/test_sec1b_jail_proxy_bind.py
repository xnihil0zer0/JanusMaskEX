"""Adversarial oracle for SEC1B (dbus proxy socket bind).

Test that build_jail_argv supports binding an optional dbus proxy socket path
at <xdg>/bus instead of the real bus when dbus_proxy_socket is provided.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from harness.agent_jail import build_jail_argv


def _pairs(argv: list[str], flag: str) -> list[tuple[str, str]]:
    """All (src, dst) pairs following occurrences of ``flag`` in argv."""
    out = []
    for i, tok in enumerate(argv):
        if tok == flag and i + 2 < len(argv):
            out.append((argv[i + 1], argv[i + 2]))
    return out


def test_proxy_mode(tmp_path, monkeypatch):
    """Test PROXY mode: call with dbus_proxy_socket=<tmp>/proxy.sock asserting

    argv has --bind proxy.sock <xdg>/bus and NOT --bind realbus realbus, keyring still bound.
    """
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

    rw_binds = _pairs(argv, "--bind")

    # Assert proxy socket bound to in-jail bus path
    assert (str(proxy_socket), str(real_bus)) in rw_binds, f"Proxy socket not bound to {real_bus}: {argv}"
    # Assert real bus not bound
    assert (str(real_bus), str(real_bus)) not in rw_binds, f"Real bus was bound, but proxy mode is active: {argv}"
    # Assert keyring still bound
    assert (str(keyring), str(keyring)) in rw_binds, f"Keyring was not bound: {argv}"


def test_default_mode(tmp_path, monkeypatch):
    """Test DEFAULT mode: no param, asserts real bus bound, no proxy ref."""
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

    argv = build_jail_argv(
        cmd=["python", "-c", "print(1)"],
        repo_root=repo_root,
        work_dir=work_dir,
        state_dir=state_dir,
        home=home_dir,
    )

    rw_binds = _pairs(argv, "--bind")

    # Assert real bus bound in default mode
    assert (str(real_bus), str(real_bus)) in rw_binds, f"Real bus not bound in default mode: {argv}"
    # Assert keyring still bound
    assert (str(keyring), str(keyring)) in rw_binds, f"Keyring not bound in default mode: {argv}"
    # Assert no proxy ref
    argv_str = " ".join(argv)
    assert "proxy.sock" not in argv_str, f"Proxy socket reference found in default mode: {argv}"
