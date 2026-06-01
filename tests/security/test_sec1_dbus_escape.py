"""SEC-1a oracle: D-Bus filtering proxy primitive (harness/dbus_proxy.py).

RED-on-HEAD detector: this file imports ``harness.dbus_proxy`` at module
scope. On HEAD that module does NOT exist, so collection fails with an
ImportError and EVERY test below errors out -- a genuine RED. After the
agent authors ``harness/dbus_proxy.py`` with the required public API, the
import resolves and the deterministic config-level assertions go GREEN.

The SPINE of this oracle is the deterministic, environment-independent set
of assertions on ``build_proxy_argv`` (no live D-Bus, no subprocess) -- it
proves the proxy is configured to BLOCK the user's systemd user manager
(StartTransientUnit = containment escape) while PRESERVING the keyring
(Secret Service / org.freedesktop.secrets) needed for agy's OAuth.

The live integration smoke (actually spawning xdg-dbus-proxy via the
context manager) is fully GUARDED: it is skipped cleanly whenever a real
session bus or the xdg-dbus-proxy binary is unavailable, so it never
flakes the worker's verification run.
"""

import os
import shutil
import time

import pytest

# RED-on-HEAD: harness.dbus_proxy does not exist yet -> ImportError at
# collection time. This is the ONLY reason this oracle is RED on HEAD.
from harness.dbus_proxy import build_proxy_argv, proxied_session_bus


# --------------------------------------------------------------------------
# Deterministic spine: build_proxy_argv (no env, no subprocess, no D-Bus)
# --------------------------------------------------------------------------

REAL = "/run/user/1000/bus"
SOCK = "/tmp/janusmask-sec1a-proxy.sock"


def test_build_proxy_argv_invokes_xdg_dbus_proxy():
    """argv must invoke the xdg-dbus-proxy binary as argv[0]."""
    argv = build_proxy_argv(REAL, SOCK)
    assert isinstance(argv, list)
    assert all(isinstance(a, str) for a in argv)
    assert argv, "argv must be non-empty"
    assert "xdg-dbus-proxy" in argv[0], (
        "argv[0] must be the xdg-dbus-proxy binary, got %r" % (argv[0],)
    )


def test_build_proxy_argv_enables_filtering():
    """--filter MUST be present: without it the proxy is a pass-through and
    every bus method (including StartTransientUnit) is reachable."""
    argv = build_proxy_argv(REAL, SOCK)
    assert "--filter" in argv, "the proxy must run in --filter mode"


def test_build_proxy_argv_grants_secrets_talk():
    """The keyring (Secret Service) MUST be talkable -- agy's OAuth refresh
    needs org.freedesktop.secrets through the proxied bus."""
    argv = build_proxy_argv(REAL, SOCK)
    assert "--talk=org.freedesktop.secrets" in argv, (
        "keyring talk grant (--talk=org.freedesktop.secrets) is required"
    )


def test_build_proxy_argv_blocks_systemd1_talk():
    """The user's systemd manager MUST NOT be talkable -- a talk grant to
    org.freedesktop.systemd1 reopens the StartTransientUnit containment
    escape. No argv token may grant talk/own to systemd1."""
    argv = build_proxy_argv(REAL, SOCK)
    for tok in argv:
        assert not tok.startswith("--talk=org.freedesktop.systemd1"), (
            "must NOT grant talk to systemd1 (StartTransientUnit escape): %r" % (tok,)
        )
        assert not tok.startswith("--own=org.freedesktop.systemd1"), (
            "must NOT grant own to systemd1: %r" % (tok,)
        )
        assert tok != "--talk=org.freedesktop.systemd1"


def test_build_proxy_argv_no_broad_wildcard_talk():
    """No broad wildcard talk grant: --talk=* or a freedesktop.* wildcard
    would transitively re-grant systemd1 and defeat the filter."""
    argv = build_proxy_argv(REAL, SOCK)
    for tok in argv:
        assert tok != "--talk=*", "broad --talk=* wildcard forbidden"
        assert tok != "--own=*", "broad --own=* wildcard forbidden"
        if tok.startswith("--talk="):
            name = tok.split("=", 1)[1]
            assert name == "org.freedesktop.secrets", (
                "only org.freedesktop.secrets may be talkable; got %r" % (name,)
            )
            assert "*" not in name, "wildcard in talk name forbidden: %r" % (tok,)
        if tok.startswith("--own="):
            name = tok.split("=", 1)[1]
            assert "*" not in name, "wildcard in own name forbidden: %r" % (tok,)


def test_build_proxy_argv_references_both_paths():
    """argv must reference both the real bus path (as the proxied address)
    and the listen socket path."""
    argv = build_proxy_argv(REAL, SOCK)
    joined = "\n".join(argv)
    assert REAL in joined, "real_bus_path must appear in argv (proxied address)"
    assert SOCK in joined, "proxy_socket_path must appear in argv (listen socket)"


def test_build_proxy_argv_address_form():
    """The real bus must be referenced as a D-Bus unix address (the proxy's
    first positional ADDRESS arg), not bare -- it should appear as a token
    that carries unix:path= or equals the bus path positionally."""
    argv = build_proxy_argv(REAL, SOCK)
    # At least one token references the real bus as a unix path address.
    has_addr = any(("unix:path=" + REAL) == t or t == REAL for t in argv)
    assert has_addr, (
        "real bus must be referenced as a unix:path= address or positional path"
    )


# --------------------------------------------------------------------------
# Live integration smoke (fully guarded / skippable)
# --------------------------------------------------------------------------

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


_LIVE_AVAILABLE = (
    shutil.which("xdg-dbus-proxy") is not None and _session_bus_path() is not None
)


@pytest.mark.skipif(
    not _LIVE_AVAILABLE,
    reason="no live session bus or xdg-dbus-proxy unavailable; spine assertions suffice",
)
def test_proxied_session_bus_spawns_and_reaps():
    """Smoke: the context manager spawns the proxy, the filtered socket
    exists inside the block, and the proxy process is reaped on exit."""
    seen_socket = None
    with proxied_session_bus() as sock_path:
        assert isinstance(sock_path, str) and sock_path
        # The filtered listen socket must exist inside the block.
        deadline = time.time() + 5.0
        while not os.path.exists(sock_path) and time.time() < deadline:
            time.sleep(0.05)
        assert os.path.exists(sock_path), (
            "filtered proxy socket must exist inside the with-block"
        )
        seen_socket = sock_path
    # After exit the socket must be cleaned up (no leak).
    assert seen_socket is not None
    # Give the finally a beat; the socket should be removed.
    time.sleep(0.1)
    assert not os.path.exists(seen_socket), (
        "proxy socket must be removed on context exit (no leak)"
    )
