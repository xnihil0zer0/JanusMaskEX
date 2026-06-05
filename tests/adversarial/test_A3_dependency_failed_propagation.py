"""A3 — a dependent of a terminally-failed (.exhausted) dep must be terminally
blocked, not hung forever.

Blocker-3 root cause: the dep gates in both dispatch paths
(orchestrator.get_next_task and autowork_daemon.collect_dispatchable_tasks) treat
a dependency as met ONLY when it is ACCEPTED. A dep whose retry budget is
exhausted (blocked/<dep>.exhausted marker, written by
autowork_daemon._retry_blocked_tasks) is never accepted, so its dependent is
neither dispatchable nor blocked -> the dispatch loop skips it forever and the
single-task worker times out. Both seams must terminalize the dependent
(route to blocked/ + its own .exhausted, no futile retry/escalation).

  A3a — orchestrator.get_next_task: candidate depends on a terminally-failed dep
        -> NOT returned; routed to blocked/ with blocked/<id>.exhausted.
  A3b — get_next_task: dep merely UNMET (not accepted, not exhausted) -> candidate
        skipped but NOT blocked (stays queued; existing behavior preserved).
  A3c — get_next_task: dep ACCEPTED -> candidate returned (regression guard).
  A3d — daemon._block_dependency_failed_tasks: routes a dependent of an exhausted
        dep to blocked/ + .exhausted; returns the count.
  A3e — daemon sweep: no exhausted deps -> no-op (returns 0, task untouched).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import harness.orchestrator as orch
import harness.autowork_daemon as daemon


def _task(tid, deps=None):
    return {
        "task_id": tid,
        "title": tid,
        "meta_task_type": "refactor",
        "dependencies": deps or [],
        "files_touched": [f"harness/{tid}.py"],
        "verification_command": "true",
    }


def _seed_task(tasks_dir: Path, tid, deps=None):
    tasks_dir.mkdir(parents=True, exist_ok=True)
    (tasks_dir / f"{tid}.json").write_text(json.dumps(_task(tid, deps)))


def _mark_exhausted(state_dir: Path, dep_id):
    blocked = state_dir / "tasks" / "blocked"
    blocked.mkdir(parents=True, exist_ok=True)
    (blocked / f"{dep_id}.json").write_text(json.dumps(_task(dep_id)))
    (blocked / f"{dep_id}.exhausted").write_text("1")


def _accept(state_dir: Path, tid):
    row = {"phase": "accepted", "event": "auto_commit", "task_id": tid}
    with open(state_dir / "impl_progress.jsonl", "a") as f:
        f.write(json.dumps(row) + "\n")


# ---------------- orchestrator.get_next_task ----------------

def test_A3a_get_next_task_blocks_dependent_of_exhausted_dep(tmp_path):
    sd = tmp_path / "state"
    (sd / "tasks").mkdir(parents=True)
    _seed_task(sd / "tasks", "B", deps=["A"])
    _mark_exhausted(sd, "A")

    chosen = orch.get_next_task(sd)
    assert chosen is None, "dependent of an exhausted dep must not be dispatched"
    # B routed out of the live queue, into blocked/ with its own terminal marker
    assert not (sd / "tasks" / "B.json").exists()
    assert (sd / "tasks" / "blocked" / "B.json").exists()
    assert (sd / "tasks" / "blocked" / "B.exhausted").exists(), \
        "dependent must be terminally marked so it is never re-staged"


def test_A3b_get_next_task_unmet_but_not_terminal_is_skipped_not_blocked(tmp_path):
    sd = tmp_path / "state"
    (sd / "tasks").mkdir(parents=True)
    _seed_task(sd / "tasks", "B", deps=["A"])  # A neither accepted nor exhausted

    chosen = orch.get_next_task(sd)
    assert chosen is None
    # B is skipped but remains queued (could become runnable once A is accepted)
    assert (sd / "tasks" / "B.json").exists()
    assert not (sd / "tasks" / "blocked" / "B.exhausted").exists()


def test_A3c_get_next_task_accepted_dep_dispatches(tmp_path):
    sd = tmp_path / "state"
    (sd / "tasks").mkdir(parents=True)
    _seed_task(sd / "tasks", "B", deps=["A"])
    _accept(sd, "A")

    chosen = orch.get_next_task(sd)
    assert chosen is not None and chosen.get("task_id") == "B", \
        "an accepted dependency must let the dependent dispatch normally"


# ---------------- autowork_daemon sweep ----------------

def test_A3d_daemon_blocks_dependent_of_exhausted_dep(tmp_path):
    sd = tmp_path / "state"
    (sd / "tasks").mkdir(parents=True)
    _seed_task(sd / "tasks", "C", deps=["A"])
    _mark_exhausted(sd, "A")

    summary = {}
    n = daemon._block_dependency_failed_tasks(sd, summary)
    assert n == 1
    assert not (sd / "tasks" / "C.json").exists()
    assert (sd / "tasks" / "blocked" / "C.json").exists()
    assert (sd / "tasks" / "blocked" / "C.exhausted").exists()


def test_A3e_daemon_sweep_noop_without_exhausted(tmp_path):
    sd = tmp_path / "state"
    (sd / "tasks").mkdir(parents=True)
    _seed_task(sd / "tasks", "C", deps=["A"])  # A not exhausted

    n = daemon._block_dependency_failed_tasks(sd, {})
    assert n == 0
    assert (sd / "tasks" / "C.json").exists(), "task with no terminal dep is untouched"
