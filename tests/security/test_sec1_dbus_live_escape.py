"""Live escape-regression oracle for the D-Bus filtering proxy.

This module tests that:
1) A filtered D-Bus proxy allows keyring access (org.freedesktop.secrets) but blocks the systemd user manager (org.freedesktop.systemd1) StartTransientUnit containment escape.
2) An unfiltered D-Bus proxy (without `--filter` and without `--talk` grants) allows systemd1 access. This acts as a negative control to ensure that systemd1 is indeed running and reachable.
"""

import os
import shutil
import subprocess
import tempfile
import time
from contextlib import contextmanager
import pytest

from harness.dbus_proxy import build_proxy_argv, proxied_session_bus


def _session_bus_path():
    addr = os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")
    if addr.startswith("unix:path="):
        p = addr.split("unix:path=", 1)[1].split(",", 1)[0]
        if os.path.exists(p):
            return p
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    if xdg:
        p = os.path.join(xdg, "bus")
        if os.path.exists(p):
            return p
    return None


_has_xdg = shutil.which("xdg-dbus-proxy") is not None
_has_gdbus = shutil.which("gdbus") is not None
_has_bus = _session_bus_path() is not None

# SKIP GUARD at module scope: skip the whole module unless
# shutil.which("xdg-dbus-proxy") and shutil.which("gdbus") and a live session bus
# (DBUS_SESSION_BUS_ADDRESS unix:path that exists, or $XDG_RUNTIME_DIR/bus exists).
pytestmark = pytest.mark.skipif(
    not (_has_xdg and _has_gdbus and _has_bus),
    reason="Missing live session bus, xdg-dbus-proxy, or gdbus CLI"
)


def run_gdbus(socket_path: str, dest: str, objpath: str, method: str, *args: str) -> str:
    """Helper run_gdbus(socket, dest, objpath, method, *args) -> (combined_output_text)."""
    gdbus_bin = shutil.which("gdbus")
    if not gdbus_bin:
        raise RuntimeError("gdbus binary not found")

    cmd = [
        gdbus_bin,
        "call",
        "--session",
        "--dest", dest,
        "--object-path", objpath,
        "--method", method
    ]
    cmd.extend(args)

    env = os.environ.copy()
    env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={socket_path}"

    res = subprocess.run(
        cmd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=10.0
    )
    return res.stdout + "\n" + res.stderr


@contextmanager
def unfiltered_session_bus(real_bus_path: str, proxy_socket_path: str):
    """Context manager to spawn an unfiltered xdg-dbus-proxy instance."""
    proxy_bin = shutil.which("xdg-dbus-proxy")
    if not proxy_bin:
        raise RuntimeError("xdg-dbus-proxy binary not found")

    argv = [proxy_bin, f"unix:path={real_bus_path}", proxy_socket_path]
    proc = subprocess.Popen(argv)
    try:
        deadline = time.monotonic() + 10.0
        while not os.path.exists(proxy_socket_path):
            if proc.poll() is not None:
                raise RuntimeError(
                    f"unfiltered xdg-dbus-proxy exited early with code {proc.returncode}"
                )
            if time.monotonic() >= deadline:
                raise TimeoutError("unfiltered xdg-dbus-proxy did not create socket in time")
            time.sleep(0.05)
        yield proxy_socket_path
    finally:
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5.0)
        except Exception:
            pass


def test_filtered_proxy_allows_secrets_blocks_systemd1():
    """Assert secrets is reachable, and systemd1 (Ping and StartTransientUnit) is blocked."""
    with proxied_session_bus() as filtered_socket:
        # A) secrets reachable: gdbus Ping on org.freedesktop.secrets succeeds (no error string).
        # We perform a Ping through the proxy to org.freedesktop.secrets
        out_secrets = run_gdbus(
            filtered_socket,
            "org.freedesktop.secrets",
            "/org/freedesktop/secrets",
            "org.freedesktop.DBus.Peer.Ping"
        )
        # The keyring (Secret Service) Ping must traverse the FILTERED proxy and
        # succeed -- this is the agy OAuth-refresh path; a denial here would mean
        # the filter is too tight and would break auth.
        for err in ("ServiceUnknown", "AccessDenied", "access denied", "Error:"):
            assert err not in out_secrets, (
                "secrets keyring must be reachable through the filtered proxy, "
                "got: %r" % (out_secrets,)
            )

        # B) systemd1 DENIED: gdbus Ping AND a StartTransientUnit call on org.freedesktop.systemd1
        # both return an error containing "ServiceUnknown" (or access denied/AccessDenied).
        out_systemd_ping = run_gdbus(
            filtered_socket,
            "org.freedesktop.systemd1",
            "/org/freedesktop/systemd1",
            "org.freedesktop.DBus.Peer.Ping"
        )
        assert any(err in out_systemd_ping for err in ["ServiceUnknown", "AccessDenied", "access denied"])

        out_systemd_escape = run_gdbus(
            filtered_socket,
            "org.freedesktop.systemd1",
            "/org/freedesktop/systemd1",
            "org.freedesktop.systemd1.Manager.StartTransientUnit",
            "jmtest-escape.service", "fail", "a(sv)", "0", "a(sa(sv))", "0"
        )
        assert any(err in out_systemd_escape for err in ["ServiceUnknown", "AccessDenied", "access denied"])


def test_unfiltered_proxy_allows_systemd1():
    """Assert systemd1 Ping over unfiltered socket succeeds (no ServiceUnknown/AccessDenied)."""
    real = _session_bus_path()
    assert real is not None, "Real session bus path must be resolved"

    tmpdir = tempfile.mkdtemp(prefix="dbus-unfiltered-")
    sock = os.path.join(tmpdir, "unfiltered.sock")
    try:
        with unfiltered_session_bus(real, sock):
            out_systemd_ping = run_gdbus(
                sock,
                "org.freedesktop.systemd1",
                "/org/freedesktop/systemd1",
                "org.freedesktop.DBus.Peer.Ping"
            )
            for err in ("ServiceUnknown", "AccessDenied", "access denied", "Error:"):
                assert err not in out_systemd_ping, (
                    "negative control: systemd1 MUST be reachable through an "
                    "UNFILTERED proxy (proves the filtered denial is non-vacuous), "
                    "got: %r" % (out_systemd_ping,)
                )
    finally:
        try:
            if os.path.exists(sock):
                os.remove(sock)
        except OSError:
            pass
        try:
            shutil.rmtree(tmpdir)
        except OSError:
            pass
