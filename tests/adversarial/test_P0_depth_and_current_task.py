"""Adversarial battery for P0.1: depth-loop break + current_task.json contract.

Per hooks-augmented-hooks-implementation-plan.md §5 P0 row:
    - Revert the P0.1 fix (drop check_true_depth call) then replay the 4-deep
      chained fixture. Mutation test: test fails -> fix works; restore fix.
    - Introduce decomposer loop (STAB-001-compose-reviewed-reviewed-...) via
      fixture. get_next_task breaks loop, moves task to processed/.

Mutation tests monkey-patch ``harness.depth_validator.check_true_depth`` to a
no-op (always-True) and assert the invariants then fail — proving the wired
gate is what's keeping them green.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import harness.depth_validator as depth_validator
import harness.orchestrator as orchestrator
from harness.orchestrator import _mark_processed, get_next_task


def _write(dirpath: Path, task_id: str, parent: str | None = None) -> None:
    payload = {"task_id": task_id, "specification": "noop"}
    if parent is not None:
        payload["parent_task"] = parent
    (dirpath / f"{task_id}.json").write_text(json.dumps(payload))


def _chain(state_dir: Path, depths: int) -> list[str]:
    """Create a parent_task chain a -> b -> c ... in tasks/. Returns ids."""
    ids = [chr(ord("a") + i) for i in range(depths)]
    parent: str | None = None
    for tid in ids:
        _write(state_dir / "tasks", tid, parent=parent)
        parent = tid
    return ids


# ── 1. Depth-loop break ────────────────────────────────────────────────────


def test_four_deep_chain_drops_deepest_to_processed(state_dir: Path) -> None:
    """4-deep chain a<-b<-c<-d. get_next_task must NOT serve d; it must move to processed/."""
    ids = _chain(state_dir, depths=4)
    served: list[str] = []
    for _ in range(4):
        task = get_next_task(state_dir)
        if task is None:
            break
        served.append(task["task_id"])
        _mark_processed(state_dir, task["task_id"])
    assert "d" not in served, f"depth-4 task should never be served, got {served}"
    deepest_processed = state_dir / "tasks" / "processed" / "d.json"
    assert deepest_processed.is_file(), "depth-4 task d must be moved straight to processed/"


def test_circular_parent_chain_moved_to_processed(state_dir: Path) -> None:
    """STAB-001-compose-reviewed-reviewed loop: a.parent=b, b.parent=a -> circular."""
    _write(state_dir / "tasks", "loop_a", parent="loop_b")
    _write(state_dir / "tasks", "loop_b", parent="loop_a")
    served: list[str] = []
    for _ in range(3):
        task = get_next_task(state_dir)
        if task is None:
            break
        served.append(task["task_id"])
        _mark_processed(state_dir, task["task_id"])
    assert served == [], f"circular tasks should never be served, got {served}"
    assert (state_dir / "tasks" / "processed" / "loop_a.json").is_file()
    assert (state_dir / "tasks" / "processed" / "loop_b.json").is_file()


def test_mutation_remove_depth_check_serves_too_deep(
    state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mutation: stub check_true_depth -> always True. The deepest task is now served."""
    _chain(state_dir, depths=4)
    # Patch where get_next_task imported the symbol from.
    monkeypatch.setattr(orchestrator, "check_true_depth", lambda *_args, **_kw: True)
    served: list[str] = []
    for _ in range(4):
        task = get_next_task(state_dir)
        if task is None:
            break
        served.append(task["task_id"])
        _mark_processed(state_dir, task["task_id"])
    assert "d" in served, (
        "Without the depth check, the depth-4 task is reachable. "
        f"Got served={served}. If this fails, the wiring may be missing."
    )


def test_mutation_remove_depth_check_serves_loop(
    state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mutation: stub check_true_depth -> always True. The circular task is now served."""
    _write(state_dir / "tasks", "loop_a", parent="loop_b")
    _write(state_dir / "tasks", "loop_b", parent="loop_a")
    monkeypatch.setattr(orchestrator, "check_true_depth", lambda *_args, **_kw: True)
    task = get_next_task(state_dir)
    assert task is not None and task["task_id"] in {"loop_a", "loop_b"}, (
        "Without the depth check, the loop participants are served as normal tasks."
    )


# ── 2. current_task.json contract ──────────────────────────────────────────


def test_current_task_written_on_claim(state_dir: Path) -> None:
    _write(state_dir / "tasks", "t1")
    task = get_next_task(state_dir)
    current = state_dir / "tasks" / "current_task_t1.json"
    assert task is not None and task["task_id"] == "t1"
    assert current.is_file(), "current_task_t1.json must exist after claim"
    payload = json.loads(current.read_text())
    assert payload["task_id"] == "t1"


def test_current_task_overwritten_on_subsequent_claim(state_dir: Path) -> None:
    _write(state_dir / "tasks", "a_task")
    _write(state_dir / "tasks", "b_task")
    first = get_next_task(state_dir)
    assert first["task_id"] == "a_task"
    _mark_processed(state_dir, "a_task")
    second = get_next_task(state_dir)
    assert second["task_id"] == "b_task"
    payload = json.loads((state_dir / "tasks" / "current_task_b_task.json").read_text())
    assert payload["task_id"] == "b_task", "current_task_b_task.json must reflect latest claim"


def test_mark_processed_removes_current_task(state_dir: Path) -> None:
    _write(state_dir / "tasks", "t1")
    get_next_task(state_dir)
    assert (state_dir / "tasks" / "current_task_t1.json").is_file()
    _mark_processed(state_dir, "t1")
    assert not (state_dir / "tasks" / "current_task_t1.json").exists(), (
        "current_task_t1.json must be removed by _mark_processed"
    )
    assert (state_dir / "tasks" / "processed" / "t1.json").is_file()


def test_mark_processed_no_current_task_safe(state_dir: Path) -> None:
    _write(state_dir / "tasks" / "processed", "ghost")
    _mark_processed(state_dir, "ghost")  # no current_task.json present


# ── 3. Defensive: depth check uses processed/ for parent lookups ───────────


def test_decomposer_subtask_with_parent_in_processed_is_served(state_dir: Path) -> None:
    """A real decomposer flow: parent moved to processed/, subtask in tasks/.
    Without P1.4, check_true_depth would FileNotFoundError -> False -> drop.
    With P1.4, the parent is found in processed/ and the subtask is served.
    """
    _write(state_dir / "tasks" / "processed", "parent")
    _write(state_dir / "tasks", "child", parent="parent")
    task = get_next_task(state_dir)
    assert task is not None and task["task_id"] == "child", (
        "decomposed subtask whose parent lives in processed/ must still be served"
    )
