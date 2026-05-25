"""Adversarial bars for SB5 — decomposition depth cap is terminal + observable.

Closes the session #24 P3.3 no-converge cycle. Two coupled fixes:

- **Worker terminal guard** (`harness/orchestrator_worker.py`): when a task
  arrives at the decompose phase already at ``depth >= config max_depth``, the
  worker emits a ``decompose_max_depth`` ledger row and TERMINATES (rejected →
  ``_mark_processed``) instead of spawning yet another escalation.
- **Monotonic escalation depth** (`harness/task_decomposer.py`): the two
  ``planner_review`` escalation paths used to reset the child ``depth`` to 0,
  so depth never climbed and the worker guard was unreachable (the #24
  oscillation). They now carry ``depth + 1`` so depth climbs to the cap.

Plain (non-xfail) regression guards — landed via reviewed direct edit, #28.
"""

from __future__ import annotations

import ast
import pathlib

from harness.task_decomposer import decompose_task

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKER = REPO_ROOT / "harness" / "orchestrator_worker.py"

_CFG = {"decomposition": {"max_depth": 2, "max_subtasks": 5}}


def _worker_main_src() -> str:
    tree = ast.parse(WORKER.read_text(encoding="utf-8"))
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == "main":
            return ast.unparse(n)
    raise AssertionError("orchestrator_worker.main not found")


def test_worker_has_max_depth_terminal_guard() -> None:
    body = _worker_main_src()
    assert "decompose_max_depth" in body, "worker missing decompose_max_depth ledger event"
    assert "cur_depth >= max_depth" in body, "worker missing the depth-cap predicate"
    # the guard must terminate (return) before calling decompose_task again
    assert "'reason': 'decompose_max_depth'" in body


def test_hard_cap_planner_review_propagates_depth() -> None:
    """At depth >= max_depth, decompose_task returns a planner_review whose child
    carries depth+1 (was 0 — the reset that caused the #24 oscillation)."""
    task = {"task_id": "T_cap", "specification": "do x"}
    res = decompose_task(task, [], _CFG, depth=2)
    assert res.strategy == "planner_review"
    assert len(res.subtasks) == 1
    assert res.subtasks[0].depth == 3, (
        f"planner_review child depth should climb (3), got {res.subtasks[0].depth}"
    )


def test_guard_shortcircuit_planner_review_propagates_depth() -> None:
    """The structural-guard short-circuit path also escalates depth monotonically
    (depth 1, max_depth 2 -> not structurally applicable -> planner_review at 2)."""
    task = {"task_id": "T_guard", "specification": "do x"}
    res = decompose_task(task, [], _CFG, depth=1)
    assert res.strategy == "planner_review"
    assert res.subtasks[0].depth == 2, (
        f"guard planner_review child depth should be 2, got {res.subtasks[0].depth}"
    )


def test_escalation_reaches_cap_in_bounded_steps() -> None:
    """Simulate the daemon loop: feed each planner_review child's depth back into
    decompose_task. Depth must reach the cap in a bounded number of steps (no
    infinite depth-0 oscillation)."""
    depth = 0
    task = {"task_id": "T_loop", "specification": "do x"}
    seen_depths = []
    for _ in range(10):
        res = decompose_task(task, [], _CFG, depth=depth)
        child_depth = res.subtasks[0].depth
        seen_depths.append(child_depth)
        if child_depth >= _CFG["decomposition"]["max_depth"]:
            break
        depth = child_depth
    assert max(seen_depths) >= _CFG["decomposition"]["max_depth"], (
        f"escalation never reached the cap (depths seen: {seen_depths})"
    )
