"""Integration tests: Task decomposer <-> state <-> orchestrator flow.

Tests I-16 through I-18 from the JanusMask Phase 1 Test Plan (Section 11.5).
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from harness.diff_fuzzer import FuzzFailure
from harness.orchestrator import get_next_task
from harness.sandbox import ExecutionResult
from harness.state import init_state, read_state
from harness.task_decomposer import (
    Subtask,
    decompose_task,
    enqueue_subtasks,
    update_parent_state,
)


def _make_failure(args, ret_a, ret_b, reason="return_mismatch"):
    """Helper to create FuzzFailure objects for decomposition testing."""
    return FuzzFailure(
        input_args=args,
        input_kwargs={},
        result_a=ExecutionResult(success=True, return_value=ret_a, return_repr=repr(ret_a)),
        result_b=ExecutionResult(success=True, return_value=ret_b, return_repr=repr(ret_b)),
        reason=reason,
    )


def _write_parent_lineage_file(integration_state_dir: Path, parent_task: dict) -> None:
    """Write the parent task JSON into tasks/processed/ so that the
    orchestrator's depth_validator.check_true_depth can resolve the
    subtask's parent_task reference when walking lineage.

    In production, a decomposed parent is moved to tasks/processed/ once
    its subtasks are enqueued (orchestrator P1.4). These integration tests
    skip that orchestrator step and call enqueue_subtasks directly, so we
    reproduce the on-disk state here. The file shape is the minimal one
    check_true_depth needs: a top-level task_id and (optionally) parent_task
    -- we give it no parent so the lineage terminates at depth 1.
    """
    processed_dir = integration_state_dir / "tasks" / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "task_id": parent_task["task_id"],
        "specification": parent_task.get("specification", ""),
        "constraints": parent_task.get("constraints", {}),
        "depth": 0,
        # No parent_task key -> lineage walker stops after this file.
    }
    (processed_dir / f"{parent_task['task_id']}.json").write_text(json.dumps(payload))


@pytest.fixture
def integration_state_dir(tmp_path):
    """Fresh state directory with STATE.json initialized (flat tmp_path layout).

    Distinct from conftest.integration_state_dir (canonical, nested) because integration tests
    here pass integration_state_dir to functions that expect init_state() to have run.
    """
    for sub in ("sessions", "tasks", "tasks/processed"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    init_state(tmp_path)
    return tmp_path


@pytest.fixture
def parent_task():
    """A parent task that will be decomposed."""
    return {
        "task_id": "parent-001",
        "specification": "Write a function merge_sorted(a, b) that merges two sorted lists.",
        "constraints": {
            "language": "python",
            "function_signature": "def merge_sorted(a: list[int], b: list[int]) -> list[int]",
            "deterministic": True,
        },
    }


@pytest.fixture
def sample_failures():
    """Diverse failures that will trigger edge-case decomposition."""
    return [
        _make_failure(args=[[], [1, 2]], ret_a=[], ret_b=[1, 2], reason="return_mismatch"),
        _make_failure(args=[[1], [2]], ret_a=[1, 2], ret_b=[2, 1], reason="return_mismatch"),
        _make_failure(args=[[0], [0]], ret_a=[0, 0], ret_b=[0], reason="return_mismatch"),
    ]


class TestDecompositionFlow:
    """I-16 through I-18: Task decomposer <-> state <-> orchestrator."""

    def test_i16_subtasks_found_by_orchestrator(self, integration_state_dir, parent_task, sample_failures):
        """I-16: Decomposed subtasks written to tasks dir are findable
        by orchestrator's get_next_task."""
        config = {"decomposition": {"max_subtasks": 5}}
        result = decompose_task(parent_task, sample_failures, config,
                                code_a="def merge_sorted(a, b): return a + b\n",
                                code_b="def merge_sorted(a, b): return sorted(a + b)\n")

        assert len(result.subtasks) > 0

        # Enqueue subtasks to the tasks directory
        enqueue_subtasks(result.subtasks, integration_state_dir)

        # Write the parent lineage file to tasks/processed/ so that
        # depth_validator.check_true_depth can resolve the subtask's
        # parent_task="parent-001" reference (production contract).
        _write_parent_lineage_file(integration_state_dir, parent_task)

        # Verify the task files are written
        tasks_dir = integration_state_dir / "tasks"
        task_files = list(tasks_dir.glob("parent-001-*.json"))
        assert len(task_files) == len(result.subtasks), (
            f"Expected {len(result.subtasks)} task files, found {len(task_files)}"
        )

        # Verify orchestrator's get_next_task can find them
        task = get_next_task(integration_state_dir)
        assert task is not None
        assert task["parent_task"] == "parent-001"
        assert "specification" in task
        assert "constraints" in task

    def test_i17_parent_state_updated_with_children_ids(self, integration_state_dir, parent_task, sample_failures):
        """I-17: Parent state updated with children IDs after decomposition."""
        config = {"decomposition": {"max_subtasks": 5}}
        result = decompose_task(parent_task, sample_failures, config,
                                code_a="def merge_sorted(a, b): return a + b\n",
                                code_b="def merge_sorted(a, b): return sorted(a + b)\n")

        subtask_ids = [s.task_id for s in result.subtasks]
        assert len(subtask_ids) > 0

        # Update parent state
        update_parent_state(integration_state_dir, "parent-001", subtask_ids)

        # Verify STATE.json reflects decomposition
        state = read_state(integration_state_dir)
        assert state["phase"] == "decomposition"
        assert state["decomposed"] is True
        assert state["children"] == subtask_ids

    def test_i18_subtask_depends_on_ordering(self, integration_state_dir, parent_task, sample_failures):
        """I-18: Subtask with depends_on blocks until dependencies met --
        verify ordering is correctly specified in the task data."""
        config = {"decomposition": {"max_subtasks": 5}}
        result = decompose_task(parent_task, sample_failures, config,
                                code_a="def merge_sorted(a, b): return a + b\n",
                                code_b="def merge_sorted(a, b): return sorted(a + b)\n")

        # Enqueue subtasks
        enqueue_subtasks(result.subtasks, integration_state_dir)

        # Write the parent lineage file to tasks/processed/ so that
        # depth_validator.check_true_depth can resolve the subtask's
        # parent_task="parent-001" reference (production contract).
        _write_parent_lineage_file(integration_state_dir, parent_task)

        # Find the composition subtask (should have depends_on)
        compose_subtasks = [s for s in result.subtasks if s.depends_on]

        if compose_subtasks:
            compose = compose_subtasks[0]
            # Verify the depends_on references are valid subtask IDs
            all_ids = {s.task_id for s in result.subtasks}
            for dep_id in compose.depends_on:
                assert dep_id in all_ids, (
                    f"depends_on references {dep_id} which is not in subtask IDs: {all_ids}"
                )

            # Verify the on-disk task file has the depends_on field
            compose_path = integration_state_dir / "tasks" / f"{compose.task_id}.json"
            assert compose_path.exists()
            compose_data = json.loads(compose_path.read_text())
            assert "depends_on" in compose_data
            assert len(compose_data["depends_on"]) > 0

            # Verify the orchestrator would process independent subtasks first
            # (those without depends_on) by filename sort order
            independent_subtasks = [s for s in result.subtasks if not s.depends_on]
            assert len(independent_subtasks) > 0, (
                "There should be at least one independent subtask"
            )

            # Get the first task -- should be an independent one
            first_task = get_next_task(integration_state_dir)
            assert first_task is not None
            assert first_task["task_id"] in {s.task_id for s in independent_subtasks} or \
                   not first_task.get("depends_on", []), (
                "First task should be independent (no depends_on)"
            )
        else:
            # If decomposition didn't produce depends_on (e.g. retry strategy),
            # at least verify subtasks exist
            assert len(result.subtasks) > 0
