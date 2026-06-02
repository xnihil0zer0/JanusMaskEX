"""SEC-1c-DAEMON: daemon self-heal D-Bus proxy wrap (the LAST of 10 sites).

The daemon self-heal spawns (`_escalate_to_autobrief` / `_escalate_inactivity`)
are DETACHED fire-and-forget Popens reaped later via pidfiles, NOT a retained
Popen the caller waits on. A per-escalation `with proxied_session_bus()` scoped
at the caller would reap the filtered bus the instant the function returns --
BEFORE the detached self-heal agent does its keyring OAuth -> auth breaks. It
would also add a per-escalation proxy Popen that breaks the existing
Popen-count tests.

The correct design is a daemon-LIFETIME singleton: `run_daemon` opens ONE
`proxied_session_bus()` at startup (only when `agent_jail.sandbox_enabled`),
stores the yielded socket in a module-level global, and closes it on daemon
shutdown. `_contain_selfheal` (the single funnel both escalation sites call
before `build_jail_argv`) threads that global socket into `build_jail_argv` via
`dbus_proxy_socket=...`. Default None preserves current behavior, so the unit
tests (which never start the daemon -> socket stays None -> fail-open) add no
extra Popen and stay green.

This oracle is RED-first on HEAD (no startup proxy init, socket not threaded)
via REAL assertions (sentinel not propagated), NOT import errors. NO real agent,
daemon, bwrap, or xdg-dbus-proxy is ever launched -- everything is monkeypatched.

The module-level singleton is referenced via ``getattr(dae, "_SELFHEAL_DBUS_SOCKET", None)``
so the THREADING/BACKWARD-COMPAT tests do not import-error before the global
exists; they go red on the missing ``dbus_proxy_socket`` thread, which is the
real behavioral gap.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import harness.autowork_daemon as dae
import harness.orchestrator as orch
import harness.agent_jail as agent_jail
import harness.dbus_proxy as dbus_proxy
from harness.paths import PROJECT_ROOT


_SENTINEL_SOCK = "/tmp/sec1c-daemon-sentinel/proxy.sock"


# --------------------------------------------------------------------------- #
# shared helpers (mirror tests/adversarial/test_daemon_control_isolation_hooks.py)
# --------------------------------------------------------------------------- #
class _FakePopen:
    def __init__(self, cmd, **kwargs):
        self.cmd = cmd
        self.kwargs = kwargs
        self.pid = 424242
        self.returncode = None

    def poll(self):
        return None

    def wait(self, timeout=None):
        return 0


@pytest.fixture
def workroot(tmp_path, monkeypatch):
    root = tmp_path / "agentwork"
    monkeypatch.setenv("JANUSMASK_AGENT_WORKROOT", str(root))
    return root


def _patch_daemon_popen(monkeypatch, captured):
    """Record every dae.subprocess.Popen call. ``captured['popen_count']`` lets
    the backward-compat guard prove NO extra proxy Popen is spawned when the
    daemon is not started (socket None)."""
    captured.setdefault("popen_count", 0)

    class _P(_FakePopen):
        def __init__(self, cmd, **kwargs):
            super().__init__(cmd, **kwargs)
            captured["popen_count"] += 1
            captured["cwd"] = kwargs.get("cwd")
            captured["env"] = kwargs.get("env", {})
            captured["cmd"] = cmd

    monkeypatch.setattr(dae.subprocess, "Popen", _P)


def _spy_build_jail_argv(monkeypatch, captured):
    """Spy ``agent_jail.build_jail_argv`` AS SEEN BY the daemon module
    (``dae.agent_jail`` / ``harness.agent_jail`` are the same object). Record the
    ``dbus_proxy_socket`` kwarg without launching bwrap (return the inner cmd
    unchanged so the Popen still fires)."""
    real = agent_jail.build_jail_argv

    def _spy(cmd, **kwargs):
        captured["dbus_proxy_socket"] = kwargs.get("dbus_proxy_socket")
        captured["jail_called"] = True
        # Do NOT call the real bwrap-wrapping builder (no bwrap on CI / RED run);
        # return the inner cmd so the detached Popen still fires for the count.
        return list(cmd)

    monkeypatch.setattr(agent_jail, "build_jail_argv", _spy)


def _enable_sandbox(monkeypatch):
    """Force ``agent_jail.sandbox_enabled`` -> True for the module under test
    regardless of the toy config so the proxy-init / jail branch is exercised."""
    monkeypatch.setattr(agent_jail, "sandbox_enabled", lambda config: True)


def _disable_sandbox(monkeypatch):
    monkeypatch.setattr(agent_jail, "sandbox_enabled", lambda config: False)


class _FakeProxyCM:
    """Recording context manager standing in for ``proxied_session_bus``.
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
    """Ensure the module global (once the feature exists) starts unset for each
    test; tolerant of it not existing yet on HEAD."""
    if hasattr(dae, "_SELFHEAL_DBUS_SOCKET"):
        monkeypatch.setattr(dae, "_SELFHEAL_DBUS_SOCKET", None, raising=False)
    if hasattr(dae, "_SELFHEAL_DBUS_STACK"):
        monkeypatch.setattr(dae, "_SELFHEAL_DBUS_STACK", None, raising=False)


def _write_blocked_task(state_dir: Path, tid: str = "RB_T"):
    (state_dir / "tasks" / "blocked").mkdir(parents=True, exist_ok=True)
    (state_dir / "tasks" / "blocked" / f"{tid}.json").write_text(json.dumps(
        {"task_id": tid, "objective": "fix the thing",
         "files_touched": ["pkg/x.py"]}))
    return tid


def _is_outside_repo(p) -> bool:
    p = Path(p).resolve()
    try:
        p.relative_to(PROJECT_ROOT.resolve())
        return False
    except ValueError:
        return True


# --------------------------------------------------------------------------- #
# STARTUP — run_daemon opens ONE proxy at startup and stores its socket.
# run_daemon is driven to exit after startup by planting the full_stop sentinel
# (it breaks on the first loop check, AFTER startup proxy-init, BEFORE any real
# work). _iteration / orphan-sweep / drain are stubbed so nothing real runs.
# --------------------------------------------------------------------------- #
def test_startup_opens_singleton_proxy_and_stores_socket(tmp_path, monkeypatch):
    _reset_singleton(monkeypatch)
    _enable_sandbox(monkeypatch)
    record = {"proxy_enters": 0, "proxy_exits": 0}
    fake_cm = _FakeProxyCM(record)
    # Patch BOTH the source symbol and (if already imported) the daemon's view.
    monkeypatch.setattr(dbus_proxy, "proxied_session_bus", fake_cm)
    monkeypatch.setattr(dae, "proxied_session_bus", fake_cm, raising=False)

    state_dir = tmp_path / "state"
    (state_dir / "control" / "autowork").mkdir(parents=True)
    # full_stop sentinel -> run_daemon breaks on the first loop check, after the
    # startup proxy-init block.
    (state_dir / "control" / "autowork" / "full_stop").touch()

    captured_socket = {}

    # Keep run_daemon fast + side-effect free.
    monkeypatch.setattr(dae, "_install_sigterm_handler", lambda: None)
    monkeypatch.setattr(dae, "_resume_or_kill_orphaned_workers",
                        lambda *a, **k: None)
    monkeypatch.setattr(dae, "_emit_telemetry", lambda *a, **k: None)

    real_drain = dae._drain_running

    def _drain_capture(sd, grace=30.0):
        # snapshot the singleton AT shutdown time, before the finally closes it
        captured_socket["at_shutdown"] = getattr(dae, "_SELFHEAL_DBUS_SOCKET", None)
        return 0

    monkeypatch.setattr(dae, "_drain_running", _drain_capture)

    config = {"agent_sandbox": {"bwrap": True}}
    rc = dae.run_daemon(tmp_path, state_dir, config)
    assert rc == 0

    # REAL assertion (RED on HEAD: no startup proxy-init -> 0 enters, attr None):
    assert record["proxy_enters"] == 1, (
        "run_daemon must open exactly ONE proxied_session_bus() at startup when "
        "sandbox is enabled")
    assert captured_socket.get("at_shutdown") == _SENTINEL_SOCK, (
        "the daemon-lifetime singleton socket must be live during the loop")
    # the singleton stack must be closed on shutdown (no proxy leak):
    assert record["proxy_exits"] == 1, "the startup proxy must be reaped on shutdown"


def test_startup_no_proxy_when_sandbox_disabled(tmp_path, monkeypatch):
    """Fail-open / no-op when bwrap is off: no proxy is opened and the socket
    stays None (preserves prior real-bus behavior for un-sandboxed daemons)."""
    _reset_singleton(monkeypatch)
    _disable_sandbox(monkeypatch)
    record = {"proxy_enters": 0, "proxy_exits": 0}
    fake_cm = _FakeProxyCM(record)
    monkeypatch.setattr(dbus_proxy, "proxied_session_bus", fake_cm)
    monkeypatch.setattr(dae, "proxied_session_bus", fake_cm, raising=False)

    state_dir = tmp_path / "state"
    (state_dir / "control" / "autowork").mkdir(parents=True)
    (state_dir / "control" / "autowork" / "full_stop").touch()

    monkeypatch.setattr(dae, "_install_sigterm_handler", lambda: None)
    monkeypatch.setattr(dae, "_resume_or_kill_orphaned_workers",
                        lambda *a, **k: None)
    monkeypatch.setattr(dae, "_emit_telemetry", lambda *a, **k: None)
    monkeypatch.setattr(dae, "_drain_running", lambda *a, **k: 0)

    config = {"agent_sandbox": {"bwrap": False}}
    rc = dae.run_daemon(tmp_path, state_dir, config)
    assert rc == 0
    assert record["proxy_enters"] == 0
    assert getattr(dae, "_SELFHEAL_DBUS_SOCKET", None) is None


def test_startup_fail_open_when_proxy_raises(tmp_path, monkeypatch):
    """If the proxy cannot start, run_daemon must FAIL OPEN: leave the socket
    None and continue to clean shutdown (never abort the daemon)."""
    _reset_singleton(monkeypatch)
    _enable_sandbox(monkeypatch)

    def _boom(*a, **k):
        raise RuntimeError("xdg-dbus-proxy unavailable")

    monkeypatch.setattr(dbus_proxy, "proxied_session_bus", _boom)
    monkeypatch.setattr(dae, "proxied_session_bus", _boom, raising=False)

    state_dir = tmp_path / "state"
    (state_dir / "control" / "autowork").mkdir(parents=True)
    (state_dir / "control" / "autowork" / "full_stop").touch()

    monkeypatch.setattr(dae, "_install_sigterm_handler", lambda: None)
    monkeypatch.setattr(dae, "_resume_or_kill_orphaned_workers",
                        lambda *a, **k: None)
    monkeypatch.setattr(dae, "_emit_telemetry", lambda *a, **k: None)
    monkeypatch.setattr(dae, "_drain_running", lambda *a, **k: 0)

    config = {"agent_sandbox": {"bwrap": True}}
    rc = dae.run_daemon(tmp_path, state_dir, config)
    assert rc == 0
    assert getattr(dae, "_SELFHEAL_DBUS_SOCKET", None) is None


# --------------------------------------------------------------------------- #
# THREADING — when the singleton socket is set, _contain_selfheal threads it
# into build_jail_argv. Driven via the real _escalate_to_autobrief funnel.
# --------------------------------------------------------------------------- #
def test_escalate_threads_singleton_socket_into_jail(workroot, tmp_path, monkeypatch):
    _reset_singleton(monkeypatch)
    _enable_sandbox(monkeypatch)
    # Daemon "started": the lifetime singleton holds a live socket.
    monkeypatch.setattr(dae, "_SELFHEAL_DBUS_SOCKET", _SENTINEL_SOCK, raising=False)

    captured = {}
    _patch_daemon_popen(monkeypatch, captured)
    _spy_build_jail_argv(monkeypatch, captured)
    # toy claude config carries no --settings; stub the C7-R hook assertion.
    monkeypatch.setattr(orch, "_assert_claude_hook_config", lambda cmd: None)

    state_dir = tmp_path / "state"
    tid = _write_blocked_task(state_dir)
    dae._escalate_to_autobrief(state_dir, tid, "fuzz_fail")

    assert captured.get("jail_called") is True, "build_jail_argv must be reached"
    # REAL assertion (RED on HEAD: _contain_selfheal passes no dbus_proxy_socket
    # -> defaults to None instead of the live singleton sentinel):
    assert captured.get("dbus_proxy_socket") == _SENTINEL_SOCK, (
        "_contain_selfheal must thread the daemon-lifetime singleton socket "
        "into build_jail_argv when the daemon is started")


def test_inactivity_threads_singleton_socket_into_jail(workroot, tmp_path, monkeypatch):
    """The sibling _escalate_inactivity funnels through the same _contain_selfheal,
    so it threads the singleton too (no separate per-site wiring needed)."""
    _reset_singleton(monkeypatch)
    _enable_sandbox(monkeypatch)
    monkeypatch.setattr(dae, "_SELFHEAL_DBUS_SOCKET", _SENTINEL_SOCK, raising=False)

    captured = {}
    _patch_daemon_popen(monkeypatch, captured)
    _spy_build_jail_argv(monkeypatch, captured)
    monkeypatch.setattr(orch, "_assert_claude_hook_config", lambda cmd: None)

    state_dir = tmp_path / "state"
    (state_dir / "tasks").mkdir(parents=True)
    (state_dir / "tasks" / "Q.json").write_text(json.dumps({"task_id": "Q"}))
    cfg = {"control": {"autobrief_default_agent": "claude"},
           "agents": {"claude": {"command": "claude", "args": ["-p"]}}}
    dae._escalate_inactivity(state_dir, cfg)

    assert captured.get("jail_called") is True
    assert captured.get("dbus_proxy_socket") == _SENTINEL_SOCK


# --------------------------------------------------------------------------- #
# BACKWARD-COMPAT GUARD — daemon NOT started (singleton None, the unit-test
# default). The escalation must thread dbus_proxy_socket is None AND add NO
# extra proxy Popen. This is the assertion the 3 previously-breaking tests rely
# on (a naive per-escalation `with proxied_session_bus()` would add a Popen and
# pass a non-None socket -> this guards against that regression).
# --------------------------------------------------------------------------- #
def test_backward_compat_no_socket_no_extra_popen_when_not_started(workroot, tmp_path, monkeypatch):
    _reset_singleton(monkeypatch)
    _enable_sandbox(monkeypatch)
    # Daemon NOT started: singleton stays None (do NOT set it).
    if hasattr(dae, "_SELFHEAL_DBUS_SOCKET"):
        monkeypatch.setattr(dae, "_SELFHEAL_DBUS_SOCKET", None, raising=False)

    record = {"proxy_enters": 0, "proxy_exits": 0}
    fake_cm = _FakeProxyCM(record)
    monkeypatch.setattr(dbus_proxy, "proxied_session_bus", fake_cm)
    monkeypatch.setattr(dae, "proxied_session_bus", fake_cm, raising=False)

    captured = {}
    _patch_daemon_popen(monkeypatch, captured)
    _spy_build_jail_argv(monkeypatch, captured)
    monkeypatch.setattr(orch, "_assert_claude_hook_config", lambda cmd: None)

    state_dir = tmp_path / "state"
    tid = _write_blocked_task(state_dir)
    dae._escalate_to_autobrief(state_dir, tid, "fuzz_fail")

    assert captured.get("jail_called") is True
    # socket threaded as None (current/preserved behavior):
    assert captured.get("dbus_proxy_socket") is None, (
        "with the daemon not started the singleton is None and must be threaded "
        "as None -- not a freshly-opened per-escalation socket")
    # NO per-escalation proxy was opened (this is what keeps the 3 Popen-count
    # tests green):
    assert record["proxy_enters"] == 0, (
        "the escalation path must NOT open a per-escalation proxied_session_bus()")
    # exactly ONE Popen (the detached self-heal agent), no extra proxy Popen:
    assert captured["popen_count"] == 1, (
        f"expected exactly 1 Popen (the agent), got {captured['popen_count']}")
    # sanity: the detached spawn still relocates cwd outside the repo.
    assert _is_outside_repo(captured["cwd"])
