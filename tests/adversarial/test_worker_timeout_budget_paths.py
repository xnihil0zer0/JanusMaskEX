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


def test_T4_retry_module_path_has_budget_guard():
    """FIX-DETECTOR (GAP_H4 option-a inverted): synthesize_with_retries now derives
    a per-call wall budget from ``config`` (synthesis.timeout_seconds) and bails
    before starting a retry window it cannot afford, emitting/returning rather than
    looping ``max_ast_retries`` full synthesis windows unguarded. The
    RECONCILE_TIMEOUT_BUDGETS protection (8dac6e1) no longer vanishes when
    ``use_retry_module=True``. Goes RED on the unguarded source.

    Contract for the reconstruction: the function uses ``import time`` /
    ``time.monotonic()`` (module-level), so the budget clock is patchable here.
    """
    import time as _time
    import unittest.mock as _mock

    src = inspect.getsource(ast_retry.synthesize_with_retries)
    assert "monotonic" in src, "no monotonic clock — per-call budget guard absent"
    assert ("_compute_timeout_budgets" in src or "timeout_seconds" in src), (
        "budget not derived from config (expected _compute_timeout_budgets or "
        "synthesis.timeout_seconds)")
    assert any(t in src for t in ("remaining", "budget", "SYNTHESIS_WINDOW", "window")), (
        "no remaining-budget comparison before the retry window")
    # The module must expose ``time`` for the clock to be patchable (import time).
    assert hasattr(ast_retry, "time"), (
        "ast_retry must 'import time' (module-level) so time.monotonic is patchable")

    # Behavioral: with the wall budget already blown, the loop bails EARLY instead
    # of running all max_ast_retries unguarded windows. run_agent_func returns None
    # so an unguarded loop would call it max_ast_retries times.
    calls = {"n": 0}

    def run_agent(*a, **k):
        calls["n"] += 1
        return None

    cfg = {"synthesis": {"timeout_seconds": 100, "max_ast_retries": 5}}
    seq = {"i": 0}

    def fake_monotonic():
        # First two reads (function entry + attempt-0 elapsed) are at t=0 so the
        # fresh first synthesis is never pre-empted; later reads jump far past the
        # hard budget so any RETRY check trips the guard.
        seq["i"] += 1
        return 0.0 if seq["i"] <= 2 else 10_000.0

    with _mock.patch.object(ast_retry.time, "monotonic", fake_monotonic):
        ok, code, viol = ast_retry.synthesize_with_retries(
            "claude", "p", cfg, Path("."), 1, {"task_id": "T"},
            run_agent, lambda c, t: (False, ["v"]))

    assert ok is False, "exhausted-budget run must report failure"
    assert 1 <= calls["n"] < 5, (
        f"budget guard did not curtail the retry loop (ran {calls['n']}/5 windows); "
        "attempt 0 must run, later retries must be cut off")

    # The worker still calls it (wiring intact); the per-call guard lives INSIDE the
    # function now, so no budget params need threading at the call site.
    worker_src = inspect.getsource(ow.main)
    assert "synthesize_with_retries(" in worker_src
