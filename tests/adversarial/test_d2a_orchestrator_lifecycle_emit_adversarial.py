"""META-D2a-MANUAL pin: harness.orchestrator emit-point closure.

Verifies the additive write_jsonl_row instrumentation per brief Deliverables D2:
- _emit_lifecycle helper exists with correct shape (try/except OSError, ts stamp)
- 31 instrumented sites: phase_transition, agent_status, task_claim, task_terminal
- emit failures swallowed (caller exit code unchanged)
- monotonic invariant: state/impl_progress.jsonl row count grows monotonically
"""
import inspect
import json
from pathlib import Path

import pytest

from harness import orchestrator


_AGENT_STATUS_TOKEN = "event='agent_status'"
_TASK_TERMINAL_TOKEN = "event='task_terminal'"


def test_emit_lifecycle_helper_exists_with_correct_shape():
    assert hasattr(orchestrator, "_emit_lifecycle"), "helper not defined"
    src = inspect.getsource(orchestrator._emit_lifecycle)
    assert "write_jsonl_row" in src
    assert "impl_progress.jsonl" in src
    assert "time.time()" in src
    assert "except OSError" in src
    assert "logger.warning" in src


def test_emit_lifecycle_writes_jsonl_row(tmp_path):
    orchestrator._emit_lifecycle(
        tmp_path,
        event="phase_transition",
        phase="ast_validation",
        task_id="T1",
        phase_transition={"to": "ast_validation"},
    )
    out = (tmp_path / "impl_progress.jsonl").read_text().strip()
    row = json.loads(out)
    assert row["event"] == "phase_transition"
    assert row["phase"] == "ast_validation"
    assert row["task_id"] == "T1"
    assert "ts" in row
    assert isinstance(row["ts"], float)
    assert row["phase_transition"] == {"to": "ast_validation"}


def test_emit_lifecycle_swallows_oserror(tmp_path, monkeypatch, caplog):
    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(orchestrator, "write_jsonl_row", boom)
    orchestrator._emit_lifecycle(tmp_path, event="task_terminal", task_id="X")
    assert any("lifecycle emit failed" in r.message for r in caplog.records)


def test_emit_lifecycle_swallows_permission_and_filenotfound(tmp_path, monkeypatch):
    """OSError subclasses (PermissionError, FileNotFoundError) also swallowed."""
    for exc_class in (PermissionError, FileNotFoundError):
        called = {"n": 0}

        def boom(*args, **kwargs):
            called["n"] += 1
            raise exc_class("err")

        monkeypatch.setattr(orchestrator, "write_jsonl_row", boom)
        orchestrator._emit_lifecycle(tmp_path, event="task_terminal", task_id="X")
        assert called["n"] == 1, exc_class.__name__ + " should have been raised + caught"


def test_static_source_pin_phase_transition_emit_after_set_phase():
    """Pin: every set_phase call site in run_pipeline has an _emit_lifecycle
    follow-up with event='phase_transition'.
    """
    src = inspect.getsource(orchestrator.run_pipeline)
    for phase in ("ast_validation", "rejected", "accepted", "fuzzing", "cross_examination", "decomposition"):
        assert "set_phase(state_dir, phase='" + phase + "')" in src, phase + " set_phase missing"
        assert "event='phase_transition', phase='" + phase + "'" in src, phase + " emit missing"


def test_static_source_pin_agent_status_emits_present():
    src = inspect.getsource(orchestrator.run_pipeline)
    assert _AGENT_STATUS_TOKEN in src, "agent_status emit not present in run_pipeline"
    n = src.count(_AGENT_STATUS_TOKEN)
    assert n >= 4, "expected >=4 agent_status emits in run_pipeline, got " + str(n)


def test_static_source_pin_task_claim_emit():
    src = inspect.getsource(orchestrator.get_next_task)
    assert "event='task_claim'" in src, "task_claim emit missing from get_next_task"
    after = src.split("event='task_claim'")[1][:200]
    assert "candidate_task_id" in after, "task_claim should include candidate_task_id"


def test_static_source_pin_task_terminal_after_mark_processed():
    src = inspect.getsource(orchestrator.run_pipeline)
    assert _TASK_TERMINAL_TOKEN in src
    n = src.count(_TASK_TERMINAL_TOKEN)
    assert n >= 6, "expected >=6 task_terminal emits, got " + str(n)


def test_emit_count_threshold_in_orchestrator_module():
    """Smoke: total _emit_lifecycle call sites in orchestrator.py."""
    mod_src = Path(orchestrator.__file__).read_text()
    call_count = mod_src.count("_emit_lifecycle(state_dir,")
    assert call_count >= 25, "expected >=25 _emit_lifecycle call sites, got " + str(call_count)


def test_emit_only_swallows_oserror_other_exceptions_propagate(tmp_path, monkeypatch):
    """Non-OSError DOES propagate (we only swallow OSError per the contract)."""
    def boom(*a, **k):
        raise RuntimeError("not OSError")
    monkeypatch.setattr(orchestrator, "write_jsonl_row", boom)
    with pytest.raises(RuntimeError):
        orchestrator._emit_lifecycle(tmp_path, event="x")


def test_monotonic_jsonl_growth_after_repeated_emits(tmp_path):
    """Property: after N emits, impl_progress.jsonl has exactly N rows."""
    target = tmp_path / "impl_progress.jsonl"
    for i in range(5):
        orchestrator._emit_lifecycle(tmp_path, event="phase_transition", phase="x" + str(i), task_id="T")
    rows = [r for r in target.read_text().splitlines() if r.strip()]
    assert len(rows) == 5
    for r in rows:
        json.loads(r)


def test_emit_includes_ts_field_per_row(tmp_path):
    for i in range(3):
        orchestrator._emit_lifecycle(tmp_path, event="task_terminal", task_id="T" + str(i))
    rows = [json.loads(r) for r in (tmp_path / "impl_progress.jsonl").read_text().splitlines() if r.strip()]
    timestamps = [r["ts"] for r in rows]
    assert all(isinstance(t, float) for t in timestamps)
    assert timestamps == sorted(timestamps)
