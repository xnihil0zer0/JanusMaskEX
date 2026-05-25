"""Adversarial regression bar for AW12 — brief_status .json.processing
recognition (R-PROMOTE-2).

Background: ``harness/brief_status.py:48`` checks for in-flight tasks at the
path ``state/tasks/processing/<id>.json`` (subdir + ``.json`` suffix), but
``harness/orchestrator_worker.py:60`` renames the claimed task to
``state/tasks/<id>.json.processing`` (top-level + ``.processing`` suffix).
Tasks in flight are therefore invisible to ``compute_brief_status``, land
in ``unstaged_task_ids``, and could be re-staged by a daemon restart
mid-flight — at which point ``_auto_promote`` would double-promote and a
parallel worker would fight the original for the same task lock.

This test pins one contract AW12 is required to satisfy:

1. A task whose spec file lives at ``state/tasks/<id>.json.processing`` is
   classified as in-flight (in the record's ``processing`` list AND state
   ``in_flight``) and is excluded from ``unstaged_task_ids``.

Pattern mirrors session #14 G27/G28 and session #17 AW9c: META commit lands
the test with ``xfail(strict=False, reason=...)``. AW12's
verification_command runs pytest with ``--runxfail`` so the marker is
bypassed at gate time; the post-AW12 META commit drops the marker and the
test passes naturally.
"""
from __future__ import annotations

import json
import pathlib

import pytest


@pytest.mark.xfail(
    strict=False,
    reason="AW12 not landed: brief_status.py:48 only recognizes the legacy state/tasks/processing/<id>.json subdir variant, not the worker's actual <id>.json.processing suffix rename target. Drops post-AW12.",
)
def test_processing_suffix_excluded_from_unstaged(tmp_path: pathlib.Path) -> None:
    """A task at state/tasks/<id>.json.processing must be classified
    as in-flight and excluded from unstaged_task_ids."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    state_dir = tmp_path / "state"
    (state_dir / "tasks").mkdir(parents=True)

    (repo_root / "brief_hooks_inflight_demo.md").write_text(
        "# inflight demo brief\n", encoding="utf-8"
    )
    plan = {
        "slug": "inflight_demo",
        "brief": "brief_hooks_inflight_demo.md",
        "tasks": [
            {"task_id": "T1", "files_touched": ["t1.py"]},
            {"task_id": "T2", "files_touched": ["t2.py"]},
        ],
    }
    (repo_root / "plan_hooks_inflight_demo.json").write_text(
        json.dumps(plan), encoding="utf-8"
    )

    # Simulate orchestrator_worker.py:60 rename target
    (state_dir / "tasks" / "T1.json.processing").write_text("{}", encoding="utf-8")

    from harness.brief_status import compute_brief_status

    records = compute_brief_status(repo_root, state_dir)
    assert len(records) == 1, f"expected exactly one record, got {len(records)}"

    r = records[0]
    assert r["slug"] == "inflight_demo", f"wrong slug: {r['slug']!r}"

    assert "T1" not in r["unstaged_task_ids"], (
        "AW12 contract: a task whose spec lives at state/tasks/T1.json.processing "
        f"must be excluded from unstaged_task_ids. Got: {r['unstaged_task_ids']!r}"
    )
    assert "T2" in r["unstaged_task_ids"], (
        f"AW12 sanity: T2 (no in-flight file) must remain unstaged. Got: {r['unstaged_task_ids']!r}"
    )

    assert "T1" in r["processing"], (
        "AW12 contract: the widened processing list must include T1 (its "
        f"spec is at .json.processing). Got processing={r['processing']!r}"
    )

    assert r["state"] == "in_flight", (
        f"AW12 contract: a brief with an in-flight task must be classified "
        f"state='in_flight'. Got state={r['state']!r}"
    )
