"""Self-heal Link #2d oracle: asserts content-aware brief refresh on changed diagnosis.

Asserts that when a self-heal brief in the agent outbox has changed content,
the harvest process refreshes the destination brief in repo_root, re-runs
plan synthesis, clears the plan-attempts markers, and re-evicts the blocked sidecars.
"""
from __future__ import annotations

import json
import pathlib
import time
import pytest

import harness.paths as _paths
from harness import autowork_daemon as d


def _seed_outbox(workroot: pathlib.Path, agent: str, task_id: str, content: str) -> None:
    sess = workroot / agent / f"{agent}-r1-{task_id}-cafef00d" / "outbox"
    sess.mkdir(parents=True, exist_ok=True)
    (sess / f"brief_hooks_{task_id}_fix.md").write_text(content, encoding="utf-8")


def _patch_workroot(monkeypatch, workroot: pathlib.Path) -> None:
    monkeypatch.setattr(_paths, "agent_workroot", lambda: workroot)
    if hasattr(d, "agent_workroot"):
        monkeypatch.setattr(d, "agent_workroot", lambda: workroot)


def test_selfheal_plan_refresh_on_changed_diagnosis(tmp_path, monkeypatch) -> None:
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

    # 3. Seed initial fix brief in outbox
    tid = "method_d_05_taxonomy_flip"
    content_a = "# Title\nGoal: First objective.\nFiles touched: ['harness/selfheal.py']\nCorrective constraint: constraint A\n"
    _seed_outbox(workroot, "claude", tid, content_a)
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
    retry_path.write_text(
        json.dumps({"attempts": 1, "last_outcome": "synthesis_or_ast_failed", "ts": time.time()}),
        encoding="utf-8",
    )

    exhausted_path = state_dir / "tasks" / "blocked" / f"{tid}.exhausted"
    exhausted_path.write_text("", encoding="utf-8")

    # 5. Drive the loop for the first harvest
    res = d._auto_promote(repo_root, state_dir, config)

    # Verify initial delivery
    dest = repo_root / f"brief_hooks_selfheal_{tid}.md"
    assert dest.exists()
    assert dest.read_text(encoding="utf-8") == content_a

    plan_path = repo_root / f"plan_hooks_selfheal_{tid}.json"
    assert plan_path.exists()
    plan_data = json.loads(plan_path.read_text(encoding="utf-8"))
    assert plan_data["tasks"][0]["objective"] == "First objective."

    # Sidecars must be gone
    assert not blocked_task_path.exists()
    assert not retry_path.exists()
    assert not exhausted_path.exists()

    # 6. Change the source brief to content B (different content)
    content_b = "# Title\nGoal: Second objective.\nFiles touched: ['harness/selfheal.py']\nCorrective constraint: constraint B\n"
    _seed_outbox(workroot, "claude", tid, content_b)

    # 7. Seed stale plan attempts files so we can verify they get cleared
    attempt_path_1 = state_dir / "plan_attempts" / f"selfheal_{tid}.json"
    attempt_path_1.parent.mkdir(parents=True, exist_ok=True)
    attempt_path_1.write_text(json.dumps({"attempts": 1, "last_outcome": "failed"}), encoding="utf-8")

    attempt_path_2 = state_dir / "control" / "autowork" / "plan_attempts" / f"selfheal_{tid}.json"
    attempt_path_2.parent.mkdir(parents=True, exist_ok=True)
    attempt_path_2.write_text(json.dumps({"attempts": 1, "last_outcome": "failed"}), encoding="utf-8")

    # 8. Re-seed blocked state (since the daemon needs it to re-synthesize plan)
    blocked_task_path.write_text(json.dumps(blocked_task_data, indent=2), encoding="utf-8")
    retry_path.write_text(
        json.dumps({"attempts": 1, "last_outcome": "synthesis_or_ast_failed", "ts": time.time()}),
        encoding="utf-8",
    )
    exhausted_path.write_text("", encoding="utf-8")

    # 9. Drive the loop again
    res2 = d._auto_promote(repo_root, state_dir, config)

    # 10. ASSERTIONS FOR REFRESH
    # (a) Destination brief must match content B (refreshed)
    assert dest.read_text(encoding="utf-8") == content_b, "Destination brief should be refreshed with content B"

    # (b) Plan must be rewritten with refreshed objective
    plan_data_refreshed = json.loads(plan_path.read_text(encoding="utf-8"))
    assert plan_data_refreshed["tasks"][0]["objective"] == "Second objective.", "Synthesized plan should have been updated"

    # (c) Stale plan-attempts marker state/plan_attempts/selfheal_<tid>.json must be cleared
    assert not attempt_path_1.exists(), "Plan attempt marker under state_dir/plan_attempts must be cleared"
    assert not attempt_path_2.exists(), "Plan attempt marker under state_dir/control/autowork/plan_attempts must be cleared"

    # (d) Sidecars must be evicted again
    assert not blocked_task_path.exists(), "Blocked task sidecar must be unlinked after refresh"
    assert not retry_path.exists(), "Retry sidecar must be unlinked after refresh"
    assert not exhausted_path.exists(), "Exhausted sidecar must be unlinked after refresh"
