"""RED-on-HEAD oracle test for BRIEF_ZOMBIE_RECLAMATION.

Objective: Add a NEW top-level helper `_reclaim_zombie_briefs(repo_root, state_dir)` to
harness/autowork_daemon.py that quarantines zombie briefs, and invoke it once per `_iteration`.
"""
from __future__ import annotations

import json
import pathlib
import pytest
import shutil

from harness import autowork_daemon as ad
from harness.brief_status import compute_brief_status


def _write_brief_and_plan(repo_root: pathlib.Path, slug: str, task_ids: list[str]) -> None:
    (repo_root / f"brief_hooks_{slug}.md").write_text("# brief\n", encoding="utf-8")
    plan = {"tasks": [{"task_id": t} for t in task_ids]}
    (repo_root / f"plan_hooks_{slug}.json").write_text(json.dumps(plan), encoding="utf-8")


def test_zombie_brief_is_quarantined(tmp_path: pathlib.Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    state_dir = tmp_path / "state"
    
    # Build repo_root + state_dir structure
    (state_dir / "tasks" / "processed").mkdir(parents=True)
    
    # Brief slug 'zomb' with one task T1 parked in state/tasks/processed/T1.json
    # and NO accepted ledger row.
    _write_brief_and_plan(repo_root, "zomb", ["T1"])
    (state_dir / "tasks" / "processed" / "T1.json").write_text("{}", encoding="utf-8")
    
    # Assert compute_brief_status reports state=='zombie' (precondition)
    records = compute_brief_status(repo_root, state_dir)
    assert len(records) == 1, f"Expected one brief record, got {len(records)}"
    r = records[0]
    assert r["slug"] == "zomb"
    assert r["state"] == "zombie", (
        f"Precondition failed: Expected state 'zombie', got {r['state']!r}"
    )
    
    # Call ad._reclaim_zombie_briefs(repo_root, state_dir)
    ad._reclaim_zombie_briefs(repo_root, state_dir)
    
    # Assert the brief file repo_root/'brief_hooks_zomb.md' NO LONGER exists at its original path
    original_brief = repo_root / "brief_hooks_zomb.md"
    assert not original_brief.exists(), "Zombie brief file still exists at its original path"
    
    # Assert it now exists under state_dir/'control'/'autowork'/'quarantine'/'brief_hooks_zomb.md'
    quarantined_brief = state_dir / "control" / "autowork" / "quarantine" / "brief_hooks_zomb.md"
    assert quarantined_brief.exists(), "Zombie brief file not found in quarantine directory"
    
    # Assert parked marker state_dir/'tasks'/'processed'/'T1.json' was unlinked
    parked_marker = state_dir / "tasks" / "processed" / "T1.json"
    assert not parked_marker.exists(), "Parked task marker was not unlinked"


def test_healthy_brief_untouched(tmp_path: pathlib.Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    state_dir = tmp_path / "state"
    
    # Build repo_root + state_dir structure
    (state_dir / "tasks").mkdir(parents=True)
    
    # Brief slug 'ok' with one queued task T1 (state/tasks/T1.json), no parked markers
    _write_brief_and_plan(repo_root, "ok", ["T1"])
    (state_dir / "tasks" / "T1.json").write_text("{}", encoding="utf-8")
    
    # Assert compute_brief_status reports state=='queued' or 'in_flight' (NOT zombie)
    records = compute_brief_status(repo_root, state_dir)
    assert len(records) == 1
    r = records[0]
    assert r["slug"] == "ok"
    assert r["state"] in ("queued", "in_flight"), f"Expected state queued or in_flight, got {r['state']!r}"
    assert r["state"] != "zombie"
    
    # Call ad._reclaim_zombie_briefs(repo_root, state_dir)
    ad._reclaim_zombie_briefs(repo_root, state_dir)
    
    # Assert the brief file still exists at repo_root/'brief_hooks_ok.md'
    original_brief = repo_root / "brief_hooks_ok.md"
    assert original_brief.exists(), "Healthy brief file was incorrectly removed/quarantined"
    
    # Assert quarantine dir has no brief for it
    quarantined_brief = state_dir / "control" / "autowork" / "quarantine" / "brief_hooks_ok.md"
    assert not quarantined_brief.exists(), "Healthy brief file was incorrectly quarantined"
