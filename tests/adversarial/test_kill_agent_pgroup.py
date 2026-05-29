"""Adversarial plan 01 — T14: kill_agent reaps the whole process group.

kill_agent (orchestrator.py :309) must SIGTERM the process GROUP first, and
SIGKILL the group only if wait() times out. If os.getpgid raises (process gone),
it falls back to proc.terminate(). No real pid is ever touched — FakePopen +
spied os.killpg/os.getpgid.
"""
from __future__ import annotations

import signal

import pytest

import harness.orchestrator as orch


class _FakeProc:
    def __init__(self, poll_seq, wait_raises=False):
        self._poll_seq = list(poll_seq)
        self.pid = 4242
        self.returncode = None
        self.terminated = False
        self.killed = False
        self._wait_raises = wait_raises

    def poll(self):
        return self._poll_seq.pop(0) if self._poll_seq else 0

    def wait(self, timeout=None):
        if self._wait_raises:
            self._wait_raises = False  # only raise once (the SIGTERM wait)
            raise __import__("subprocess").TimeoutExpired(cmd="x", timeout=timeout)
        return 0

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


def test_T14_sigterm_to_pgroup_first(monkeypatch):
    signals = []
    monkeypatch.setattr(orch.os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(orch.os, "killpg", lambda pgid, sig: signals.append((pgid, sig)))
    monkeypatch.setattr(orch, "_join_stream_threads", lambda *a, **k: None)

    proc = _FakeProc(poll_seq=[None])  # alive
    orch.kill_agent(proc, "gemini", reason="handoff")

    assert signals and signals[0] == (4242, signal.SIGTERM), \
        f"first signal must be SIGTERM to the pgroup, got {signals}"
    assert not proc.terminated, "should not fall back to terminate() when killpg works"


def test_T14_sigkill_pgroup_on_wait_timeout(monkeypatch):
    signals = []
    monkeypatch.setattr(orch.os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(orch.os, "killpg", lambda pgid, sig: signals.append((pgid, sig)))
    monkeypatch.setattr(orch, "_join_stream_threads", lambda *a, **k: None)

    proc = _FakeProc(poll_seq=[None], wait_raises=True)  # SIGTERM wait times out
    orch.kill_agent(proc, "claude", reason="timeout")

    assert (4242, signal.SIGTERM) in signals
    assert (4242, signal.SIGKILL) in signals, \
        f"SIGKILL to the pgroup must follow a wait timeout, got {signals}"


def test_T14_getpgid_lookup_error_falls_back_to_terminate(monkeypatch):
    def _boom(pid):
        raise ProcessLookupError()

    monkeypatch.setattr(orch.os, "getpgid", _boom)
    monkeypatch.setattr(orch.os, "killpg", lambda *a: (_ for _ in ()).throw(AssertionError("killpg should not be reached")))
    monkeypatch.setattr(orch, "_join_stream_threads", lambda *a, **k: None)

    proc = _FakeProc(poll_seq=[None])
    orch.kill_agent(proc, "gemini", reason="handoff")
    assert proc.terminated, "must fall back to proc.terminate() when getpgid raises"


def test_T14_already_exited_is_noop(monkeypatch):
    monkeypatch.setattr(orch, "_join_stream_threads", lambda *a, **k: None)
    monkeypatch.setattr(orch.os, "killpg", lambda *a: (_ for _ in ()).throw(AssertionError("no kill on dead proc")))

    proc = _FakeProc(poll_seq=[0])  # already exited
    proc.returncode = 0
    orch.kill_agent(proc, "claude", reason="handoff")  # must not signal
