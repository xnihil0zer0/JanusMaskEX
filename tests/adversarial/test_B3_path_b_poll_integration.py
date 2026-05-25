"""B3 adversarial suite — Path B outbox fallback integration in
``poll_for_submission`` (HEAD 6ec6e29).

Covers 20 adversarial vectors. All tests are hermetic:
  * ``tmp_path`` for state_dir and work_dir
  * ``MagicMock`` stand-in for ``subprocess.Popen`` (no real processes)
  * ``monkeypatch`` for env + clock (``time.sleep``/``time.monotonic``)

NO production edits. NO real agent spawns. NO git mutations.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from harness.orchestrator import (  # noqa: E402
    poll_for_submission,
    _path_b_outbox_fallback,
)
from harness.session_namer import generate_submission_filename  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_state_dir(tmp_path: Path) -> Path:
    state_dir = tmp_path / "state"
    (state_dir / "sessions").mkdir(parents=True, exist_ok=True)
    # Minimal STATE.json so the watchdog branch can read without exception.
    (state_dir / "STATE.json").write_text(json.dumps({
        "task_id": None, "round": 0, "phase": "idle",
        "claude_status": "pending", "gemini_status": "pending",
        "status_updated_at_epoch": None,
    }))
    return state_dir


def _make_work_dir(tmp_path: Path, name: str = "wd") -> Path:
    wd = tmp_path / name
    (wd / "outbox").mkdir(parents=True, exist_ok=True)
    return wd


def _fake_proc(poll_sequence=None, pid: int = 4242, work_dir: Path | None = None,
               has_work_dir: bool = True) -> MagicMock:
    """Construct a MagicMock that quacks like a subprocess.Popen.

    ``poll_sequence`` iterates values returned by successive ``proc.poll()`` calls
    (e.g. [None, None, 0] => alive twice, then exited). The last value repeats.
    """
    proc = MagicMock(spec=["poll", "returncode", "pid", "wait", "kill",
                           "terminate", "_work_dir"])
    proc.pid = pid
    if poll_sequence is None:
        poll_sequence = [None] * 1024  # alive forever
    seq = list(poll_sequence)
    last = {"rc": None}

    def _poll():
        if len(seq) > 1:
            v = seq.pop(0)
        else:
            v = seq[0]
        last["rc"] = v
        proc.returncode = v if v is not None else 0
        return v
    proc.poll.side_effect = _poll
    if has_work_dir:
        proc._work_dir = work_dir
    else:
        # Explicitly remove the attribute so getattr returns the default.
        if hasattr(proc, "_work_dir"):
            del proc._work_dir
    return proc


def _canonical_path(state_dir: Path, agent: str, round_number: int, task_id: str) -> Path:
    return state_dir / "sessions" / generate_submission_filename(
        agent, round_number, task_id)


VALID_PY = "def f():\n    return 42\n"
INVALID_PY = "def f(:\n  return 42\n"  # syntactically broken


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _fast_sleep(monkeypatch):
    """Make time.sleep a no-op so poll loops tick fast."""
    monkeypatch.setattr("harness.orchestrator.time.sleep", lambda s: None)
    yield


@pytest.fixture(autouse=True)
def _clear_task_id(monkeypatch):
    monkeypatch.delenv("JANUSMASK_TASK_ID", raising=False)
    yield


# ---------------------------------------------------------------------------
# Vectors
# ---------------------------------------------------------------------------

def test_v1_canonical_wins_over_outbox(tmp_path, monkeypatch):
    """Vector 1: canonical submission.json present AND valid -> fallback NOT used."""
    state_dir = _make_state_dir(tmp_path)
    work_dir = _make_work_dir(tmp_path)
    task_id = "default"
    sub_path = _canonical_path(state_dir, "claude", 1, task_id)
    sub_path.write_text(json.dumps({"code": "def canonical():\n    return 1\n",
                                    "task_id": task_id}))
    outbox_code = "def outbox():\n    return 2\n"
    (work_dir / "outbox" / "submission.py").write_text(outbox_code)
    proc = _fake_proc(work_dir=work_dir)
    called = {"n": 0}
    orig = _path_b_outbox_fallback

    def spy(*a, **kw):
        called["n"] += 1
        return orig(*a, **kw)
    with patch("harness.orchestrator._path_b_outbox_fallback", side_effect=spy):
        code = poll_for_submission("claude", state_dir, 1, proc, timeout=2)
    assert code == "def canonical():\n    return 1\n"
    assert called["n"] == 0  # fallback never invoked — canonical check wins first


def test_v2_outbox_only_first_tick(tmp_path):
    """Vector 2: canonical absent, outbox valid on first tick -> fallback recovers."""
    state_dir = _make_state_dir(tmp_path)
    work_dir = _make_work_dir(tmp_path)
    (work_dir / "outbox" / "submission.py").write_text(VALID_PY)
    proc = _fake_proc(work_dir=work_dir)
    sub_path = _canonical_path(state_dir, "claude", 1, "default")
    assert not sub_path.is_file()
    code = poll_for_submission("claude", state_dir, 1, proc, timeout=5)
    assert code == VALID_PY
    # canonical JSON now materialized by the fallback
    assert sub_path.is_file()
    data = json.loads(sub_path.read_text())
    assert data["code"] == VALID_PY
    assert data["task_id"] == "default"


def test_v3_outbox_materializes_mid_poll(tmp_path, monkeypatch):
    """Vector 3: outbox empty for first 2 ticks, appears on 3rd tick."""
    state_dir = _make_state_dir(tmp_path)
    work_dir = _make_work_dir(tmp_path)
    outbox = work_dir / "outbox" / "submission.py"
    tick = {"n": 0}

    # Instead of relying on wallclock, intercept time.monotonic and write
    # the outbox when the third tick happens.
    t = {"now": 1000.0}

    def fake_mono():
        t["now"] += 0.5
        tick["n"] += 1
        if tick["n"] == 3 and not outbox.is_file():
            outbox.write_text(VALID_PY)
        return t["now"]
    monkeypatch.setattr("harness.orchestrator.time.monotonic", fake_mono)
    proc = _fake_proc(work_dir=work_dir)
    code = poll_for_submission("claude", state_dir, 1, proc, timeout=60)
    assert code == VALID_PY


def test_v4_proc_exits_then_outbox_appears(tmp_path, monkeypatch):
    """Vector 4: proc.poll() returns alive for K ticks then exits, outbox
    written to disk just before/between the exit tick. The proc-exit
    branch's fallback call picks it up."""
    state_dir = _make_state_dir(tmp_path)
    work_dir = _make_work_dir(tmp_path)
    outbox = work_dir / "outbox" / "submission.py"
    # Alive for 2 ticks then exits with rc=1
    proc = _fake_proc(poll_sequence=[None, None, 1], work_dir=work_dir)

    # Write outbox content right before poll() is called the 3rd time
    # (i.e. on the tick where proc is reported as exited). We wrap poll
    # to write VALID_PY the moment it would return a non-None value.
    real_poll = proc.poll.side_effect

    def poll_then_write():
        rc = real_poll()
        if rc is not None and not outbox.is_file():
            outbox.write_text(VALID_PY)
        return rc
    proc.poll.side_effect = poll_then_write

    code = poll_for_submission("claude", state_dir, 1, proc, timeout=10)
    assert code == VALID_PY


def test_v5_proc_exits_no_canonical_no_outbox(tmp_path):
    """Vector 5: proc exits with neither canonical nor outbox -> returns None."""
    state_dir = _make_state_dir(tmp_path)
    work_dir = _make_work_dir(tmp_path)
    proc = _fake_proc(poll_sequence=[1], work_dir=work_dir)  # exits immediately rc=1
    code = poll_for_submission("claude", state_dir, 1, proc, timeout=5)
    assert code is None


def test_v6_outbox_invalid_python_throughout(tmp_path, monkeypatch):
    """Vector 6: outbox has invalid Python on every tick -> timeout -> None."""
    state_dir = _make_state_dir(tmp_path)
    work_dir = _make_work_dir(tmp_path)
    (work_dir / "outbox" / "submission.py").write_text(INVALID_PY)
    proc = _fake_proc(work_dir=work_dir)
    # Make deadline terminate quickly: patch monotonic to step 10s per call.
    t = {"now": 0.0}

    def fake_mono():
        t["now"] += 10.0
        return t["now"]
    monkeypatch.setattr("harness.orchestrator.time.monotonic", fake_mono)
    code = poll_for_submission("claude", state_dir, 1, proc, timeout=5)
    assert code is None


def test_v7_no_work_dir_attr_falls_back_to_canonical_only(tmp_path):
    """Vector 7: legacy caller — proc has no _work_dir attribute.
    getattr returns None; fallback branch skipped entirely."""
    state_dir = _make_state_dir(tmp_path)
    # Simulate legacy: has_work_dir=False removes the attr
    proc = _fake_proc(has_work_dir=False)
    # Canonical never written; proc immediately exits
    proc.poll.side_effect = lambda: 0
    proc.returncode = 0
    code = poll_for_submission("claude", state_dir, 1, proc, timeout=2)
    assert code is None  # no crash, falls through to "died without submitting"


def test_v8_work_dir_points_at_nonexistent_dir(tmp_path):
    """Vector 8: work_dir is a path that does not exist."""
    state_dir = _make_state_dir(tmp_path)
    bogus = tmp_path / "does_not_exist" / "wd"
    proc = _fake_proc(poll_sequence=[0], work_dir=bogus)
    # Helper must return None without raising.
    assert _path_b_outbox_fallback(bogus, state_dir / "sessions" / "x.json",
                                   "default") is None
    code = poll_for_submission("claude", state_dir, 1, proc, timeout=2)
    assert code is None


def test_v9_watchdog_timeout_still_fires(tmp_path, monkeypatch):
    """Vector 9: watchdog >600s stale status still triggers when work_dir
    set and outbox is empty."""
    state_dir = _make_state_dir(tmp_path)
    # Mark claude running with stale status_updated_at (>600s ago).
    state_path = state_dir / "STATE.json"
    state = json.loads(state_path.read_text())
    state["claude_status"] = "running"
    state["status_updated_at_epoch"] = time.time() - 3600
    state_path.write_text(json.dumps(state))
    work_dir = _make_work_dir(tmp_path)
    proc = _fake_proc(work_dir=work_dir)  # stays alive forever
    code = poll_for_submission("claude", state_dir, 1, proc, timeout=60)
    assert code is None
    # status flipped to timeout
    final = json.loads(state_path.read_text())
    assert final["claude_status"] == "timeout"


def test_v10_main_deadline_timeout_no_content(tmp_path, monkeypatch):
    """Vector 10: timeout=1 with no content anywhere -> returns None cleanly."""
    state_dir = _make_state_dir(tmp_path)
    work_dir = _make_work_dir(tmp_path)
    proc = _fake_proc(work_dir=work_dir)
    t = {"now": 0.0}

    def fake_mono():
        t["now"] += 2.0
        return t["now"]
    monkeypatch.setattr("harness.orchestrator.time.monotonic", fake_mono)
    code = poll_for_submission("claude", state_dir, 1, proc, timeout=1)
    assert code is None


def test_v11_proc_poll_zero_no_submission(tmp_path):
    """Vector 11: rc=0 (success exit) but neither canonical nor outbox -> None
    via the 'died without submitting' log path."""
    state_dir = _make_state_dir(tmp_path)
    work_dir = _make_work_dir(tmp_path)
    proc = _fake_proc(poll_sequence=[0], work_dir=work_dir)
    code = poll_for_submission("claude", state_dir, 1, proc, timeout=2)
    assert code is None


def test_v12_nonzero_exit_canonical_appears_just_before(tmp_path, monkeypatch):
    """Vector 12: proc exits nonzero; canonical appeared on the exit tick
    (outbox never written). Existing exit-branch canonical recheck wins;
    fallback path not reachable because outbox is empty."""
    state_dir = _make_state_dir(tmp_path)
    work_dir = _make_work_dir(tmp_path)
    # Outbox intentionally EMPTY — fallback returns None, canonical wins.
    sub_path = _canonical_path(state_dir, "claude", 1, "default")
    state = {"count": 0}

    def poll_fn():
        state["count"] += 1
        if state["count"] == 1:
            return None
        # On tick 2 the proc has exited; write canonical first so the
        # exit-branch recheck succeeds before fallback is tried.
        sub_path.write_text(json.dumps(
            {"code": "def canonical():\n    return 99\n",
             "task_id": "default"}))
        return 2  # exit with rc=2
    proc = _fake_proc(work_dir=work_dir)
    proc.poll.side_effect = poll_fn
    # Spy the fallback — it may be called once (main loop, tick 1 — returns
    # None because outbox empty). What matters: the *return value* comes from
    # the canonical recheck, not from fallback.
    called = {"n": 0}
    real = _path_b_outbox_fallback

    def spy(*a, **kw):
        called["n"] += 1
        return real(*a, **kw)
    with patch("harness.orchestrator._path_b_outbox_fallback", side_effect=spy):
        code = poll_for_submission("claude", state_dir, 1, proc, timeout=5)
    assert code == "def canonical():\n    return 99\n"


def test_v13_nonzero_exit_outbox_has_content(tmp_path):
    """Vector 13 (the B3 #12 scenario): proc exits nonzero, canonical absent,
    outbox has valid content -> fallback recovers in exit branch."""
    state_dir = _make_state_dir(tmp_path)
    work_dir = _make_work_dir(tmp_path)
    (work_dir / "outbox" / "submission.py").write_text(VALID_PY)
    proc = _fake_proc(poll_sequence=[7], work_dir=work_dir)  # immediate exit
    code = poll_for_submission("claude", state_dir, 1, proc, timeout=5)
    assert code == VALID_PY


def test_v14_concurrent_writes_canonical_precedence(tmp_path):
    """Vector 14: canonical AND outbox both written between ticks -> canonical
    precedence from check-ordering."""
    state_dir = _make_state_dir(tmp_path)
    work_dir = _make_work_dir(tmp_path)
    sub_path = _canonical_path(state_dir, "claude", 1, "default")
    # Pre-write both before first tick
    sub_path.write_text(json.dumps(
        {"code": "def canonical():\n    return 'c'\n", "task_id": "default"}))
    (work_dir / "outbox" / "submission.py").write_text(
        "def outbox():\n    return 'o'\n")
    proc = _fake_proc(work_dir=work_dir)
    code = poll_for_submission("claude", state_dir, 1, proc, timeout=2)
    assert "canonical" in code and "outbox" not in code


def test_v15_race_partial_then_full(tmp_path, monkeypatch):
    """Vector 15: outbox partially written (invalid) on tick N, fully valid
    on tick N+1 -> N skipped (ast.parse fails), N+1 recovered."""
    state_dir = _make_state_dir(tmp_path)
    work_dir = _make_work_dir(tmp_path)
    outbox = work_dir / "outbox" / "submission.py"
    outbox.write_text(INVALID_PY)
    tick = {"n": 0}
    t = {"now": 0.0}

    def fake_mono():
        tick["n"] += 1
        t["now"] += 0.5
        if tick["n"] == 3:
            outbox.write_text(VALID_PY)
        return t["now"]
    monkeypatch.setattr("harness.orchestrator.time.monotonic", fake_mono)
    proc = _fake_proc(work_dir=work_dir)
    code = poll_for_submission("claude", state_dir, 1, proc, timeout=60)
    assert code == VALID_PY


def test_v16_large_outbox_5000_loc(tmp_path):
    """Vector 16: 5000-line valid Python payload recovered; canonical written
    with correct size."""
    state_dir = _make_state_dir(tmp_path)
    work_dir = _make_work_dir(tmp_path)
    big = "def f0():\n    return 0\n" + "".join(
        f"def f{i}():\n    return {i}\n" for i in range(1, 2501))
    # That's ~2500 funcs * 2 lines + 2 = ~5002 lines
    assert big.count("\n") >= 5000
    (work_dir / "outbox" / "submission.py").write_text(big)
    proc = _fake_proc(work_dir=work_dir)
    code = poll_for_submission("claude", state_dir, 1, proc, timeout=5)
    assert code == big
    sub_path = _canonical_path(state_dir, "claude", 1, "default")
    data = json.loads(sub_path.read_text())
    assert len(data["code"]) == len(big)


def test_v17_empty_task_id_env_defaults_to_default(tmp_path, monkeypatch):
    """Vector 17: JANUSMASK_TASK_ID unset -> 'default' filename used."""
    monkeypatch.delenv("JANUSMASK_TASK_ID", raising=False)
    state_dir = _make_state_dir(tmp_path)
    work_dir = _make_work_dir(tmp_path)
    (work_dir / "outbox" / "submission.py").write_text(VALID_PY)
    proc = _fake_proc(work_dir=work_dir)
    code = poll_for_submission("gemini", state_dir, 3, proc, timeout=5)
    assert code == VALID_PY
    expected = _canonical_path(state_dir, "gemini", 3, "default")
    assert expected.is_file()


def test_v18_custom_task_id_in_filename(tmp_path, monkeypatch):
    """Vector 18: custom JANUSMASK_TASK_ID -> matches session_namer format."""
    monkeypatch.setenv("JANUSMASK_TASK_ID", "CUSTOM-TASK-77")
    state_dir = _make_state_dir(tmp_path)
    work_dir = _make_work_dir(tmp_path)
    (work_dir / "outbox" / "submission.py").write_text(VALID_PY)
    proc = _fake_proc(work_dir=work_dir)
    code = poll_for_submission("claude", state_dir, 2, proc, timeout=5)
    assert code == VALID_PY
    expected = _canonical_path(state_dir, "claude", 2, "CUSTOM-TASK-77")
    assert expected.is_file()
    data = json.loads(expected.read_text())
    assert data["task_id"] == "CUSTOM-TASK-77"


def test_v19_fallback_content_but_sub_path_write_fails(tmp_path, monkeypatch):
    """Vector 19: fallback content extracted but sessions_dir write fails;
    helper logs warning and still returns content; poll returns it."""
    state_dir = _make_state_dir(tmp_path)
    work_dir = _make_work_dir(tmp_path)
    (work_dir / "outbox" / "submission.py").write_text(VALID_PY)
    # Monkeypatch Path.replace to raise OSError for our specific sub_path.
    sub_path = _canonical_path(state_dir, "claude", 1, "default")
    real_replace = Path.replace

    def boom_replace(self, other):
        if str(other) == str(sub_path):
            raise OSError("read-only")
        return real_replace(self, other)
    monkeypatch.setattr(Path, "replace", boom_replace)
    proc = _fake_proc(work_dir=work_dir)
    code = poll_for_submission("claude", state_dir, 1, proc, timeout=5)
    # Must still return the content from the outbox even though canonical
    # materialization failed.
    assert code == VALID_PY


def test_v20_idempotency_retry_after_timeout(tmp_path, monkeypatch):
    """Vector 20: first poll times out with no content; second poll with the
    same proc+outbox recovers as soon as outbox materializes."""
    state_dir = _make_state_dir(tmp_path)
    work_dir = _make_work_dir(tmp_path)
    outbox = work_dir / "outbox" / "submission.py"
    proc = _fake_proc(work_dir=work_dir)

    # First call: make monotonic race past deadline quickly.
    t = {"now": 0.0}

    def fast_mono():
        t["now"] += 10.0
        return t["now"]
    monkeypatch.setattr("harness.orchestrator.time.monotonic", fast_mono)
    code1 = poll_for_submission("claude", state_dir, 1, proc, timeout=1)
    assert code1 is None

    # Second call: outbox appears, monotonic returns small steady values.
    outbox.write_text(VALID_PY)
    t["now"] = 0.0
    monkeypatch.setattr("harness.orchestrator.time.monotonic",
                        lambda: (t.__setitem__("now", t["now"] + 0.5), t["now"])[1])
    code2 = poll_for_submission("claude", state_dir, 1, proc, timeout=30)
    assert code2 == VALID_PY
