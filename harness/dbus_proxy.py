"""D-Bus filtering proxy primitive (SEC-1a).

This module provides a thin wrapper around ``xdg-dbus-proxy`` that exposes a
*filtered* view of the user's session bus. The filter is configured so that a
jailed agent can still reach the keyring / Secret Service
(``org.freedesktop.secrets``, needed for agy's OAuth refresh) but CANNOT reach
the user's systemd user manager (``org.freedesktop.systemd1``), whose
``StartTransientUnit`` method is a containment-escape vector.

It is a standalone primitive: importing this module spawns nothing and requires
no live bus. Side effects (spawning the proxy, creating sockets) happen only
when :func:`proxied_session_bus` is actually entered. Wiring the filtered
socket into the jail is a separate, later task (SEC-1b/1c).

Only the standard library is used.
"""
from __future__ import annotations
import os
import shutil
import subprocess
import tempfile
import time
from contextlib import contextmanager
from typing import Iterator, Optional

def build_proxy_argv(real_bus_path: str, proxy_socket_path: str) -> list[str]:
    """Assemble the ``xdg-dbus-proxy`` command line for a filtered session bus.

    This is a pure function: it spawns nothing and touches no filesystem; it
    only assembles strings.

    The positional grammar of ``xdg-dbus-proxy`` is::

        <binary> <ADDRESS> <SOCKET_PATH> [OPTIONS...]

    where ``<ADDRESS>`` is the real bus to proxy (``unix:path=`` + the real bus
    path) and ``<SOCKET_PATH>`` is the filtered listen socket to create.

    The options enable filtering (``--filter`` -- without it the proxy is a
    transparent pass-through and ``StartTransientUnit`` is reachable) and grant
    talk access to the keyring (``--talk=org.freedesktop.secrets``). No grant of
    any kind is added for ``org.freedesktop.systemd1`` and no broad wildcard
    grant is added, so the user's systemd manager stays unreachable.
    """
    binary = shutil.which('xdg-dbus-proxy') or '/usr/bin/xdg-dbus-proxy'
    return [binary, 'unix:path=' + real_bus_path, proxy_socket_path, '--filter', '--talk=org.freedesktop.secrets']

@contextmanager
def proxied_session_bus(real_bus_path: Optional[str]=None, runtime_dir: Optional[str]=None) -> Iterator[str]:
    """Spawn a filtered ``xdg-dbus-proxy`` and yield its listen socket path.

    On enter the real session bus is resolved (``real_bus_path`` if given, else
    ``$DBUS_SESSION_BUS_ADDRESS`` parsed as ``unix:path=...``, else
    ``<runtime_dir or $XDG_RUNTIME_DIR>/bus``), a fresh temp socket is created,
    the proxy is spawned and polled until the socket appears, and the socket
    path is yielded. On exit -- whether normal or exceptional -- the proxy is
    always terminated and reaped and the socket + temp dir are removed, so
    neither the process nor the socket leaks.
    """
    real = _resolve_real_bus(real_bus_path, runtime_dir)
    tmpdir = tempfile.mkdtemp(prefix='dbus-proxy-')
    sock = os.path.join(tmpdir, 'proxy.sock')
    argv = build_proxy_argv(real, sock)
    proc = subprocess.Popen(argv)
    try:
        deadline = time.monotonic() + 10.0
        while not os.path.exists(sock):
            if proc.poll() is not None:
                raise RuntimeError(f'xdg-dbus-proxy exited early with code {proc.returncode} (argv={argv!r})')
            if time.monotonic() >= deadline:
                raise TimeoutError(f'xdg-dbus-proxy did not create socket {sock!r} in time')
            time.sleep(0.05)
        yield sock
    finally:
        _terminate_and_reap(proc)
        try:
            os.remove(sock)
        except OSError:
            pass
        try:
            shutil.rmtree(tmpdir)
        except OSError:
            pass

def _resolve_real_bus(real_bus_path: Optional[str], runtime_dir: Optional[str]) -> str:
    """Resolve the path to the real session bus socket, or raise ``RuntimeError``."""
    if real_bus_path:
        return real_bus_path
    addr = os.environ.get('DBUS_SESSION_BUS_ADDRESS')
    if addr and addr.startswith('unix:path='):
        path = addr[len('unix:path='):]
        path = path.split(',', 1)[0]
        if path:
            return path
    base = runtime_dir or os.environ.get('XDG_RUNTIME_DIR')
    if base:
        return os.path.join(base, 'bus')
    raise RuntimeError('could not resolve the real session bus: pass real_bus_path, set $DBUS_SESSION_BUS_ADDRESS, or set $XDG_RUNTIME_DIR')

def _terminate_and_reap(proc: 'subprocess.Popen[bytes]') -> None:
    """Terminate and reap the proxy process, swallowing teardown errors."""
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=5.0)
                except Exception:
                    pass
    except Exception:
        pass