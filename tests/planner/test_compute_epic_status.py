"""Oracle for Brief 16: compute_epic_status read-derived roll-up + telemetry.

RED on HEAD: ``harness.brief_status`` computes per-brief status but has no
notion of an *epic* rolling up over its children. Per PHASE1 Brief 16 (and
``area_D_verified.md`` — roll-up is a COMPUTED view, never a second persisted
tree-state file), ``compute_epic_status(repo_root, state_dir)`` derives each
epic's state from its children's ``compute_brief_status`` records: an epic is
``complete`` iff every child is ``complete``; ``blocked`` if any child is
blocked/zombie; otherwise ``in_flight``. A best-effort ``record_epic_complete``
appends a flat ``(phase='epic', event='epic_complete')`` telemetry row (never
load-bearing). Neither symbol exists yet, so this module errors on HEAD.
"""
from __future__ import annotations

import json
from pathlib import Path

from harness.brief_status import compute_epic_status, record_epic_complete


# ---------------------------------------------------------------------------
# helpers: lay down an epic + its child briefs/plans/ledger in a tmp repo
# ---------------------------------------------------------------------------

def _write_brief(repo: Path, slug: str) -> None:
    (repo / f"brief_hooks_{slug}.md").write_text(
        "# Title\n\nt\n\n# Scope\n\ns\n\n# Non-Goals\n\nn\n\n# Inputs\n\ni\n\n# Deliverables\n\nd\n",
        encoding="utf-8",
    )


def _write_epic_record(repo: Path, epic_slug: str, child_slugs: list[str]) -> None:
    # The epic's own brief + its plan_hooks epic record listing children.
    _write_brief(repo, epic_slug)
    (repo / f"plan_hooks_{epic_slug}.json").write_text(
        json.dumps({"plan_kind": "epic", "epic": True, "epic_slug": epic_slug,
                    "child_slugs": list(child_slugs)}),
        encoding="utf-8",
    )


def _write_child_plan(repo: Path, slug: str, task_ids: list[str]) -> None:
    # A child brief + a normal (leaf) plan_hooks with concrete tasks.
    _write_brief(repo, slug)
    (repo / f"plan_hooks_{slug}.json").write_text(
        json.dumps({"tasks": [{"task_id": t} for t in task_ids]}),
        encoding="utf-8",
    )


def _accept(state_dir: Path, task_id: str) -> None:
    # Mark a task accepted in the ledger (so compute_brief_status -> complete).
    ledger = state_dir / "impl_progress.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with open(ledger, "a", encoding="utf-8") as f:
        f.write(json.dumps({"phase": "accepted", "event": "auto_commit",
                            "task_id": task_id, "commit_sha": "abc", "ts": 1.0}) + "\n")


def _queue(state_dir: Path, task_id: str) -> None:
    # Leave a task queued (so the child brief is in_flight, not complete).
    d = state_dir / "tasks"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{task_id}.json").write_text(json.dumps({"task_id": task_id}), encoding="utf-8")


def _find(records: list[dict], slug: str) -> dict:
    for r in records:
        if r.get("epic_slug") == slug or r.get("slug") == slug:
            return r
    raise AssertionError(f"no epic record for {slug}: {records}")


# ---------------------------------------------------------------------------
# compute_epic_status
# ---------------------------------------------------------------------------

def test_epic_complete_when_all_children_complete(tmp_path):
    repo, state = tmp_path, tmp_path / "state"
    _write_epic_record(repo, "epic1", ["c1", "c2"])
    _write_child_plan(repo, "c1", ["c1t1"])
    _write_child_plan(repo, "c2", ["c2t1"])
    _accept(state, "c1t1")
    _accept(state, "c2t1")
    rec = _find(compute_epic_status(repo, state), "epic1")
    assert rec["state"] == "complete"


def test_epic_in_flight_when_a_child_unfinished(tmp_path):
    repo, state = tmp_path, tmp_path / "state"
    _write_epic_record(repo, "epic1", ["c1", "c2"])
    _write_child_plan(repo, "c1", ["c1t1"])
    _write_child_plan(repo, "c2", ["c2t1"])
    _accept(state, "c1t1")
    _queue(state, "c2t1")  # c2 still in_flight
    rec = _find(compute_epic_status(repo, state), "epic1")
    assert rec["state"] != "complete"


def test_epic_status_lists_children(tmp_path):
    repo, state = tmp_path, tmp_path / "state"
    _write_epic_record(repo, "epic1", ["c1", "c2"])
    _write_child_plan(repo, "c1", ["c1t1"])
    _write_child_plan(repo, "c2", ["c2t1"])
    rec = _find(compute_epic_status(repo, state), "epic1")
    # the roll-up surfaces the child slugs it considered
    children = rec.get("children") or rec.get("child_slugs") or []
    child_slugs = {c["slug"] if isinstance(c, dict) else c for c in children}
    assert {"c1", "c2"} <= child_slugs


def test_epic_blocked_when_child_blocked(tmp_path):
    repo, state = tmp_path, tmp_path / "state"
    _write_epic_record(repo, "epic1", ["c1"])
    _write_child_plan(repo, "c1", ["c1t1"])
    blocked = state / "tasks" / "blocked"
    blocked.mkdir(parents=True, exist_ok=True)
    (blocked / "c1t1.json").write_text(json.dumps({"task_id": "c1t1"}), encoding="utf-8")
    rec = _find(compute_epic_status(repo, state), "epic1")
    assert rec["state"] == "blocked"


def test_no_epics_returns_empty(tmp_path):
    repo, state = tmp_path, tmp_path / "state"
    _write_child_plan(repo, "lonely_leaf", ["t1"])  # leaf plan, not an epic
    assert compute_epic_status(repo, state) == []


def test_missing_child_record_is_not_complete(tmp_path):
    repo, state = tmp_path, tmp_path / "state"
    # epic references a child whose brief/plan does not exist yet (unplanned).
    _write_epic_record(repo, "epic1", ["ghost"])
    rec = _find(compute_epic_status(repo, state), "epic1")
    assert rec["state"] != "complete"


# ---------------------------------------------------------------------------
# record_epic_complete telemetry (flat, best-effort, never load-bearing)
# ---------------------------------------------------------------------------

def test_record_epic_complete_appends_flat_row(tmp_path):
    state = tmp_path / "state"
    state.mkdir(parents=True, exist_ok=True)
    record_epic_complete("epic1", state)
    ledger = state / "impl_progress.jsonl"
    rows = [json.loads(l) for l in ledger.read_text().splitlines() if l.strip()]
    epic_rows = [r for r in rows if r.get("phase") == "epic" and r.get("event") == "epic_complete"]
    assert len(epic_rows) == 1
    assert epic_rows[0].get("epic_slug") == "epic1"


def test_record_epic_complete_best_effort_swallows_errors(tmp_path):
    # A non-writable/odd state_dir must not raise (telemetry is best-effort).
    record_epic_complete("epic1", tmp_path / "does" / "not" / "exist")  # no raise
