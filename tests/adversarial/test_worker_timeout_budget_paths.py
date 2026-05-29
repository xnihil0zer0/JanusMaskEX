"""Adversarial plan 01 — T3/T4: per-worker timeout budget coverage.

The RECONCILE_TIMEOUT_BUDGETS work (8dac6e1) added a per-retry budget guard at
orchestrator_worker.py:179-185 that exits 2 ``insufficient_time_for_retry`` when
the remaining wall budget is below one synthesis window. These tests prove:

  T3a — the guard IS reachable+fires on a *retry* (ast_retries>0) when budget is
        exhausted, via the single-agent-missing loop.
  T3b — the guard is SKIPPED on attempt 0 (``if ast_retries > 0``), so a fresh
        synthesis is never pre-empted; combined with T2 (double-timeout exits
        immediately) the only way to consume budget across retries is repeated
        single-missing / AST-invalid loops.
  T4  — GAP: ``ast_retry.synthesize_with_retries`` (the ``use_retry_module=True``
        path) has NO budget check at all. The RECONCILE protection vanishes if
        the config flag is flipped. Proven by source inspection.

No agy/claude spawned. run_both_agents mocked; time.monotonic patched.
"""
from __future__ import annotations

import inspect
import json
import sys

import pytest

import harness.orchestrator as orch
import harness.orchestrator_worker as ow
import harness.ast_retry as ast_retry


@pytest.fixture
def worker_env(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    (state_dir / "tasks").mkdir(parents=True)
    (state_dir / "sessions").mkdir(parents=True)
    task_id = "BUDGET_T"
    task = {"task_id": task_id, "specification": "x", "files_touched": ["pkg/m.py"],
            "verification_command": "true"}
    (state_dir / "tasks" / f"{task_id}.json").write_text(json.dumps(task))
    cfg = {"synthesis": {"timeout_seconds": 600, "max_ast_retries": 3,
                         "antigravity_mode": False,
                         "active_agents": ["claude", "gemini"]},
           "cross_examination": {"max_rounds": 1},
           "decomposition": {"max_depth": 3}}
    monkeypatch.setattr(orch, "load_config", lambda *a, **k: cfg)
    monkeypatch.setenv("JANUSMASK_AGENT_WORKROOT", str(tmp_path / "wr"))
    monkeypatch.setattr(sys, "argv",
                        ["ow", "--state-dir", str(state_dir), "--task-id", task_id])
    return {"state_dir": state_dir, "task_id": task_id}


def test_T3a_budget_guard_fires_on_retry(worker_env, monkeypatch):
    """Single-agent-missing loop reaches ast_retries>0; with exhausted budget the
    guard exits 2 insufficient_time_for_retry."""
    # tiny budgets: hard=1.0s, window=10.0s -> any elapsed > (1-10) is "insufficient"
    monkeypatch.setattr(ow, "_compute_timeout_budgets", lambda cfg: (1.0, 10.0))

    # make time advance a lot after the first iteration so the retry guard trips
    clock = {"t": 1000.0}

    def _mono():
        return clock["t"]

    monkeypatch.setattr(ow.time, "monotonic", _mono)

    commit_calls = []
    monkeypatch.setattr(orch, "_auto_commit_accepted",
                        lambda *a, **k: commit_calls.append(1) or True)

    def _fake_run_both(*a, **k):
        clock["t"] += 100.0  # burn wall time so retry sees insufficient budget
        return ("code_a", None)  # single-missing -> loop continues to retry

    monkeypatch.setattr(orch, "run_both_agents", _fake_run_both)

    rc = ow.main()
    assert rc == 2, f"exhausted retry budget must exit 2, got {rc}"
    assert not commit_calls


def test_T3b_budget_guard_skipped_on_attempt_zero(worker_env, monkeypatch):
    """Attempt 0 is never pre-empted even with a tiny/negative budget."""
    monkeypatch.setattr(ow, "_compute_timeout_budgets", lambda cfg: (1.0, 10.0))
    # monotonic constant -> elapsed is ~0; but the guard is gated on ast_retries>0
    # so it must not run on the first iteration regardless.
    commit_calls = []
    monkeypatch.setattr(orch, "_auto_commit_accepted",
                        lambda *a, **k: commit_calls.append(1) or True)

    rb_calls = {"n": 0}

    def _fake_run_both(*a, **k):
        rb_calls["n"] += 1
        # first call: both valid -> synthesis_success on attempt 0, no guard hit
        return ("def f():\n    return 1\n", "def f():\n    return 1\n")

    monkeypatch.setattr(orch, "run_both_agents", _fake_run_both)
    # validation passes (real _validate_submission on trivial code); fuzz path
    # would run — short-circuit by accepting at commit.
    monkeypatch.setattr(orch, "_save_final_output", lambda *a, **k: None)
    monkeypatch.setattr(ow, "_detect_and_append_untracked_tests", lambda *a, **k: None)
    # Force the bypass/fuzz path to accept deterministically:
    monkeypatch.setattr(orch, "_validate_submission", lambda code, agent, task: (True, []))

    import harness.diff_fuzzer as df

    class _FR:
        error = None
        equivalent = True
        failures = []

    monkeypatch.setattr("harness.diff_fuzzer.fuzz_from_task", lambda *a, **k: _FR())
    monkeypatch.setattr(orch, "_persist_fuzz_results", lambda *a, **k: None)

    rc = ow.main()
    # attempt 0 produced valid+equivalent -> accepted (0); guard never blocked it.
    assert rb_calls["n"] == 1, "attempt 0 must run synthesis without a budget pre-empt"
    assert rc == 0 and commit_calls, "valid attempt-0 submission should accept"


def test_T4_retry_module_path_has_no_budget_check():
    """GAP: synthesize_with_retries has no monotonic/budget/HARD_TIMEOUT guard.

    Flipping config synthesis.use_retry_module=True routes the worker through
    ast_retry.synthesize_with_retries, which loops max_ast_retries full synthesis
    windows with NO insufficient_time_for_retry guard. The RECONCILE budget work
    only protects the legacy inline else-branch."""
    src = inspect.getsource(ast_retry.synthesize_with_retries)
    for token in ("monotonic", "budget", "HARD_TIMEOUT", "worker_start", "remaining"):
        assert token not in src, (
            f"unexpected budget token {token!r} found — gap may be closed, "
            "update this test"
        )

    # And the worker's use_retry_module branch passes no budget params to it:
    worker_src = inspect.getsource(ow.main)
    # locate the use_retry_module call sites and confirm they don't thread budgets
    assert "synthesize_with_retries(" in worker_src
    # the budget locals only appear in the else-branch guard, never on the
    # synthesize_with_retries call line.
    for line in worker_src.splitlines():
        if "synthesize_with_retries(" in line:
            assert "HARD_TIMEOUT" not in line and "SYNTHESIS_WINDOW" not in line, (
                "GAP would be closed if budgets were threaded into the retry module"
            )
