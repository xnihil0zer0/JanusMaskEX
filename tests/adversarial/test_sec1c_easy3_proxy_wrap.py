"""SEC-1c-EASY3 oracle: the three verification spawn sites route their jailed
subprocess through the FILTERED D-Bus proxy when sandboxing is enabled.

The three wrapped functions are:
  * ``harness.embedded_test_runner.run_embedded_tests`` (TWO build_jail_argv
    sites: collect + run -- both must receive the proxy socket).
  * ``harness.sandbox_smoke.smoke_import`` (ONE site).
  * ``harness.narrow_fuzz.validation._exec_module`` (ONE site).

RED on HEAD: on HEAD none of these functions enter ``proxied_session_bus`` and
they pass ``dbus_proxy_socket=None`` (the param defaults to None) -- so the
fake proxy CM is never entered and the captured ``dbus_proxy_socket`` is None,
failing the assertions. The failures are real ``assert`` failures, not
import/collection errors.

GREEN after the wrap: each function enters ``proxied_session_bus`` on its
sandboxed path and threads the yielded sentinel socket into every
``build_jail_argv`` call at that site.

Determinism: this oracle NEVER spawns a real ``xdg-dbus-proxy`` or ``bwrap``.
``harness.dbus_proxy.proxied_session_bus`` is replaced with a fake context
manager; ``harness.agent_jail.build_jail_argv`` is replaced with a recorder
that captures the ``dbus_proxy_socket`` kwarg and returns a benign argv; the
subprocess spawn (``subprocess.run`` / ``subprocess.Popen``) is mocked so no
real process is launched. ``sandbox_enabled`` is forced True via an injected
config and a direct patch; ``shutil.which`` is NOT relied upon (build_jail_argv
is replaced wholesale).
"""
from __future__ import annotations

import unittest.mock as mock

import pytest


_SENTINEL_SOCK = "/tmp/sec1c-easy3-sentinel/proxy.sock"


class _FakeProxyCM:
    """Records entry and yields a sentinel socket path; reaps nothing."""

    def __init__(self, recorder):
        self._recorder = recorder

    def __enter__(self):
        self._recorder["entered"] += 1
        return _SENTINEL_SOCK

    def __exit__(self, *exc):
        self._recorder["exited"] += 1
        return False


def _install_fake_proxy(monkeypatch):
    """Patch ``harness.dbus_proxy.proxied_session_bus`` with a recording fake.

    The target modules lazily ``from harness.dbus_proxy import
    proxied_session_bus`` inside the function body, so patching the attribute
    on ``harness.dbus_proxy`` is sufficient -- the import resolves to the patch
    at call time.
    """
    import harness.dbus_proxy as dbus_proxy

    rec = {"entered": 0, "exited": 0}

    def _factory(*args, **kwargs):
        return _FakeProxyCM(rec)

    monkeypatch.setattr(dbus_proxy, "proxied_session_bus", _factory)
    return rec


def _install_build_jail_recorder(monkeypatch):
    """Replace ``harness.agent_jail.build_jail_argv`` with a recorder.

    Captures the ``dbus_proxy_socket`` kwarg of every call and returns a benign
    bwrap-shaped argv so downstream code that inspects argv[0]/structure does
    not crash. The target modules import build_jail_argv lazily from
    ``harness.agent_jail`` (or call ``agent_jail.build_jail_argv``), so patching
    the attribute on ``harness.agent_jail`` covers every site.
    """
    import harness.agent_jail as agent_jail

    captured = []

    def _recorder(cmd, *, repo_root, work_dir, state_dir, dbus_proxy_socket=None, **kwargs):
        captured.append(dbus_proxy_socket)
        inner = list(cmd)
        return ["/usr/bin/bwrap", "--ro-bind", "/", "/"] + inner

    monkeypatch.setattr(agent_jail, "build_jail_argv", _recorder)
    return captured


# --------------------------------------------------------------------------
# 1. embedded_test_runner.run_embedded_tests -- TWO sites (collect + run)
# --------------------------------------------------------------------------

def test_embedded_runner_threads_proxy_socket_into_both_sites(monkeypatch):
    from harness import embedded_test_runner

    rec = _install_fake_proxy(monkeypatch)
    captured = _install_build_jail_recorder(monkeypatch)

    # Force the sandboxed path: sandbox_enabled True via injected config.
    monkeypatch.setattr(
        "harness.orchestrator.load_config",
        lambda: {"agent_sandbox": {"bwrap": True}},
    )
    monkeypatch.setattr(
        "harness.agent_jail.sandbox_enabled", lambda cfg: True
    )

    run_calls = []

    def fake_run(argv, *args, **kwargs):
        run_calls.append(argv)
        proc = mock.MagicMock()
        proc.returncode = 0
        proc.stdout = ""
        proc.stderr = ""
        return proc

    monkeypatch.setattr(
        "harness.embedded_test_runner.subprocess.run", fake_run
    )

    src = "def test_dummy():\n    pass\n"
    embedded_test_runner.run_embedded_tests("dummy_module", src)

    assert rec["entered"] >= 1, "proxied_session_bus was never entered"
    # collect + run => two build_jail_argv calls, each must get the sentinel.
    assert len(captured) == 2, f"expected 2 build_jail_argv calls, got {captured!r}"
    for sock in captured:
        assert sock == _SENTINEL_SOCK, (
            f"build_jail_argv received dbus_proxy_socket={sock!r}, "
            f"expected the proxy sentinel {_SENTINEL_SOCK!r}"
        )


def test_embedded_runner_no_proxy_when_sandbox_disabled(monkeypatch):
    """Regression: the non-sandboxed path NEVER enters the proxy."""
    from harness import embedded_test_runner

    rec = _install_fake_proxy(monkeypatch)
    captured = _install_build_jail_recorder(monkeypatch)

    monkeypatch.setattr(
        "harness.orchestrator.load_config",
        lambda: {"agent_sandbox": {"bwrap": False}},
    )
    monkeypatch.setattr(
        "harness.agent_jail.sandbox_enabled", lambda cfg: False
    )

    run_calls = []

    def fake_run(argv, *args, **kwargs):
        run_calls.append(argv)
        proc = mock.MagicMock()
        proc.returncode = 0
        proc.stdout = ""
        proc.stderr = ""
        return proc

    monkeypatch.setattr(
        "harness.embedded_test_runner.subprocess.run", fake_run
    )

    src = "def test_dummy():\n    pass\n"
    embedded_test_runner.run_embedded_tests("dummy_module", src)

    assert rec["entered"] == 0, "proxy must NOT be entered on the non-sandboxed path"
    assert captured == [], "build_jail_argv must not be called when sandbox disabled"


# --------------------------------------------------------------------------
# 2. sandbox_smoke.smoke_import -- ONE site
# --------------------------------------------------------------------------

def test_smoke_import_threads_proxy_socket(monkeypatch):
    from harness import sandbox_smoke

    rec = _install_fake_proxy(monkeypatch)
    captured = _install_build_jail_recorder(monkeypatch)

    monkeypatch.setattr(
        "harness.orchestrator.load_config",
        lambda: {"agent_sandbox": {"bwrap": True}},
    )
    monkeypatch.setattr(
        "harness.agent_jail.sandbox_enabled", lambda cfg: True
    )

    run_calls = []

    def fake_run(argv, *args, **kwargs):
        run_calls.append(argv)
        proc = mock.MagicMock()
        proc.returncode = 0
        proc.stdout = ""
        proc.stderr = ""
        return proc

    monkeypatch.setattr(
        "harness.sandbox_smoke.subprocess.run", fake_run
    )

    sandbox_smoke.smoke_import("test_mymod_sec1c", "x = 1")

    assert rec["entered"] >= 1, "proxied_session_bus was never entered"
    assert len(captured) == 1, f"expected 1 build_jail_argv call, got {captured!r}"
    assert captured[0] == _SENTINEL_SOCK, (
        f"build_jail_argv received dbus_proxy_socket={captured[0]!r}, "
        f"expected the proxy sentinel {_SENTINEL_SOCK!r}"
    )


# --------------------------------------------------------------------------
# 3. narrow_fuzz.validation._exec_module -- ONE site
# --------------------------------------------------------------------------

def test_exec_module_threads_proxy_socket(monkeypatch):
    from harness.narrow_fuzz import validation

    rec = _install_fake_proxy(monkeypatch)
    captured = _install_build_jail_recorder(monkeypatch)

    monkeypatch.setattr(
        "harness.orchestrator.load_config",
        lambda: {"agent_sandbox": {"bwrap": True}},
    )
    monkeypatch.setattr(
        "harness.agent_jail.sandbox_enabled", lambda cfg: True
    )

    # Fake Popen: a "ready" handshake then EOF so _exec_module returns a
    # namespace without spawning anything real.
    class _FakeProc:
        def __init__(self):
            self.stdin = mock.MagicMock()
            self._lines = iter(['{"status": "ready", "functions": {}}\n'])

        @property
        def stdout(self):
            return self

        def readline(self):
            try:
                return next(self._lines)
            except StopIteration:
                return ""

        def terminate(self):
            pass

        def wait(self, timeout=None):
            return 0

        def kill(self):
            pass

    def fake_popen(argv, *args, **kwargs):
        fake_popen.calls.append(argv)
        return _FakeProc()

    fake_popen.calls = []
    # _exec_module lazily ``import subprocess`` in-body (a local rebind), so
    # patch the stdlib module object directly -- the lazy import resolves to it.
    import subprocess as _subprocess
    monkeypatch.setattr(_subprocess, "Popen", fake_popen)

    ns = validation._exec_module("cand_mod", "def validate_x(x: int) -> bool:\n    return True\n")

    assert rec["entered"] >= 1, "proxied_session_bus was never entered"
    assert len(captured) == 1, f"expected 1 build_jail_argv call, got {captured!r}"
    assert captured[0] == _SENTINEL_SOCK, (
        f"build_jail_argv received dbus_proxy_socket={captured[0]!r}, "
        f"expected the proxy sentinel {_SENTINEL_SOCK!r}"
    )
