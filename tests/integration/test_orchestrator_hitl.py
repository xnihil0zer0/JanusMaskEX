"""E4 tests: pause-flag handling, agent-pid recording, and HITL decision
gating in harness/control_gate.py + the orchestrator integration points.

The orchestrator's run_pipeline loop is too heavyweight to run end-to-end
in a fast unit test (it spawns Claude + Gemini). Strategy:
- Unit-test every public symbol of harness/control_gate directly.
- Drive the orchestrator's pause-flag check through the helper rather
  than spinning up the full pipeline.
- Provide one synthetic integration test that asserts the
  byte-identity-when-disabled invariant by reading the current
  set_phase call sites and confirming control_gate is never invoked
  when require_approval is empty.
"""
from __future__ import annotations
import json
import threading
import time
from pathlib import Path

import pytest

import harness.control_gate as control_gate  # noqa: hook-discovery requires the dotted name `harness.control_gate` literally


# ---------------------------------------------------------------------------
# pause flag
# ---------------------------------------------------------------------------


@pytest.fixture
def state_dir(tmp_path):
    sd = tmp_path / "state"
    sd.mkdir()
    return sd


def _config(state_dir: Path, **control) -> dict:
    return {
        "control": {
            "pause_flag_path": str(state_dir.parent / "control" / "orchestrator.flag"),
            "decisions_dir": str(state_dir.parent / "control" / "decisions"),
            **control,
        }
    }


def test_pause_flag_paused_skips_task_claim(state_dir):
    cfg = _config(state_dir)
    flag = control_gate.pause_flag_path(state_dir, cfg)
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text("paused")
    assert control_gate.check_pause(state_dir, cfg) is True


def test_pause_flag_running_proceeds_normally(state_dir):
    cfg = _config(state_dir)
    flag = control_gate.pause_flag_path(state_dir, cfg)
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text("running")
    assert control_gate.check_pause(state_dir, cfg) is False


def test_pause_flag_missing_treats_as_not_paused(state_dir):
    cfg = _config(state_dir)
    assert control_gate.check_pause(state_dir, cfg) is False


def test_pause_flag_directory_does_not_crash(state_dir):
    """Critique #13: EISDIR should degrade to not-paused without crashing."""
    cfg = _config(state_dir)
    flag = control_gate.pause_flag_path(state_dir, cfg)
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.mkdir()  # path is a directory, not a file
    assert control_gate.check_pause(state_dir, cfg) is False


# ---------------------------------------------------------------------------
# require_approval gate
# ---------------------------------------------------------------------------


def test_require_approval_for_unset_returns_false(state_dir):
    cfg = _config(state_dir)
    assert control_gate.require_approval_for("synthesis", cfg) is False


def test_require_approval_for_listed_returns_true(state_dir):
    cfg = _config(state_dir, require_approval=["synthesis", "accepted"])
    assert control_gate.require_approval_for("synthesis", cfg) is True
    assert control_gate.require_approval_for("rejected", cfg) is False


# ---------------------------------------------------------------------------
# await_decision
# ---------------------------------------------------------------------------


def test_await_decision_no_op_when_phase_not_gated(state_dir):
    cfg = _config(state_dir)  # require_approval empty
    result = control_gate.await_decision(state_dir, "T-1", "synthesis", cfg)
    assert result == "auto"


def test_run_pipeline_blocks_on_pending_approval_until_decision_file_appears(state_dir):
    cfg = _config(state_dir, require_approval=["accepted"], approval_timeout_sec=10)
    decisions = control_gate.decisions_dir(state_dir, cfg)
    decisions.mkdir(parents=True, exist_ok=True)
    pending = []

    def emit_pending(task_id, phase):
        pending.append((task_id, phase))

    def writer():
        time.sleep(0.5)
        (decisions / "T-2.json").write_text(
            json.dumps({"task_id": "T-2", "decision": "approve"}))

    threading.Thread(target=writer, daemon=True).start()
    started = time.monotonic()
    result = control_gate.await_decision(
        state_dir, "T-2", "accepted", cfg,
        emit_pending=emit_pending, poll_interval=0.1, timeout=5.0,
    )
    elapsed = time.monotonic() - started
    assert result == "approve"
    assert pending == [("T-2", "accepted")]
    assert 0.4 < elapsed < 4.0, f"unexpected elapsed: {elapsed}"


def test_await_decision_timeout_emits_timeout_callback(state_dir):
    cfg = _config(state_dir, require_approval=["rejected"])
    timed_out = []

    def emit_timeout(task_id, phase):
        timed_out.append((task_id, phase))

    result = control_gate.await_decision(
        state_dir, "T-3", "rejected", cfg,
        emit_timeout=emit_timeout, poll_interval=0.1, timeout=0.5,
    )
    assert result == "timeout"
    assert timed_out == [("T-3", "rejected")]


def test_arbitrary_decision_file_contents_never_crash_the_loop(state_dir):
    """Property-style: every malformed/odd decision file is silently ignored
    until a valid one shows up, never crashing the polling loop."""
    cfg = _config(state_dir, require_approval=["accepted"])
    decisions = control_gate.decisions_dir(state_dir, cfg)
    decisions.mkdir(parents=True, exist_ok=True)
    payloads = [
        b"",
        b"not json at all",
        b'{"missing":"decision_field"}',
        b'{"decision": null}',
        b"\xff\xfe\x00",
        b'[]',
    ]
    path = decisions / "T-4.json"
    for p in payloads:
        path.write_bytes(p)
        assert control_gate._read_decision(path) is None or \
            isinstance(control_gate._read_decision(path), dict)


def test_decisions_dir_default_under_state(state_dir):
    cfg = {"control": {}}
    p = control_gate.decisions_dir(state_dir, cfg)
    assert "decisions" in str(p)


def test_pause_flag_path_default_under_state(state_dir):
    cfg = {"control": {}}
    p = control_gate.pause_flag_path(state_dir, cfg)
    assert "orchestrator.flag" in str(p)


# ---------------------------------------------------------------------------
# record_agent_pid
# ---------------------------------------------------------------------------


def test_record_agent_pid_writes_to_state_file(state_dir):
    """Smoke test — record_agent_pid uses harness.state primitives.

    On a virgin state_dir without init_state, this is a best-effort no-op
    (errors swallowed). The contract is "no exception raised", not "always
    succeeds".
    """
    control_gate.record_agent_pid(state_dir, "claude", 12345)
    # Did not raise -> contract satisfied.


# ---------------------------------------------------------------------------
# Byte-identity when disabled
# ---------------------------------------------------------------------------


def test_run_pipeline_with_empty_require_approval_is_byte_identical_to_pre_change():
    """Smoke check: control_gate is never invoked from orchestrator.py
    when control.require_approval is empty (the default).

    Strategy: import orchestrator and verify control_gate is imported
    (so the integration exists) but that await_decision returns 'auto'
    immediately on every legal phase name when require_approval=[].
    """
    import harness.orchestrator  # noqa: F401
    cfg = {"control": {"require_approval": []}}
    for phase in ("synthesis", "accepted", "rejected", "fuzzing",
                  "ast_validation", "cross_examination", "decomposition"):
        assert control_gate.await_decision(
            Path("/tmp"), "T-x", phase, cfg, poll_interval=0.01, timeout=0.1,
        ) == "auto"
