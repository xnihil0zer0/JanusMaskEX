"""Adversarial plan 01 — T12: poll_for_submission outbox fallback, interceptor
deny, and the stale-state watchdog self-timeout hazard.

poll_for_submission (orchestrator.py :375) watches for a session submission file
while the agent is alive; _path_b_outbox_fallback (:339) promotes a valid
outbox/submission.py when no session file exists.

  T12a — no session file but a valid outbox submission.py -> fallback promotes it.
  T12b — interceptor pre_tool_use returns decision=deny -> session submission is
         dropped (file unlinked) and poll does not return that code.
  T12c — non-.py target -> _path_b_outbox_fallback skips ast.parse and still
         promotes non-Python content (target_is_py branch).
  T12d — GAP (plan §5 :460): a stale 'running' agent_status with an old
         status_updated_at_epoch makes a BRAND-NEW poll self-timeout immediately
         even though the process is alive — state-coupling hazard.

No agy/claude spawned; FakePopen never execs. interceptor registry patched.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

import harness.orchestrator as orch
from harness.session_namer import generate_submission_filename


class _FakePopen:
    def __init__(self, work_dir, poll_seq=None):
        self._work_dir = work_dir
        self.pid = 555
        self.returncode = None
        self._poll_seq = list(poll_seq) if poll_seq else None

    def poll(self):
        if self._poll_seq:
            rc = self._poll_seq.pop(0)
            if rc is not None:
                self.returncode = rc
            return rc
        return None  # alive


class _FakeRegistry:
    def __init__(self, deny=False):
        self.deny = deny
        self.calls = []

    def pre_tool_use(self, agent, tool, payload):
        self.calls.append(("pre", agent, tool))
        return {"decision": "deny", "reason": "blocked"} if self.deny else None

    def post_tool_use(self, agent, tool, payload):
        self.calls.append(("post", agent, tool))


@pytest.fixture
def state(tmp_path, monkeypatch):
    sd = tmp_path / "state"
    (sd / "sessions").mkdir(parents=True)
    monkeypatch.setenv("JANUSMASK_TASK_ID", "T12")
    return sd


def _patch_registry(monkeypatch, reg):
    import harness.interceptors as interceptors
    monkeypatch.setattr(interceptors, "registry", reg)


def test_T12a_outbox_fallback_promotes_valid_py(state, tmp_path, monkeypatch):
    reg = _FakeRegistry(deny=False)
    _patch_registry(monkeypatch, reg)

    wd = tmp_path / "wd"
    (wd / "outbox").mkdir(parents=True)
    (wd / "outbox" / "submission.py").write_text("def f():\n    return 1\n")
    proc = _FakePopen(wd)

    code = orch.poll_for_submission("claude", state, 1, proc, timeout=2)
    assert code is not None and "def f" in code
    # the promoted session file was written
    sub = state / "sessions" / generate_submission_filename("claude", 1, "T12")
    assert sub.is_file()


def test_T12b_interceptor_deny_drops_session_submission(state, tmp_path, monkeypatch):
    reg = _FakeRegistry(deny=True)
    _patch_registry(monkeypatch, reg)

    sub = state / "sessions" / generate_submission_filename("gemini", 1, "T12")
    sub.write_text(json.dumps({"code": "def g():\n    return 2\n"}))

    # process exits after a couple polls so the loop terminates (deny -> unlink -> None)
    proc = _FakePopen(tmp_path / "nowd", poll_seq=[None, 0])
    # no outbox dir -> no fallback

    code = orch.poll_for_submission("gemini", state, 1, proc, timeout=2)
    assert code is None, "denied submission must not be returned"
    assert not sub.exists(), "denied session submission file must be unlinked"


def test_T12c_non_py_target_skips_astparse_and_promotes(state, tmp_path, monkeypatch):
    reg = _FakeRegistry(deny=False)
    _patch_registry(monkeypatch, reg)

    # write the current_task_<id>.json so the fallback reads files_touched[0] non-.py
    (state / "tasks").mkdir(parents=True, exist_ok=True)
    (state / "tasks" / "current_task_T12.json").write_text(
        json.dumps({"files_touched": ["docs/readme.md"]}))

    wd = tmp_path / "wd2"
    (wd / "outbox").mkdir(parents=True)
    # NON-python content (would fail ast.parse) — must still promote because target is .md
    (wd / "outbox" / "submission.py").write_text("# Heading\nnot python at all ((( ")
    proc = _FakePopen(wd)

    code = orch.poll_for_submission("claude", state, 1, proc, timeout=2)
    assert code is not None and "Heading" in code, \
        "non-.py target must bypass ast.parse and still promote"


def test_T12d_stale_running_state_self_timeouts_fresh_poll(state, tmp_path, monkeypatch):
    """GAP: a stale 'running' status with an old epoch immediately times out a
    fresh poll even though the FakePopen is alive and no submission exists yet."""
    from harness.state import init_state
    init_state(state)
    # seed a stale running status from a prior task
    from harness.state import locked_read_modify_write

    def _seed(s):
        s["claude_status"] = "running"
        s["status_updated_at_epoch"] = time.time() - 10_000  # ancient
        return s

    locked_read_modify_write(_seed, state)

    reg = _FakeRegistry(deny=False)
    _patch_registry(monkeypatch, reg)

    proc = _FakePopen(tmp_path / "nowd_d")  # alive forever, no submission
    code = orch.poll_for_submission("claude", state, 1, proc, timeout=5)
    assert code is None, (
        "GAP confirmed: a stale 'running' status with an old "
        "status_updated_at_epoch self-times-out a brand-new poll despite the "
        "process being alive and within its own timeout window."
    )
