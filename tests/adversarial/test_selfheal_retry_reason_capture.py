"""Self-heal Link #2 retry-path oracle: the AST-validation reject terminal must persist the
per-agent violation reason to the ledger on the retry-module path (use_retry_module=True)
so the daemon's diagnose agent can see why the task failed.
"""
from __future__ import annotations

import json
import pathlib
import sys
import pytest

from harness import autowork_daemon as d
import harness.orchestrator as orch
import harness.orchestrator_worker as ow

REPO = pathlib.Path(__file__).resolve().parents[2]
WORKER = REPO / "harness" / "orchestrator_worker.py"


def test_ast_reject_terminal_persists_violation_detail() -> None:
    """Static analysis guard: check that the synthesis_or_ast_failed terminal
    references the per-agent AST violations."""
    src = WORKER.read_text(encoding="utf-8")
    anchor = "_mark_blocked(state_dir, task_id, 'synthesis_or_ast_failed')"
    assert anchor in src, "AST-reject terminal anchor moved/renamed"
    i = src.index(anchor)
    guard = src.rfind("if not synthesis_success:", 0, i)
    assert guard != -1, "synthesis_success terminal guard not found before anchor"
    window = src[guard:i]
    refs_violations = (
        "agent_a_violations" in window
        or "agent_b_violations" in window
        or "violation" in window.lower()
    )
    emits_ledger = (
        ("_emit_lifecycle" in window and "detail" in window)
        or "write_jsonl" in window
    )
    assert refs_violations and emits_ledger, (
        "synthesis_or_ast_failed terminal must persist the per-agent AST violation "
        "summary to impl_progress.jsonl"
    )


class MockViolation:
    def __init__(self, rule, line, message, severity):
        self.rule = rule
        self.line = line
        self.message = message
        self.severity = severity


def _run_mocked_synthesis_rejection(tmp_path, monkeypatch, antigravity_mode: bool) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    tasks_dir = state_dir / "tasks"
    tasks_dir.mkdir()

    task_id = "test_retry_telemetry_task"
    task = {
        "task_id": task_id,
        "specification": "Dummy spec for retry telemetry",
        "meta_task_type": "harness_self_fix",
        "dependencies": [],
        "files_touched": ["dummy.py"],
    }
    task_file = tasks_dir / f"{task_id}.json"
    task_file.write_text(json.dumps(task), encoding="utf-8")

    # Command line arguments
    monkeypatch.setattr(
        sys, "argv",
        ["orchestrator_worker", "--state-dir", str(state_dir), "--task-id", task_id]
    )

    # Config sets use_retry_module=True and antigravity_mode as requested
    cfg = {
        "synthesis": {
            "timeout_seconds": 60,
            "max_ast_retries": 2,
            "antigravity_mode": antigravity_mode,
            "use_retry_module": True,
            "active_agents": ["claude", "gemini"]
        }
    }
    monkeypatch.setattr(orch, "load_config", lambda *a, **k: cfg)

    # Mock outputs
    monkeypatch.setattr(orch, "run_agent_phase", lambda *a, **k: "def dummy(): pass")
    monkeypatch.setattr(orch, "prepare_task_prompt", lambda *a, **k: "prompt")

    # Reject submission with a concrete violation rule name
    violation = MockViolation("retry_eval_banned_rule", 3, "eval is banned", "error")
    monkeypatch.setattr(orch, "_validate_submission", lambda *a, **k: (False, [violation]))

    exit_code = ow.main()
    assert exit_code == 1

    # Read progress ledger
    progress_file = state_dir / "impl_progress.jsonl"
    assert progress_file.exists()
    
    events = []
    with open(progress_file, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                events.append(json.loads(line.strip()))
                
    ast_events = [e for e in events if e.get("event") == "ast_validation_failed"]
    assert len(ast_events) == 1, f"Expected 1 ast_validation_failed event, got: {ast_events}"
    detail = ast_events[0].get("detail", "")
    
    assert "retry_eval_banned_rule" in detail, (
        f"Expected violation rule 'retry_eval_banned_rule' in detail, got: {detail!r}"
    )


def test_selfheal_retry_reason_capture_behavioral_serial(tmp_path, monkeypatch) -> None:
    """Drive synthesis retry path (serial) and verify it captures and logs AST rule violations."""
    _run_mocked_synthesis_rejection(tmp_path, monkeypatch, antigravity_mode=True)


def test_selfheal_retry_reason_capture_behavioral_parallel(tmp_path, monkeypatch) -> None:
    """Drive synthesis retry path (parallel thread pool) and verify it captures and logs AST rule violations."""
    _run_mocked_synthesis_rejection(tmp_path, monkeypatch, antigravity_mode=False)
