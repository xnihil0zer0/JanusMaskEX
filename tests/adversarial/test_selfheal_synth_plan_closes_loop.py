"""Self-heal Loop Closure oracle: asserts that the self-heal loop closes
without invoking the planner subprocess, by synthesizing plan_hooks_selfheal_<tid>.json
during harvest and evicting the blocked sidecars.

RED on HEAD: plan_hooks_selfheal_<tid>.json is never synthesized, and the blocked sidecars
prevent compute_brief_status from staging the task.
"""
from __future__ import annotations

import json
import pathlib
import time

import pytest

import harness.paths as _paths
from harness import autowork_daemon as d


def _seed_outbox(workroot: pathlib.Path, agent: str, task_id: str) -> None:
    sess = workroot / agent / f"{agent}-r1-{task_id}-cafef00d" / "outbox"
    sess.mkdir(parents=True)
    (sess / f"brief_hooks_{task_id}_fix.md").write_text(
        "# Title\nCorrected spec: edit the target directly; do NOT use eval/exec/decorators.\n",
        encoding="utf-8",
    )


def _patch_workroot(monkeypatch, workroot: pathlib.Path) -> None:
    monkeypatch.setattr(_paths, "agent_workroot", lambda: workroot)
    if hasattr(d, "agent_workroot"):
        monkeypatch.setattr(d, "agent_workroot", lambda: workroot)


def test_selfheal_synth_plan_closes_loop(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("JANUSMASK_SELFHEAL_SECRET_PATH", str(tmp_path / "selfheal_hmac_secret"))
    # 1. Setup paths
    workroot = tmp_path / "agentwork"
    workroot.mkdir()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    state_dir = tmp_path / "state"
    (state_dir / "tasks").mkdir(parents=True)
    (state_dir / "tasks" / "blocked").mkdir(parents=True)
    (state_dir / "control" / "autowork").mkdir(parents=True)

    # 2. Seed configuration
    config = {"autowork": {"selfheal_auto_promote": True}}

    # 3. Seed fix brief in outbox
    tid = "method_d_05_taxonomy_flip"
    _seed_outbox(workroot, "claude", tid)
    _patch_workroot(monkeypatch, workroot)

    # 4. Seed realistic post-escalation blocked state
    blocked_task_path = state_dir / "tasks" / "blocked" / f"{tid}.json"
    blocked_task_data = {
        "task_id": tid,
        "meta_task_type": "harness_self_fix",
        "dependencies": ["dependency_task_id"],
        "files_touched": ["harness/selfheal.py"],
        "objective": "Resolve banned eval AST violation in selfheal.py."
    }
    blocked_task_path.write_text(json.dumps(blocked_task_data, indent=2), encoding="utf-8")

    retry_path = state_dir / "tasks" / "blocked" / f"{tid}.retry.json"
    # Seed the genuinely-exhausted post-escalation state: attempts=1 with a
    # deterministic last_outcome -> effective_max=1 -> attempts >= effective_max
    # -> _retry_blocked_tasks `continue`s without re-staging, so the blocked
    # sidecar survives for harvest's _synthesize_selfheal_plan to read.
    retry_path.write_text(
        json.dumps({"attempts": 1, "last_outcome": "synthesis_or_ast_failed", "ts": time.time()}),
        encoding="utf-8",
    )

    exhausted_path = state_dir / "tasks" / "blocked" / f"{tid}.exhausted"
    exhausted_path.write_text("", encoding="utf-8")

    # 5. Drive the loop
    res = d._auto_promote(repo_root, state_dir, config)

    # 6. ASSERTIONS
    # (a) plan_hooks_selfheal_<tid>.json exists
    plan_path = repo_root / f"plan_hooks_selfheal_{tid}.json"
    assert plan_path.exists(), "plan_hooks_selfheal_<tid>.json must be synthesized"

    # (b) its tasks[0].task_id == <tid>
    plan_data = json.loads(plan_path.read_text(encoding="utf-8"))
    assert "tasks" in plan_data and len(plan_data["tasks"]) == 1, "Plan must contain exactly one task"
    assert plan_data["tasks"][0]["task_id"] == tid, "Task ID must be the original inner task ID"
    assert plan_data["tasks"][0]["meta_task_type"] == "harness_self_fix", "Should preserve meta_task_type"
    assert plan_data["tasks"][0]["dependencies"] == ["dependency_task_id"], "Should preserve dependencies"

    # (c) all three blocked sidecars are GONE (C1 eviction check)
    assert not blocked_task_path.exists(), "Blocked JSON sidecar must be unlinked"
    assert not retry_path.exists(), "Retry JSON sidecar must be unlinked"
    assert not exhausted_path.exists(), "Exhausted sidecar must be unlinked"

    # (d) state/tasks/<tid>.json exists (staged)
    staged_task_path = state_dir / "tasks" / f"{tid}.json"
    assert staged_task_path.exists(), "Task must be successfully staged under state/tasks/<tid>.json"

    # (e) NO state/plan_attempts/selfheal_<tid>.json exists (planner subprocess never ran)
    attempt_path = state_dir / "plan_attempts" / f"selfheal_{tid}.json"
    assert not attempt_path.exists(), "Planner subprocess must not be run"
