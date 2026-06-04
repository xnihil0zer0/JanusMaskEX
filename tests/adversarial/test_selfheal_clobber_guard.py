"""Self-heal Clobber Guard oracle: asserts that self-heal plan correction is not clobbered
by original allowlisted plans, and that exhausted tasks are not re-staged.
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
        "# Title\nCorrected spec: edit the target directly; do NOT use eval/exec/decorators.\n# Objective\nCORRECTED\n",
        encoding="utf-8",
    )

def _patch_workroot(monkeypatch, workroot: pathlib.Path) -> None:
    monkeypatch.setattr(_paths, "agent_workroot", lambda: workroot)
    if hasattr(d, "agent_workroot"):
        monkeypatch.setattr(d, "agent_workroot", lambda: workroot)

def test_selfheal_clobber_guard(tmp_path, monkeypatch) -> None:
    # 1. Setup paths
    workroot = tmp_path / "agentwork"
    workroot.mkdir()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    state_dir = tmp_path / "state"
    (state_dir / "tasks").mkdir(parents=True)
    (state_dir / "tasks" / "blocked").mkdir(parents=True)
    (state_dir / "control" / "autowork").mkdir(parents=True)

    # 2. Seed configuration and environment for self-heal secret
    config = {"autowork": {"selfheal_auto_promote": True}}
    secret_file = tmp_path / "selfheal_secret"
    monkeypatch.setenv("JANUSMASK_SELFHEAL_SECRET_PATH", str(secret_file))

    # 3. Seed fix brief in agent outbox
    tid = "my_task_id"
    _seed_outbox(workroot, "claude", tid)
    _patch_workroot(monkeypatch, workroot)

    # 4. Seed realistic post-escalation blocked state so harvest can read task properties
    blocked_task_path = state_dir / "tasks" / "blocked" / f"{tid}.json"
    blocked_task_data = {
        "task_id": tid,
        "meta_task_type": "harness_self_fix",
        "dependencies": [],
        "files_touched": ["harness/autowork_daemon.py"],
        "objective": "CORRECTED"
    }
    blocked_task_path.write_text(json.dumps(blocked_task_data, indent=2), encoding="utf-8")

    retry_path = state_dir / "tasks" / "blocked" / f"{tid}.retry.json"
    retry_path.write_text(
        json.dumps({"attempts": 1, "last_outcome": "synthesis_or_ast_failed", "ts": time.time()}),
        encoding="utf-8",
    )

    exhausted_path = state_dir / "tasks" / "blocked" / f"{tid}.exhausted"
    exhausted_path.write_text("1", encoding="utf-8")

    # 5. Seed an ALLOWLISTED original brief with older mtime
    orig_slug = "original_brief"
    orig_brief_path = repo_root / f"brief_hooks_{orig_slug}.md"
    orig_brief_path.write_text("# Original Brief\n", encoding="utf-8")

    orig_plan_path = repo_root / f"plan_hooks_{orig_slug}.json"
    orig_plan_data = {
        "tasks": [
            {
                "task_id": tid,
                "meta_task_type": "harness_self_fix",
                "dependencies": [],
                "objective": "ORIGINAL"
            }
        ]
    }
    orig_plan_path.write_text(json.dumps(orig_plan_data, indent=2), encoding="utf-8")

    # Allowlist the original brief slug
    allowlist_path = state_dir / "control" / "autowork" / "auto_promote.allowlist"
    allowlist_path.write_text(f"{orig_slug}\n", encoding="utf-8")

    # Force original brief to have an older mtime so selfheal brief comes first in sorted records
    past_time = time.time() - 3600
    import os
    os.utime(orig_brief_path, (past_time, past_time))
    os.utime(orig_plan_path, (past_time, past_time))

    # 6. Drive ONE auto-promote tick
    d._auto_promote(repo_root, state_dir, config)

    # 7. Assertions
    staged_task_path = state_dir / "tasks" / f"{tid}.json"
    assert staged_task_path.exists(), "The task must be staged"
    
    staged_content = json.loads(staged_task_path.read_text(encoding="utf-8"))
    
    # Assert that the task's objective corresponds to the CORRECTED selfheal task, NOT the original.
    # On HEAD: the original clobbers -> staged objective is "ORIGINAL" -> RED.
    # After the fix: original is skipped -> staged objective remains "CORRECTED" -> GREEN.
    assert staged_content.get("objective") == "CORRECTED", (
        f"Clobber detected: expected task objective 'CORRECTED', but found '{staged_content.get('objective')}'"
    )

def test_retry_exhausted_clobber_guard(tmp_path) -> None:
    # Set up paths
    state_dir = tmp_path / "state"
    tasks_dir = state_dir / "tasks"
    blocked_dir = tasks_dir / "blocked"
    blocked_dir.mkdir(parents=True)
    
    tid = "retry_task_id"
    
    # Seed blocked task JSON
    (blocked_dir / f"{tid}.json").write_text(
        json.dumps({"task_id": tid, "objective": "TEST"}, indent=2), encoding="utf-8"
    )
    # Seed retry state: 3 attempts, last outcome "unknown"
    # mtime threshold for 3 attempts is 86400, so we make ts very old
    (blocked_dir / f"{tid}.retry.json").write_text(
        json.dumps({"attempts": 3, "last_outcome": "unknown", "ts": time.time() - 100000.0}), encoding="utf-8"
    )
    # Seed exhausted marker
    (blocked_dir / f"{tid}.exhausted").write_text("1", encoding="utf-8")
    
    # Drive _retry_blocked_tasks with max_attempts = 5
    summary = {}
    from harness.autowork_daemon import _retry_blocked_tasks
    res = _retry_blocked_tasks(state_dir, summary, max_attempts=5)
    
    # Assertions
    # In old code: attempts (3) < effective_max (5), so it would be re-staged (res = 1, tasks/retry_task_id.json exists)
    # In new code: it is skipped (res = 0, tasks/retry_task_id.json does not exist)
    staged_path = tasks_dir / f"{tid}.json"
    assert not staged_path.exists(), "Exhausted task should not be re-staged even with higher max_attempts"
    assert res == 0, "Expected 0 tasks re-staged"
