"""HITL pipeline-integration tests (HITL-TEST, session #30).

Unlike tests/integration/test_orchestrator_hitl.py (which unit-tests
harness.control_gate in isolation), these drive harness.orchestrator.run_pipeline
to the round-1-equivalent accept site with control.require_approval=['accepted']
and assert the HITL gate's observable contract at the ORCHESTRATOR layer:

  * a pending_approval ledger row is emitted (via _emit_pending),
  * an 'approve' decision commits (set_phase 'accepted', _auto_commit_accepted),
  * 'reject' / 'retry' / 'timeout' decisions do NOT commit (set_phase 'rejected').

The 'retry' case is the regression bar for HITL-RETRY: before that fix the three
accept sites only diverted on decision in ('reject','timeout'), so a 'retry'
decision fell through to _auto_commit_accepted and committed anyway.

Reuses the run_pipeline drive pattern proven in
tests/test_orchestrator.py::TestPipelineStateTransitions: patch run_both_agents,
_validate_submission, fuzz_from_task (equivalent), _auto_commit_accepted,
get_next_task (one task then None), and time.sleep (StopIteration breaks the
otherwise-infinite loop). control_gate.time.sleep is a DIFFERENT module
reference, so the gate's own poll is unaffected by the orchestrator sleep patch.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from harness.orchestrator import run_pipeline, init_state
from harness.diff_fuzzer import FuzzResult


@pytest.fixture
def pipeline_state_dir(tmp_path):
    for sub in ("tasks", "tasks/processed", "tasks/blocked", "sessions"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    init_state(tmp_path)
    return tmp_path


def _config(state_dir: Path, require_approval, timeout=5.0):
    return {
        "synthesis": {"timeout_seconds": 30, "max_ast_retries": 3},
        "fuzzing": {
            "engine": "hypothesis",
            "function_level_inputs": 50,
            "program_level_inputs": 20,
            "timeout_per_input_ms": 2000,
            "float_tolerance": 1e-9,
            "seed": 42,
        },
        "sandbox": {"memory_limit_mb": 256, "cpu_time_limit_seconds": 5, "network": False},
        "decomposition": {"max_depth": 3, "max_subtasks": 5, "fresh_instances": True},
        "agents": {
            "claude": {"command": "claude", "args": ["-p"]},
            "gemini": {"command": "gemini", "args": ["-p"]},
        },
        "control": {
            "require_approval": require_approval,
            # absolute path so the gate writes/reads the decision file here
            "decisions_dir": str(state_dir / "control" / "decisions"),
            "approval_timeout_sec": timeout,
        },
    }


def _one_task_then_none():
    state = {"called": False}

    def _next(_sd):
        if state["called"]:
            return None
        state["called"] = True
        # V2 requires a non-empty verification_command for a real auto-commit;
        # _auto_commit_accepted is mocked so 'true' is sufficient here.
        return {
            "task_id": "t-hitl",
            "specification": "Write add(a, b).",
            "constraints": {"deterministic": True},
            "verification_command": "true",
        }

    return _next


def _write_decision(state_dir: Path, task_id: str, decision: str):
    decisions = state_dir / "control" / "decisions"
    decisions.mkdir(parents=True, exist_ok=True)
    (decisions / f"{task_id}.json").write_text(
        json.dumps({"task_id": task_id, "decision": decision, "reason": "test"})
    )


def _ledger_events(state_dir: Path):
    path = state_dir / "impl_progress.jsonl"
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return rows


def _drive(state_dir, config, *, decision):
    if decision is not None:
        _write_decision(state_dir, "t-hitl", decision)

    phases_seen = []
    import harness.orchestrator as orch
    original_set_phase = orch.set_phase

    def tracking_set_phase(sd, *, phase):
        phases_seen.append(phase)
        return original_set_phase(sd, phase=phase)

    with patch("harness.orchestrator.run_both_agents",
               return_value=("def f(): pass", "def g(): pass")), \
         patch("harness.orchestrator._validate_submission", return_value=(True, [])), \
         patch("harness.orchestrator.fuzz_from_task",
               return_value=FuzzResult(equivalent=True, total_inputs=100, matching_inputs=100)), \
         patch("harness.orchestrator._auto_commit_accepted", return_value=True) as mock_commit, \
         patch("harness.orchestrator.set_phase", side_effect=tracking_set_phase), \
         patch("harness.orchestrator.get_next_task", side_effect=_one_task_then_none()), \
         patch("harness.orchestrator.time.sleep", side_effect=StopIteration):
        with pytest.raises(StopIteration):
            run_pipeline(config, state_dir)
    return phases_seen, mock_commit.call_count


def test_accepted_gate_emits_pending_then_approve_commits(pipeline_state_dir):
    cfg = _config(pipeline_state_dir, require_approval=["accepted"])
    phases, commits = _drive(pipeline_state_dir, cfg, decision="approve")

    events = _ledger_events(pipeline_state_dir)
    assert any(e.get("event") == "pending_approval" and e.get("task_id") == "t-hitl"
               for e in events), "expected a pending_approval ledger row"
    assert commits == 1, "approve must call _auto_commit_accepted"
    assert "accepted" in phases


@pytest.mark.parametrize("decision", ["reject", "retry"])
def test_accepted_gate_non_commit_decisions_do_not_commit(pipeline_state_dir, decision):
    cfg = _config(pipeline_state_dir, require_approval=["accepted"])
    phases, commits = _drive(pipeline_state_dir, cfg, decision=decision)

    assert commits == 0, f"{decision} must NOT call _auto_commit_accepted"
    assert "accepted" not in phases
    assert "rejected" in phases, f"{decision} should transition to rejected"


def test_accepted_gate_timeout_does_not_commit(pipeline_state_dir):
    # No decision file + approval_timeout_sec=0.0 -> await_decision returns 'timeout'
    # immediately (no poll sleep).
    cfg = _config(pipeline_state_dir, require_approval=["accepted"], timeout=0.0)
    phases, commits = _drive(pipeline_state_dir, cfg, decision=None)

    events = _ledger_events(pipeline_state_dir)
    assert any(e.get("event") == "approval_timeout" and e.get("task_id") == "t-hitl"
               for e in events), "expected an approval_timeout ledger row"
    assert commits == 0, "timeout must NOT call _auto_commit_accepted"
    assert "accepted" not in phases
    assert "rejected" in phases
