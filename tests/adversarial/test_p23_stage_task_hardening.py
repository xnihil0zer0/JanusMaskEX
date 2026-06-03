"""Behavioral RED oracle for P23_STAGE_TASK_HARDENING (plan items P2 + P3).

Drives the REAL ``harness.planner.staging.stage_task`` and asserts two
behaviors that are MISSING on HEAD (so both tests fail RED on HEAD):

  TEST 1 (P3 diff-aware overwrite): staging an id whose canonical file already
    exists, with DIFFERENT, not-yet-accepted content, must OVERWRITE rather
    than raise ``FileExistsError``. On HEAD ``stage_task`` unconditionally
    raises ``FileExistsError`` => RED.

  TEST 2 (P2 evict stale blocked sidecars): before (re)staging an id,
    ``state_dir/tasks/blocked/<id>.json``, ``<id>.retry.json`` and
    ``<id>.exhausted`` must be evicted (best-effort). On HEAD they persist
    untouched => RED.

Hermetic (tmp_path), fast, no network. Calls ``stage_task`` with the real
signature ``stage_task(plan_path, task_id, state_dir, canonical=True)``.
"""
import json
from pathlib import Path

import pytest

from harness.planner.staging import stage_task


def _write_plan(plan_path: Path, task: dict) -> None:
    plan_path.write_text(json.dumps({"tasks": [task]}), encoding="utf-8")


def test_stage_task_overwrites_unaccepted_changed_task(tmp_path):
    """P3: re-staging the same id with changed, not-yet-accepted content
    overwrites the canonical file instead of raising FileExistsError."""
    state_dir = tmp_path / "state"
    plan_v1 = tmp_path / "plan_v1.json"
    plan_v2 = tmp_path / "plan_v2.json"

    _write_plan(plan_v1, {"task_id": "T1", "meta_task_type": "old", "marker": "v1"})
    _write_plan(plan_v2, {"task_id": "T1", "meta_task_type": "new", "marker": "v2"})

    # First staging succeeds and creates the canonical file.
    out1 = stage_task(plan_v1, "T1", state_dir, canonical=True)
    assert out1.exists()
    first = json.loads(out1.read_text(encoding="utf-8"))
    assert first.get("marker") == "v1"

    # Second staging with DIFFERENT content for the SAME id. The task has not
    # been accepted (no processed marker, no accepted ledger row), so this must
    # overwrite -- NOT raise FileExistsError (which is what HEAD does => RED).
    try:
        out2 = stage_task(plan_v2, "T1", state_dir, canonical=True)
    except FileExistsError as exc:
        raise AssertionError(
            "stage_task raised FileExistsError instead of overwriting an "
            f"unaccepted changed task (P3 not implemented): {exc!r}"
        ) from exc

    staged = json.loads(out2.read_text(encoding="utf-8"))
    assert staged.get("marker") == "v2", (
        f"staged file was not updated to the new task content: {staged!r}"
    )
    assert staged.get("meta_task_type") == "new", (
        f"staged meta_task_type was not updated: {staged!r}"
    )


def test_stage_task_evicts_stale_blocked_sidecars(tmp_path):
    """P2: staging an id evicts its stale blocked/<id>.json, <id>.retry.json
    and <id>.exhausted sidecars."""
    state_dir = tmp_path / "state"
    blocked_dir = state_dir / "tasks" / "blocked"
    blocked_dir.mkdir(parents=True, exist_ok=True)

    sidecar_json = blocked_dir / "T2.json"
    sidecar_retry = blocked_dir / "T2.retry.json"
    sidecar_exhausted = blocked_dir / "T2.exhausted"
    sidecar_json.write_text("{}", encoding="utf-8")
    sidecar_retry.write_text(json.dumps({"attempts": 3, "ts": 0.0}), encoding="utf-8")
    sidecar_exhausted.write_text("1", encoding="utf-8")

    plan_path = tmp_path / "plan.json"
    _write_plan(plan_path, {"task_id": "T2", "meta_task_type": "harness_self_fix"})

    out = stage_task(plan_path, "T2", state_dir, canonical=True)
    assert out.exists()

    # All three stale sidecars must be gone (HEAD leaves them => RED).
    assert not sidecar_json.exists(), "blocked/<id>.json was not evicted"
    assert not sidecar_retry.exists(), "blocked/<id>.retry.json was not evicted"
    assert not sidecar_exhausted.exists(), "blocked/<id>.exhausted was not evicted"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
