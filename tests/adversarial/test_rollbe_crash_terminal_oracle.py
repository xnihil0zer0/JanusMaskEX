"""ROLLB-E (CRASH_SAFE_TERMINAL) orphan-routing oracle.

Targets ``harness.orchestrator_worker.main`` -- the durable per-task landing
path the autowork daemon spawns (``python -m harness.orchestrator_worker``).

main() atomically CLAIMS a task by renaming ``<id>.json`` ->
``<id>.json.processing`` (orchestrator_worker.py:131) and then runs the
pipeline. Every NON-crashing terminal calls either ``_mark_processed`` (accept /
decompose) or ``_mark_blocked`` (reject), each of which CONSUMES the
``.processing`` claim file. But an UNEXPECTED exception in the body is caught by
the broad ``except Exception`` arm, which sets ``exit_code=2`` and RETURNS
WITHOUT marking the task processed OR blocked. The task is left claimed as
``<id>.json.processing`` -- and ``get_next_task`` /
``collect_dispatchable_tasks`` glob ``*.json`` (NOT ``.processing``), so the
orphan is never re-dispatched in-process; recovery depends entirely on the
daemon's out-of-band ``_reclaim_orphan_processing`` sweep.

ROLLB-E adds a self-healing guard to main()'s ``finally``: on a non-success
exit, if the ``.processing`` claim file still exists (neither processed nor
blocked), route it to ``blocked/`` via ``_mark_blocked`` with a retry sidecar.

This oracle is NON-VACUOUS: it forces a crash AFTER the claim (by
monkeypatching ``orchestrator.prepare_task_prompt`` to raise) and asserts the
claimed task ends up in ``blocked/`` (re-claimable) with a retry sidecar, and
that NO orphan ``.processing`` file is left behind. On HEAD the finally does not
route the orphan, so the task is left as ``.processing`` (RED); with ROLLB-E it
lands in ``blocked/`` (GREEN).

No real agents are invoked -- the crash is injected before synthesis.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import harness.orchestrator as orch
import harness.orchestrator_worker as worker


def _write_config(tmp_path: Path) -> Path:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "synthesis:\n"
        "  timeout_seconds: 60\n"
        "  active_agents: [claude, gemini]\n"
        "  use_retry_module: false\n"
        "agent_sandbox:\n"
        "  enabled: false\n",
        encoding="utf-8",
    )
    return cfg


@pytest.fixture
def staged_task(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    tasks_dir = state_dir / "tasks"
    tasks_dir.mkdir(parents=True)
    task_id = "ROLLBE_CRASH"
    task = {
        "task_id": task_id,
        "files_touched": ["pkg/mod.py"],
        "verification_command": "true",
        "specification": "noop",
    }
    (tasks_dir / f"{task_id}.json").write_text(json.dumps(task), encoding="utf-8")
    cfg = _write_config(tmp_path)
    # Keep init/baseline machinery cheap and side-effect-free.
    monkeypatch.setattr(worker, "_precompute_baseline_test_results",
                        lambda *a, **k: None)
    return state_dir, tasks_dir, task_id, cfg


class TestRollbECrashRoutesOrphanToBlocked:
    def test_crash_after_claim_routes_to_blocked(self, staged_task, monkeypatch):
        state_dir, tasks_dir, task_id, cfg = staged_task

        # Crash AFTER the .processing claim: prepare_task_prompt is the first
        # body call after the rename + current_task write.
        def _boom(_task):
            raise RuntimeError("simulated worker crash after claim")
        monkeypatch.setattr(orch, "prepare_task_prompt", _boom)

        argv = ["prog", "--state-dir", str(state_dir),
                "--task-id", task_id, "--config", str(cfg)]
        monkeypatch.setattr("sys.argv", argv)

        rc = worker.main()
        assert rc == 2, "an unexpected crash must exit non-zero (error)"

        # The claim file must NOT be left as an orphan .processing.
        orphans = list(tasks_dir.glob(f"*{task_id}.json.processing"))
        assert not orphans, (
            f"ROLLB-E: task left as orphan .processing (neither processed nor "
            f"blocked): {[p.name for p in orphans]}")

        # It must land in blocked/ (re-claimable) -- NOT processed/.
        blocked = tasks_dir / "blocked" / f"{task_id}.json"
        processed = tasks_dir / "processed" / f"{task_id}.json"
        assert blocked.exists(), (
            "ROLLB-E: crashed task must be routed to blocked/ for retry")
        assert not processed.exists(), (
            "ROLLB-E: a crashed (non-accepted) task must NOT be parked in "
            "processed/ (zombie)")

        # A retry sidecar must accompany it so the daemon's retry budget applies.
        sidecar = tasks_dir / "blocked" / f"{task_id}.retry.json"
        assert sidecar.exists(), "ROLLB-E: blocked task must carry a retry sidecar"
        meta = json.loads(sidecar.read_text(encoding="utf-8"))
        assert meta.get("attempts", 0) >= 1
        assert meta.get("last_outcome") == "worker_crash_orphan"


class TestRollbESuccessNotDoubleRouted:
    """Regression guard: a CLEANLY-rejected task (exit_code=1, already routed to
    blocked/ by the body) must not be double-bumped by the finally guard."""

    def test_clean_reject_single_blocked_sidecar(self, tmp_path, monkeypatch):
        # A harness_plumbing task bypasses fuzzing + smoke; stub both agents to
        # submit valid code and force _auto_commit_accepted to return False so
        # the body routes cleanly to blocked('auto_commit_failed') and returns 1.
        # The finally guard must then be a NO-OP (the .processing file is already
        # consumed), leaving exactly ONE block-route (sidecar attempts == 1) with
        # the body's outcome -- never overwritten by the guard.
        state_dir = tmp_path / "state"
        tasks_dir = state_dir / "tasks"
        tasks_dir.mkdir(parents=True)
        task_id = "ROLLBE_REJECT"
        task = {
            "task_id": task_id,
            "files_touched": ["pkg/mod.py"],
            "verification_command": "true",
            "specification": "noop",
            "meta_task_type": "harness_plumbing",
        }
        (tasks_dir / f"{task_id}.json").write_text(json.dumps(task), encoding="utf-8")
        cfg = _write_config(tmp_path)
        monkeypatch.setattr(worker, "_precompute_baseline_test_results",
                            lambda *a, **k: None)
        monkeypatch.setattr(orch, "prepare_task_prompt", lambda _t: "PROMPT")
        monkeypatch.setattr(orch, "run_both_agents",
                            lambda *a, **k: ("def f():\n    return 1\n",
                                             "def f():\n    return 1\n"))
        monkeypatch.setattr(orch, "_validate_submission", lambda *a, **k: (True, []))
        monkeypatch.setattr(orch, "_save_final_output", lambda *a, **k: None)
        # Bypass HITL await + the actual commit; force a clean auto-commit reject.
        monkeypatch.setattr(orch, "_auto_commit_accepted", lambda *a, **k: False)
        monkeypatch.setattr(worker, "_consume_no_diff_marker", lambda *a, **k: False)
        monkeypatch.setattr(worker, "_detect_and_append_untracked_tests",
                            lambda *a, **k: None)
        import harness.control_gate as cg
        monkeypatch.setattr(cg, "await_decision", lambda *a, **k: "accept")

        argv = ["prog", "--state-dir", str(state_dir),
                "--task-id", task_id, "--config", str(cfg)]
        monkeypatch.setattr("sys.argv", argv)

        rc = worker.main()
        assert rc == 1, f"clean auto-commit reject must exit 1; got {rc}"

        orphans = list(tasks_dir.glob(f"*{task_id}.json.processing"))
        assert not orphans
        blocked = tasks_dir / "blocked" / f"{task_id}.json"
        assert blocked.exists()
        sidecar = tasks_dir / "blocked" / f"{task_id}.retry.json"
        meta = json.loads(sidecar.read_text(encoding="utf-8"))
        assert meta.get("attempts") == 1, (
            "ROLLB-E: a cleanly-rejected task must be block-routed exactly once "
            f"(body), not double-bumped by the finally guard: {meta}")
        assert meta.get("last_outcome") == "auto_commit_failed", (
            f"finally guard must not overwrite the body's block outcome: {meta}")
