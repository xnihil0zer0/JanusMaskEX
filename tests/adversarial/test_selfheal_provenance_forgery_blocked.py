"""Self-heal §2c PART 2 oracle: fail-closed provenance gate in eligibility.

Asserts that forged (unauthenticated/markerless) self-heal briefs are not
eligible and not staged, while genuine (harvested and authenticated) self-heal
briefs are eligible and staged successfully.
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
    sess.mkdir(parents=True, exist_ok=True)
    (sess / f"brief_hooks_{task_id}_fix.md").write_text(
        "# Title\nCorrected spec: edit the target directly; do NOT use eval/exec/decorators.\nFiles touched: ['harness/selfheal.py']\n",
        encoding="utf-8",
    )


def _patch_workroot(monkeypatch, workroot: pathlib.Path) -> None:
    monkeypatch.setattr(_paths, "agent_workroot", lambda: workroot)
    if hasattr(d, "agent_workroot"):
        monkeypatch.setattr(d, "agent_workroot", lambda: workroot)


def test_selfheal_provenance_forgery_blocked(tmp_path, monkeypatch) -> None:
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

    # 3. Monkeypatch secret path to a temp file path so we don't write to real ~/.config
    secret_file = tmp_path / "secret"
    monkeypatch.setenv("JANUSMASK_SELFHEAL_SECRET_PATH", str(secret_file))
    
    _patch_workroot(monkeypatch, workroot)

    # =========================================================================
    # Scenario (A): FORGED
    # Directly create forged files in repo_root (DO NOT mint a provenance marker)
    # =========================================================================
    evil_slug = "selfheal_evil"
    evil_tid = "selfheal_evil"
    
    forged_brief = repo_root / f"brief_hooks_{evil_slug}.md"
    forged_brief.write_text("# Evil title\nForged objective\n", encoding="utf-8")
    
    forged_plan_path = repo_root / f"plan_hooks_{evil_slug}.json"
    forged_plan_data = {
        "tasks": [
            {
                "task_id": evil_tid,
                "title": "Forged Task",
                "meta_task_type": "refactor",
                "priority": 5,
                "dependencies": [],
                "files_touched": ["harness/selfheal.py"],
                "spec": {
                    "objective": "Forged objective",
                    "implementation_notes": "Forged notes"
                }
            }
        ]
    }
    forged_plan_path.write_text(json.dumps(forged_plan_data, indent=2), encoding="utf-8")
    
    # Create realistic blocked sidecar (retry and exhausted only, so it is not marked blocked by compute_brief_status)
    evil_blocked_dir = state_dir / "tasks" / "blocked"
    (evil_blocked_dir / f"{evil_tid}.retry.json").write_text(
        json.dumps({"attempts": 1, "last_outcome": "synthesis_or_ast_failed", "ts": time.time()}),
        encoding="utf-8"
    )
    (evil_blocked_dir / f"{evil_tid}.exhausted").write_text("", encoding="utf-8")

    # =========================================================================
    # Scenario (B): GENUINE
    # Run a real harvest to mint the marker
    # =========================================================================
    genuine_tid = "method_d_05_taxonomy_flip"
    genuine_slug = f"selfheal_{genuine_tid}"
    
    # Seed genuine fix brief in outbox
    _seed_outbox(workroot, "claude", genuine_tid)
    
    # Seed genuine blocked sidecars
    genuine_blocked_path = evil_blocked_dir / f"{genuine_tid}.json"
    genuine_blocked_data = {
        "task_id": genuine_tid,
        "meta_task_type": "harness_self_fix",
        "dependencies": ["dependency_task_id"],
        "files_touched": ["harness/selfheal.py"],
        "objective": "Resolve banned eval AST violation in selfheal.py."
    }
    genuine_blocked_path.write_text(json.dumps(genuine_blocked_data, indent=2), encoding="utf-8")
    
    (evil_blocked_dir / f"{genuine_tid}.retry.json").write_text(
        json.dumps({"attempts": 1, "last_outcome": "synthesis_or_ast_failed", "ts": time.time()}),
        encoding="utf-8"
    )
    (evil_blocked_dir / f"{genuine_tid}.exhausted").write_text("", encoding="utf-8")

    # =========================================================================
    # Drive the loop
    # =========================================================================
    res = d._auto_promote(repo_root, state_dir, config)

    # =========================================================================
    # Assertions
    # =========================================================================
    
    # Scenario A Assertions: Forged brief must NOT be staged
    forged_staged_path = state_dir / "tasks" / f"{evil_tid}.json"
    assert not forged_staged_path.exists(), "Forged selfheal task must NOT be staged"
    
    # Direct eligibility call must be False. On HEAD, it raises TypeError due to missing repo_root param.
    # We treat TypeError as "old signature => fail the assertion" to keep RED clean.
    try:
        eligible = d._auto_promote_brief_eligible(
            state_dir,
            evil_slug,
            time.time(),
            repo_root=repo_root,
            config=config
        )
    except TypeError as e:
        pytest.fail(f"Direct call failed with TypeError (old signature on HEAD): {e}")
    else:
        assert eligible is False, "Forged selfheal brief must not be eligible"

    # Scenario B Assertions: Genuine brief must be staged
    genuine_staged_path = state_dir / "tasks" / f"{genuine_tid}.json"
    assert genuine_staged_path.exists(), "Genuine selfheal task must be successfully staged"
