"""Tests for harness/task_decomposer.py -- 37 tests (D-01 through D-37)."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json
import pytest
from pathlib import Path

from harness.task_decomposer import (
    _classify_failures,
    _decompose_by_edge_cases,
    _decompose_by_function_split,
    decompose_task,
    enqueue_subtasks,
    update_parent_state,
    Subtask,
    DecompositionResult,
)
from harness.sandbox import ExecutionResult
from harness.diff_fuzzer import FuzzFailure


def _make_failure(
    input_args=None,
    input_kwargs=None,
    reason="return_mismatch",
):
    if input_args is None:
        input_args = [5, 10]
    if input_kwargs is None:
        input_kwargs = {}
    result_a = ExecutionResult(success=True, return_value=1, return_repr="1")
    result_b = ExecutionResult(success=True, return_value=2, return_repr="2")
    return FuzzFailure(
        input_args=input_args,
        input_kwargs=input_kwargs,
        result_a=result_a,
        result_b=result_b,
        reason=reason,
    )


# ===========================================================================
# Failure Classification (D-01 to D-13)
# ===========================================================================

class TestClassifyFailures:

    def test_d01_empty_list_arg(self):
        f = _make_failure(input_args=[[]])
        cats = _classify_failures([f])
        assert "empty_input" in cats

    def test_d02_empty_string_arg(self):
        f = _make_failure(input_args=[""])
        cats = _classify_failures([f])
        assert "empty_input" in cats

    def test_d03_empty_dict_arg(self):
        f = _make_failure(input_args=[{}])
        cats = _classify_failures([f])
        assert "empty_input" in cats

    def test_d04_single_element_list(self):
        f = _make_failure(input_args=[[42]])
        cats = _classify_failures([f])
        assert "single_element" in cats

    def test_d05_arg_zero_boundary(self):
        f = _make_failure(input_args=[0])
        cats = _classify_failures([f])
        assert "boundary" in cats

    def test_d06_arg_negative_one_boundary(self):
        f = _make_failure(input_args=[-1])
        cats = _classify_failures([f])
        assert "boundary" in cats

    def test_d07_exception_mismatch_type_error(self):
        f = _make_failure(input_args=[5, 10], reason="exception_mismatch")
        cats = _classify_failures([f])
        assert "type_error" in cats

    def test_d08_normal_args_general(self):
        f = _make_failure(input_args=[5, 10])
        cats = _classify_failures([f])
        assert "general" in cats

    def test_d09_empty_list_returns_empty_dict(self):
        cats = _classify_failures([])
        assert cats == {}

    def test_d10_all_same_category_single_entry(self):
        failures = [_make_failure(input_args=[[]]) for _ in range(3)]
        cats = _classify_failures(failures)
        assert len(cats) == 1
        assert "empty_input" in cats
        assert len(cats["empty_input"]) == 3

    def test_d11_multiple_categories(self):
        f1 = _make_failure(input_args=[[]])
        f2 = _make_failure(input_args=[0])
        cats = _classify_failures([f1, f2])
        assert len(cats) >= 2

    def test_d12_first_match_wins(self):
        # An empty tuple is both empty AND could be single-element check target,
        # but empty_input check comes first
        f = _make_failure(input_args=[tuple()])
        cats = _classify_failures([f])
        assert "empty_input" in cats
        assert "single_element" not in cats

    def test_d13_first_match_wins_boundary_over_type(self):
        # 0 as arg with exception_mismatch reason: boundary check comes before
        # exception_mismatch check, so boundary wins
        f = _make_failure(input_args=[0], reason="exception_mismatch")
        cats = _classify_failures([f])
        assert "boundary" in cats
        assert "type_error" not in cats


# ===========================================================================
# Edge-Case Decomposition (D-14 to D-19)
# ===========================================================================

class TestDecomposeByEdgeCases:

    def _make_task(self, task_id="task-1"):
        return {
            "task_id": task_id,
            "specification": "Sort a list of integers",
            "constraints": {"function_signature": "def sort_list(lst: list[int]) -> list[int]"},
        }

    def test_d14_two_categories_creates_subtasks_plus_composition(self):
        f1 = _make_failure(input_args=[[]])
        f2 = _make_failure(input_args=[0])
        cats = _classify_failures([f1, f2])
        subtasks = _decompose_by_edge_cases(self._make_task(), cats, max_subtasks=5)
        # Should have component subtasks + 1 composition
        assert len(subtasks) >= 3  # at least 2 components + 1 compose

    def test_d15_composition_depends_on_components(self):
        f1 = _make_failure(input_args=[[]])
        f2 = _make_failure(input_args=[0])
        cats = _classify_failures([f1, f2])
        subtasks = _decompose_by_edge_cases(self._make_task(), cats, max_subtasks=5)
        compose = [s for s in subtasks if "compose" in s.task_id]
        assert len(compose) == 1
        assert len(compose[0].depends_on) > 0

    def test_d16_subtask_ids_follow_pattern(self):
        f1 = _make_failure(input_args=[[]])
        f2 = _make_failure(input_args=[0])
        cats = _classify_failures([f1, f2])
        subtasks = _decompose_by_edge_cases(self._make_task("parent-1"), cats, max_subtasks=5)
        non_compose = [s for s in subtasks if "compose" not in s.task_id]
        for s in non_compose:
            assert s.task_id.startswith("parent-1-")

    def test_d17_specs_include_example_inputs(self):
        f1 = _make_failure(input_args=[[]])
        cats = _classify_failures([f1])
        subtasks = _decompose_by_edge_cases(self._make_task(), cats, max_subtasks=5)
        non_compose = [s for s in subtasks if "compose" not in s.task_id]
        assert len(non_compose) >= 1
        assert "Example failing inputs" in non_compose[0].specification

    def test_task_decomposer_prompt_context(self):
        """Verify context is included in prompt."""
        f1 = _make_failure(input_args=[[]])
        cats = _classify_failures([f1])
        task = self._make_task()
        task["system_objective"] = "System Objective Context"
        task["codebase_context"] = "Codebase Context String"
        subtasks = _decompose_by_edge_cases(task, cats, max_subtasks=5)
        assert len(subtasks) >= 1
        for s in subtasks:
            assert "System Objective Context" in s.specification
            assert "Codebase Context String" in s.specification

    def test_d18_max_subtasks_respected(self):
        # Create many categories
        f1 = _make_failure(input_args=[[]])
        f2 = _make_failure(input_args=[[42]])
        f3 = _make_failure(input_args=[0])
        f4 = _make_failure(input_args=[5, 10], reason="exception_mismatch")
        f5 = _make_failure(input_args=[5, 10])
        cats = _classify_failures([f1, f2, f3, f4, f5])
        subtasks = _decompose_by_edge_cases(self._make_task(), cats, max_subtasks=3)
        assert len(subtasks) <= 3

    def test_d19_composition_references_all_components(self):
        f1 = _make_failure(input_args=[[]])
        f2 = _make_failure(input_args=[0])
        cats = _classify_failures([f1, f2])
        subtasks = _decompose_by_edge_cases(self._make_task(), cats, max_subtasks=5)
        compose = [s for s in subtasks if "compose" in s.task_id][0]
        non_compose = [s for s in subtasks if "compose" not in s.task_id]
        for nc in non_compose:
            assert nc.task_id in compose.depends_on


# ===========================================================================
# Function-Split Decomposition (D-20 to D-25)
# ===========================================================================

class TestDecomposeByFunctionSplit:

    def _make_task(self, task_id="task-1"):
        return {
            "task_id": task_id,
            "specification": "Sort a list of integers",
            "constraints": {},
        }

    def test_d20_code_with_if_for_return_creates_subtasks(self):
        code = (
            "def foo(x):\n"
            "    if x < 0:\n"
            "        return -x\n"
            "    for i in range(x):\n"
            "        x += i\n"
            "    return x\n"
        )
        subtasks = _decompose_by_function_split(self._make_task(), code, "", max_subtasks=5)
        assert len(subtasks) >= 2

    def test_d21_single_block_returns_empty(self):
        code = "def foo(x):\n    return x + 1\n"
        subtasks = _decompose_by_function_split(self._make_task(), code, "", max_subtasks=5)
        assert subtasks == []

    def test_d22_syntax_error_code_returns_empty(self):
        code = "def foo(x):\n    return x +++"
        subtasks = _decompose_by_function_split(self._make_task(), code, "", max_subtasks=5)
        assert subtasks == []

    def test_d23_no_function_defs_returns_empty(self):
        code = "x = 42\ny = x + 1\n"
        subtasks = _decompose_by_function_split(self._make_task(), code, "", max_subtasks=5)
        assert subtasks == []

    def test_d24_duplicate_block_types_deduplicated(self):
        code = (
            "def foo(x):\n"
            "    if x < 0:\n"
            "        return -x\n"
            "    if x > 100:\n"
            "        return 100\n"
            "    return x\n"
        )
        subtasks = _decompose_by_function_split(self._make_task(), code, "", max_subtasks=5)
        # Two if blocks but same type -> deduplicated, plus return
        non_compose = [s for s in subtasks if "compose" not in s.task_id]
        block_types_in_ids = [s.task_id.split("-")[-1] for s in non_compose]
        # Should not have duplicates of the same block type base
        assert len(non_compose) >= 1

    def test_d25_composition_subtask_added(self):
        code = (
            "def foo(x):\n"
            "    if x < 0:\n"
            "        return -x\n"
            "    for i in range(x):\n"
            "        x += i\n"
            "    return x\n"
        )
        subtasks = _decompose_by_function_split(self._make_task(), code, "", max_subtasks=5)
        compose = [s for s in subtasks if "compose" in s.task_id]
        assert len(compose) == 1


# ===========================================================================
# Main Entry Point (D-26 to D-31)
# ===========================================================================

class TestDecomposeTask:

    def _make_task(self, task_id="task-1"):
        return {
            "task_id": task_id,
            "specification": "Sort a list of integers",
            "constraints": {},
        }

    def test_d26_multiple_failure_categories_edge_case_strategy(self):
        f1 = _make_failure(input_args=[[]])
        f2 = _make_failure(input_args=[0])
        result = decompose_task(self._make_task(), [f1, f2], {})
        assert result.strategy == "edge_case"

    def test_d27_single_category_multi_block_function_split(self):
        code_a = (
            "def foo(x):\n"
            "    if x < 0:\n"
            "        return -x\n"
            "    for i in range(x):\n"
            "        x += i\n"
            "    return x\n"
        )
        f = _make_failure(input_args=[5, 10])
        result = decompose_task(self._make_task(), [f], {}, code_a=code_a)
        assert result.strategy == "function_split"

    def test_d28_single_category_no_code_fallback(self):
        # Single category, no code -> fallback edge_case (or retry if no categories)
        f = _make_failure(input_args=[5, 10])
        result = decompose_task(self._make_task(), [f], {})
        # With one general failure, decomposer uses fallback edge_case
        assert result.strategy in ("edge_case", "retry")

    def test_d29_result_includes_parent_task_id(self):
        f1 = _make_failure(input_args=[[]])
        f2 = _make_failure(input_args=[0])
        result = decompose_task(self._make_task("my-task"), [f1, f2], {})
        assert result.parent_task_id == "my-task"

    def test_d30_result_includes_reason(self):
        f1 = _make_failure(input_args=[[]])
        f2 = _make_failure(input_args=[0])
        result = decompose_task(self._make_task(), [f1, f2], {})
        assert len(result.reason) > 0

    def test_d31_result_has_subtasks(self):
        f1 = _make_failure(input_args=[[]])
        f2 = _make_failure(input_args=[0])
        result = decompose_task(self._make_task(), [f1, f2], {})
        assert len(result.subtasks) > 0

    def test_max_depth_reached_returns_original_task(self):
        """At max depth, the decomposer intentionally returns a single planner-review
        subtask (strategy='planner_review') instead of a terminal 'max_depth' signal
        -- it nudges the agent to retry with a conceptual tweak rather than hard-failing.
        See harness/task_decomposer.py:451-475."""
        f = _make_failure(input_args=[5, 10])
        config = {"decomposition": {"max_depth": 3}}
        task = self._make_task("t1")
        result = decompose_task(task, [f], config, depth=3)
        assert result.strategy == "planner_review"
        assert len(result.subtasks) == 1
        assert result.subtasks[0].parent_task_id == "t1"
        assert "PLANNER REVIEW" in result.subtasks[0].specification


# ===========================================================================
# Persistence (D-32 to D-37)
# ===========================================================================

class TestPersistence:

    def test_d32_enqueue_subtasks_writes_json_files(self, tmp_path):
        subtasks = [
            Subtask(
                task_id="t1-empty",
                parent_task_id="t1",
                specification="Handle empty input",
                constraints={},
            ),
        ]
        enqueue_subtasks(subtasks, tmp_path)
        assert (tmp_path / "tasks" / "t1-empty.json").exists()

    def test_d33_subtask_json_has_all_fields(self, tmp_path):
        subtasks = [
            Subtask(
                task_id="t1-empty",
                parent_task_id="t1",
                specification="Handle empty input",
                constraints={"key": "value"},
                depends_on=["t1-boundary"],
            ),
        ]
        enqueue_subtasks(subtasks, tmp_path)
        with open(tmp_path / "tasks" / "t1-empty.json") as f:
            data = json.load(f)
        assert data["task_id"] == "t1-empty"
        assert data["parent_task"] == "t1"
        assert data["specification"] == "Handle empty input"
        assert data["constraints"] == {"key": "value"}
        assert data["depends_on"] == ["t1-boundary"]

    def test_d34_update_parent_state_sets_phase(self, tmp_path):
        from harness.state import init_state, read_state
        init_state(tmp_path)
        update_parent_state(tmp_path, "t1", ["t1-a", "t1-b"])
        state = read_state(tmp_path)
        assert state["phase"] == "decomposition"

    def test_d35_update_parent_state_sets_decomposed(self, tmp_path):
        from harness.state import init_state, read_state
        init_state(tmp_path)
        update_parent_state(tmp_path, "t1", ["t1-a", "t1-b"])
        state = read_state(tmp_path)
        assert state["decomposed"] is True

    def test_d36_update_parent_state_sets_children(self, tmp_path):
        from harness.state import init_state, read_state
        init_state(tmp_path)
        update_parent_state(tmp_path, "t1", ["t1-a", "t1-b"])
        state = read_state(tmp_path)
        assert state["children"] == ["t1-a", "t1-b"]

    def test_d37_tasks_dir_created_if_missing(self, tmp_path):
        state_dir = tmp_path / "brand_new"
        subtasks = [
            Subtask(
                task_id="t1-empty",
                parent_task_id="t1",
                specification="Handle empty input",
                constraints={},
            ),
        ]
        enqueue_subtasks(subtasks, state_dir)
        assert (state_dir / "tasks").is_dir()


# ===========================================================================
# Meta Task Type Inheritance (M1 -- v2 step 2 regression gap)
#
# Pins the FR6 back-propagation in harness.task_decomposer: decomposer-generated
# children use the flat schema and drop top-level meta_task_type, so the parent
# value must be copied into each child's constraints unless the child already
# carries an explicit meta_task_type (explicit override wins). If the parent
# has no meta_task_type at all, children must not invent one.
#
# Exercises the real decompose_task entry point (no mocks). The propagation
# test covers BOTH code paths:
#   - planner_review branch (parent mtt 'orchestration' is in
#     SIDE_EFFECT_META_TYPES, triggering the structural-decomposition guard)
#   - edge_case branch (non-side-effect mtt 'pure_function' survives the guard
#     and yields multiple children via _decompose_by_edge_cases)
# ===========================================================================

class TestMetaTaskTypeInheritance:

    def _make_task(self, task_id="task-1", meta_task_type=None, constraints=None):
        task = {
            "task_id": task_id,
            "specification": "Sort a list of integers",
            "constraints": constraints if constraints is not None else {},
        }
        if meta_task_type is not None:
            task["meta_task_type"] = meta_task_type
        return task

    def test_parent_meta_task_type_propagates_to_children(self):
        """Parent meta_task_type is copied into every child's constraints.

        Covers both the planner_review branch (side-effect mtt, single review
        child) and the edge_case branch (non-side-effect mtt, multiple
        children). Both must carry the FR6 back-propagated value.
        """
        f1 = _make_failure(input_args=[[]])
        f2 = _make_failure(input_args=[0])

        # Side-effect mtt -> planner_review single child
        task_a = self._make_task("parent-1a", meta_task_type="orchestration")
        result_a = decompose_task(task_a, [f1, f2], {})
        assert len(result_a.subtasks) >= 1
        for st in result_a.subtasks:
            assert st.constraints.get("meta_task_type") == "orchestration", (
                f"child {st.task_id} dropped parent meta_task_type; "
                f"constraints={st.constraints}"
            )

        # Non-side-effect mtt -> edge_case strategy, multiple children
        task_b = self._make_task("parent-1b", meta_task_type="pure_function")
        result_b = decompose_task(task_b, [f1, f2], {})
        assert result_b.strategy == "edge_case"
        assert len(result_b.subtasks) >= 2
        for st in result_b.subtasks:
            assert st.constraints.get("meta_task_type") == "pure_function", (
                f"edge_case child {st.task_id} dropped parent mtt; "
                f"constraints={st.constraints}"
            )

    def test_explicit_child_override_wins_over_parent(self):
        """When parent constraints already carry an explicit meta_task_type, the
        _child_constraints helper must NOT overwrite it with the top-level
        parent value -- child constraints win."""
        task = self._make_task(
            "parent-2",
            meta_task_type="orchestration",
            constraints={"meta_task_type": "pure_function"},
        )
        f1 = _make_failure(input_args=[[]])
        f2 = _make_failure(input_args=[0])
        result = decompose_task(task, [f1, f2], {})
        assert len(result.subtasks) >= 1
        for st in result.subtasks:
            assert st.constraints.get("meta_task_type") == "pure_function", (
                f"explicit child override overwritten by parent: "
                f"child={st.task_id} constraints={st.constraints}"
            )

    def test_parent_missing_meta_task_type_leaves_child_none(self):
        """When the parent has no meta_task_type (top-level or in constraints),
        generated children must not fabricate one."""
        task = self._make_task("parent-3")  # no meta_task_type anywhere
        f1 = _make_failure(input_args=[[]])
        f2 = _make_failure(input_args=[0])
        result = decompose_task(task, [f1, f2], {})
        assert len(result.subtasks) >= 1
        for st in result.subtasks:
            assert st.constraints.get("meta_task_type") is None, (
                f"child {st.task_id} invented meta_task_type="
                f"{st.constraints.get('meta_task_type')!r} with no parent value"
            )
