"""SEC-1 FAIL-CLOSED (EASY3) oracle: the three verification spawn sites must
FAIL CLOSED when the filtered D-Bus proxy cannot start but the proxy binary IS
present.

The three sites (all on their sandboxed path) currently catch any exception
from ``proxied_session_bus()`` and fall back to ``dbus_proxy_socket=None`` ->
the jailed subprocess then dials the REAL (unfiltered) host session bus, which
re-opens the systemd1 / StartTransientUnit containment escape. This oracle
asserts the post-fix contract:

  * sandbox ENABLED + ``shutil.which("xdg-dbus-proxy")`` truthy +
    ``proxied_session_bus()`` raises  ->  the function REFUSES: it raises a
    ``RuntimeError`` mentioning "filtered D-Bus proxy failed to start" and
    NEVER calls ``build_jail_argv`` with ``dbus_proxy_socket=None`` (i.e. never
    dispatches a subprocess on the real bus).

  * sandbox ENABLED + ``shutil.which("xdg-dbus-proxy")`` -> None (binary
    ABSENT) + ``proxied_session_bus()`` raises  ->  GRACEFUL DEGRADE preserved:
    the function does NOT raise, and ``build_jail_argv`` is called with
    ``dbus_proxy_socket=None`` (binary genuinely unavailable -> best effort).

The three wrapped functions are:
  * ``harness.embedded_test_runner.run_embedded_tests`` (TWO build_jail_argv
    sites: collect + run).
  * ``harness.sandbox_smoke.smoke_import`` (ONE site).
  * ``harness.narrow_fuzz.validation._exec_module`` (ONE site).

RED on HEAD: on HEAD the except branch unconditionally sets ``_dbus_sock=None``
regardless of ``which`` -> NO RuntimeError is raised and ``build_jail_argv`` is
reached with ``dbus_proxy_socket=None``. Both the ``pytest.raises`` and the
``None not in captured`` assertions therefore FAIL (genuine assert failures,
not import/collection errors).

Determinism: never spawns a real ``xdg-dbus-proxy`` or ``bwrap``.
``proxied_session_bus`` is replaced with a CM whose ``__enter__`` raises;
``build_jail_argv`` is replaced with a recorder; ``subprocess.run`` /
``subprocess.Popen`` are mocked; ``sandbox_enabled`` is forced True; and
``shutil.which`` is monkeypatched to control binary presence. Mirrors the idiom
of ``tests/security/test_sec1_failclosed.py`` and
``tests/adversarial/test_sec1c_easy3_proxy_wrap.py``.
"""
from __future__ import annotations

import shutil
import unittest.mock as mock

import pytest


# --------------------------------------------------------------------------
# Shared fakes / helpers
# --------------------------------------------------------------------------

class _FailingProxyCM:
    """A proxied_session_bus() return value whose __enter__ raises -- mimics a
    proxy that resolves on PATH but fails to actually spawn/listen."""

    def __enter__(self):
        raise RuntimeError(
            "Fake D-Bus proxy failure: xdg-dbus-proxy failed to start."
        )

    def __exit__(self, *exc):
        return False


def _install_failing_proxy(monkeypatch):
    """Patch harness.dbus_proxy.proxied_session_bus to a CM that raises on
    enter. The target modules lazily ``from harness.dbus_proxy import
    proxied_session_bus`` in-body, so patching the attribute on the module
    object is sufficient."""
    import harness.dbus_proxy as dbus_proxy

    monkeypatch.setattr(
        dbus_proxy, "proxied_session_bus", lambda *a, **k: _FailingProxyCM()
    )


def _install_build_jail_recorder(monkeypatch):
    """Replace harness.agent_jail.build_jail_argv with a recorder that captures
    the dbus_proxy_socket kwarg and returns a benign argv."""
    import harness.agent_jail as agent_jail

    captured = []

    def _recorder(cmd, *, repo_root, work_dir, state_dir, dbus_proxy_socket=None, **kwargs):
        captured.append(dbus_proxy_socket)
        return ["/usr/bin/bwrap", "--ro-bind", "/", "/"] + list(cmd)

    monkeypatch.setattr(agent_jail, "build_jail_argv", _recorder)
    return captured


def _force_sandbox(monkeypatch):
    monkeypatch.setattr(
        "harness.orchestrator.load_config",
        lambda: {"agent_sandbox": {"bwrap": True}},
    )
    monkeypatch.setattr("harness.agent_jail.sandbox_enabled", lambda cfg: True)


def _mock_which(monkeypatch, *, proxy_present: bool):
    """Force shutil.which('xdg-dbus-proxy') to a path (present) or None
    (absent); keep bwrap resolvable; delegate everything else to the real
    which."""
    original_which = shutil.which

    def fake(binary, *a, **k):
        if binary == "xdg-dbus-proxy":
            return "/usr/bin/xdg-dbus-proxy" if proxy_present else None
        if binary == "bwrap":
            return "/usr/bin/bwrap"
        return original_which(binary, *a, **k)

    monkeypatch.setattr(shutil, "which", fake)


def _fake_run_factory(calls):
    def fake_run(argv, *args, **kwargs):
        calls.append(argv)
        proc = mock.MagicMock()
        proc.returncode = 0
        proc.stdout = ""
        proc.stderr = ""
        return proc
    return fake_run


class _FakeFuzzProc:
    """Popen stand-in for narrow_fuzz: emits a 'ready' handshake then EOF."""

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


# ==========================================================================
# 1. embedded_test_runner.run_embedded_tests
# ==========================================================================

def test_embedded_runner_fails_closed_when_proxy_raises_and_binary_present(monkeypatch):
    from harness import embedded_test_runner

    _install_failing_proxy(monkeypatch)
    captured = _install_build_jail_recorder(monkeypatch)
    _force_sandbox(monkeypatch)
    _mock_which(monkeypatch, proxy_present=True)

    run_calls = []
    monkeypatch.setattr(
        "harness.embedded_test_runner.subprocess.run", _fake_run_factory(run_calls)
    )

    src = "def test_dummy():\n    pass\n"
    with pytest.raises(RuntimeError) as excinfo:
        embedded_test_runner.run_embedded_tests("dummy_module", src)
    assert "filtered D-Bus proxy failed to start" in str(excinfo.value)
    # MUST NOT have dispatched a subprocess on the real (unfiltered) bus.
    assert None not in captured, (
        "fail-OPEN detected: build_jail_argv was called with "
        f"dbus_proxy_socket=None (captured={captured!r}); refused-spawn expected"
    )
    assert run_calls == [], "no jailed subprocess may be dispatched on refusal"


def test_embedded_runner_graceful_when_proxy_binary_absent(monkeypatch):
    """Negative control: binary genuinely absent -> graceful degrade preserved
    (no raise, dbus_proxy_socket=None passed through)."""
    from harness import embedded_test_runner

    _install_failing_proxy(monkeypatch)
    captured = _install_build_jail_recorder(monkeypatch)
    _force_sandbox(monkeypatch)
    _mock_which(monkeypatch, proxy_present=False)

    run_calls = []
    monkeypatch.setattr(
        "harness.embedded_test_runner.subprocess.run", _fake_run_factory(run_calls)
    )

    src = "def test_dummy():\n    pass\n"
    # Must not raise.
    embedded_test_runner.run_embedded_tests("dummy_module", src)
    assert captured, "build_jail_argv must still be reached on the graceful path"
    assert all(s is None for s in captured), (
        f"binary-absent graceful path must pass dbus_proxy_socket=None, got {captured!r}"
    )


# ==========================================================================
# 2. sandbox_smoke.smoke_import
# ==========================================================================

def test_smoke_import_fails_closed_when_proxy_raises_and_binary_present(monkeypatch):
    from harness import sandbox_smoke

    _install_failing_proxy(monkeypatch)
    captured = _install_build_jail_recorder(monkeypatch)
    _force_sandbox(monkeypatch)
    _mock_which(monkeypatch, proxy_present=True)

    run_calls = []
    monkeypatch.setattr(
        "harness.sandbox_smoke.subprocess.run", _fake_run_factory(run_calls)
    )

    with pytest.raises(RuntimeError) as excinfo:
        sandbox_smoke.smoke_import("test_mymod_sec1fc", "x = 1")
    assert "filtered D-Bus proxy failed to start" in str(excinfo.value)
    assert None not in captured, (
        "fail-OPEN detected: build_jail_argv called with dbus_proxy_socket=None "
        f"(captured={captured!r})"
    )
    assert run_calls == [], "no jailed subprocess may be dispatched on refusal"


def test_smoke_import_graceful_when_proxy_binary_absent(monkeypatch):
    from harness import sandbox_smoke

    _install_failing_proxy(monkeypatch)
    captured = _install_build_jail_recorder(monkeypatch)
    _force_sandbox(monkeypatch)
    _mock_which(monkeypatch, proxy_present=False)

    run_calls = []
    monkeypatch.setattr(
        "harness.sandbox_smoke.subprocess.run", _fake_run_factory(run_calls)
    )

    sandbox_smoke.smoke_import("test_mymod_sec1fc", "x = 1")
    assert captured, "build_jail_argv must still be reached on the graceful path"
    assert all(s is None for s in captured), (
        f"binary-absent graceful path must pass dbus_proxy_socket=None, got {captured!r}"
    )


# ==========================================================================
# 3. narrow_fuzz.validation._exec_module
# ==========================================================================

def test_exec_module_fails_closed_when_proxy_raises_and_binary_present(monkeypatch):
    from harness.narrow_fuzz import validation

    _install_failing_proxy(monkeypatch)
    captured = _install_build_jail_recorder(monkeypatch)
    _force_sandbox(monkeypatch)
    _mock_which(monkeypatch, proxy_present=True)

    popen_calls = []

    def fake_popen(argv, *args, **kwargs):
        popen_calls.append(argv)
        return _FakeFuzzProc()

    import subprocess as _subprocess
    monkeypatch.setattr(_subprocess, "Popen", fake_popen)

    with pytest.raises(RuntimeError) as excinfo:
        validation._exec_module(
            "cand_mod", "def validate_x(x: int) -> bool:\n    return True\n"
        )
    assert "filtered D-Bus proxy failed to start" in str(excinfo.value)
    assert None not in captured, (
        "fail-OPEN detected: build_jail_argv called with dbus_proxy_socket=None "
        f"(captured={captured!r})"
    )
    assert popen_calls == [], "no jailed subprocess may be dispatched on refusal"


def test_exec_module_graceful_when_proxy_binary_absent(monkeypatch):
    from harness.narrow_fuzz import validation

    _install_failing_proxy(monkeypatch)
    captured = _install_build_jail_recorder(monkeypatch)
    _force_sandbox(monkeypatch)
    _mock_which(monkeypatch, proxy_present=False)

    popen_calls = []

    def fake_popen(argv, *args, **kwargs):
        popen_calls.append(argv)
        return _FakeFuzzProc()

    import subprocess as _subprocess
    monkeypatch.setattr(_subprocess, "Popen", fake_popen)

    validation._exec_module(
        "cand_mod", "def validate_x(x: int) -> bool:\n    return True\n"
    )
    assert captured, "build_jail_argv must still be reached on the graceful path"
    assert all(s is None for s in captured), (
        f"binary-absent graceful path must pass dbus_proxy_socket=None, got {captured!r}"
    )
