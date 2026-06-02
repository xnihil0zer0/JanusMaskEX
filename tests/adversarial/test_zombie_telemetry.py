"""Adversarial bar for ZOMBIE_TELEMETRY (REV22 §2d).

A task that fails auto-commit can be parked in ``state/tasks/processed/<id>.json``
WITHOUT an ``accepted``/``auto_commit`` ledger row. If that task is the only
remaining (non-accepted) work for its parent brief and nothing is queued /
processing / blocked, the brief is a *zombie*: ``compute_brief_status`` counts
``processed/`` as staged, so ``unstaged_task_ids`` is empty and the autowork
daemon never re-stages it -- it sits unaccepted forever, requiring manual
cleanup.

On HEAD such a brief is misreported as ``state='queued'`` (the catch-all
branch), giving an operator no signal that the brief is actually stuck. The
ZOMBIE_TELEMETRY fix surfaces an observable signal: ``state='zombie'`` for a
brief whose remaining tasks are all parked-unaccepted in ``processed/``.

Contracts pinned here:
1. A brief whose only remaining task is parked-unaccepted in ``processed/``
   (no queued/processing/blocked, brief not complete) is flagged
   ``state == 'zombie'`` and the task appears in ``processed_unaccepted``.
2. A normal accepted brief is NOT flagged zombie (``state == 'complete'``).
3. A brief with a parked task BUT also genuine in-flight work is NOT a zombie
   (active progress wins -> ``state == 'in_flight'``).
"""
from __future__ import annotations

import json
import pathlib

from harness.brief_status import compute_brief_status


def _write_brief_and_plan(repo_root: pathlib.Path, slug: str, task_ids: list[str]) -> None:
    (repo_root / f"brief_hooks_{slug}.md").write_text("# brief\n", encoding="utf-8")
    plan = {"tasks": [{"task_id": t} for t in task_ids]}
    (repo_root / f"plan_hooks_{slug}.json").write_text(json.dumps(plan), encoding="utf-8")


def test_parked_unaccepted_task_flags_brief_zombie(tmp_path: pathlib.Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    state_dir = tmp_path / "state"
    (state_dir / "tasks" / "processed").mkdir(parents=True)

    _write_brief_and_plan(repo_root, "zomb", ["T1"])
    # T1 landed in processed/ but NO accepted/auto_commit ledger row exists.
    (state_dir / "tasks" / "processed" / "T1.json").write_text("{}", encoding="utf-8")

    records = compute_brief_status(repo_root, state_dir)
    assert len(records) == 1, f"expected one record, got {len(records)}"
    r = records[0]

    assert r["slug"] == "zomb", f"wrong slug: {r['slug']!r}"
    assert r["processed_unaccepted"] == ["T1"], (
        f"T1 must be detected as parked-unaccepted: {r['processed_unaccepted']!r}"
    )
    # The observable signal: brief is a zombie, NOT a misleading 'queued'.
    assert r["state"] == "zombie", (
        "ZOMBIE_TELEMETRY contract: a brief whose only remaining task is parked "
        f"unaccepted in processed/ must surface state='zombie'. Got {r['state']!r}"
    )


def test_accepted_brief_not_zombie(tmp_path: pathlib.Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    _write_brief_and_plan(repo_root, "ok", ["T1"])
    ledger = {"phase": "accepted", "event": "auto_commit", "task_id": "T1", "commit_sha": "abc", "ts": 1}
    (state_dir / "impl_progress.jsonl").write_text(json.dumps(ledger) + "\n", encoding="utf-8")

    records = compute_brief_status(repo_root, state_dir)
    r = records[0]
    assert r["state"] == "complete", f"accepted brief must be complete, got {r['state']!r}"
    assert r["state"] != "zombie"


def test_parked_plus_inflight_is_not_zombie(tmp_path: pathlib.Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    state_dir = tmp_path / "state"
    (state_dir / "tasks" / "processed").mkdir(parents=True)

    _write_brief_and_plan(repo_root, "mix", ["T1", "T2"])
    # T1 parked unaccepted, but T2 is genuinely queued -> active work in flight.
    (state_dir / "tasks" / "processed" / "T1.json").write_text("{}", encoding="utf-8")
    (state_dir / "tasks" / "T2.json").write_text("{}", encoding="utf-8")

    records = compute_brief_status(repo_root, state_dir)
    r = records[0]
    assert r["state"] == "in_flight", (
        f"a brief with a parked task but live queued work must stay in_flight, got {r['state']!r}"
    )
    assert r["state"] != "zombie"
    # T1 is still detectable as parked even when the brief is in_flight.
    assert "T1" in r["processed_unaccepted"]
