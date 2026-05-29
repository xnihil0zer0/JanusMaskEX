"""Coverage pins — harness/planner/plan_validator.py (Plan 04, CASE-N).

One violation code per case, plus the GAP-5 note that ``dfs`` (lines 150-167)
is dead code — only ``dfs2`` runs cycle detection (and emits each cycle exactly
once). Wrapper checks for source_brief traceability + the D8 hard ValueError on
blank verification_command.
"""
from __future__ import annotations

import copy
import pathlib
import sys

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from harness.planner.plan_validator import (  # noqa: E402
    validate_plan,
    validate_plan_wrapper,
)


def _valid_task(task_id="T1"):
    return {
        "task_id": task_id,
        "title": "t",
        "meta_task_type": "docs_writing",
        "priority": "low",
        "dependencies": [],
        "files_touched": ["docs/x.md"],
        "acceptance_criteria": ["x"],
        "spec_author": None,
        "estimated_complexity": "low",
        "verification_command": "echo ok",
        "spec": {
            "objective": "o",
            "functional_requirements": ["r1"],
            "interfaces": "i",
            "edge_cases": ["e1", "e2"],
            "non_goals": ["integration_tests"],
            "implementation_notes": "n",
        },
        "test_spec": {
            "unit_tests": [{"name": "u1"}, {"name": "u2"}],
            "integration_tests": [],
            "property_tests": [],
            "regression_tests": [{"name": "r1"}, {"name": "r2"}],
            "minimum_test_count": 2,
            "test_data_requirements": "none",
        },
        "token_budget_ratio": {
            "implementation_tokens": 100,
            "test_tokens": 200,
            "note": "n",
        },
        "attribution_metadata": {
            "proposed_by": "test",
            "reconciled": False,
            "diff_resolution": None,
        },
    }


def _codes(violations):
    return {v.code for v in violations}


class TestBaselineClean:
    def test_minimal_valid_task_has_no_violations(self):
        assert validate_plan({"tasks": [_valid_task()]}) == []


class TestMissingFields:
    @pytest.mark.parametrize("field", [
        "task_id", "title", "meta_task_type", "priority", "dependencies",
        "files_touched", "acceptance_criteria", "spec_author",
        "estimated_complexity", "verification_command",
    ])
    def test_missing_top_level_field(self, field):
        t = _valid_task()
        del t[field]
        codes = _codes(validate_plan({"tasks": [t]}))
        # meta_task_type/priority absence have dedicated codes; the rest are missing_field.
        assert "missing_field" in codes or {
            "missing_meta_task_type"} & codes

    @pytest.mark.parametrize("field", [
        "objective", "functional_requirements", "interfaces",
        "edge_cases", "non_goals", "implementation_notes",
    ])
    def test_missing_spec_field(self, field):
        t = _valid_task()
        del t["spec"][field]
        assert "missing_field" in _codes(validate_plan({"tasks": [t]}))

    @pytest.mark.parametrize("field", [
        "unit_tests", "integration_tests", "property_tests",
        "regression_tests", "minimum_test_count", "test_data_requirements",
    ])
    def test_missing_test_spec_field(self, field):
        t = _valid_task()
        del t["test_spec"][field]
        assert "missing_field" in _codes(validate_plan({"tasks": [t]}))

    @pytest.mark.parametrize("field", ["implementation_tokens", "test_tokens", "note"])
    def test_missing_budget_field(self, field):
        t = _valid_task()
        del t["token_budget_ratio"][field]
        assert "missing_field" in _codes(validate_plan({"tasks": [t]}))

    @pytest.mark.parametrize("field", ["proposed_by", "reconciled", "diff_resolution"])
    def test_missing_attr_field(self, field):
        t = _valid_task()
        del t["attribution_metadata"][field]
        assert "missing_field" in _codes(validate_plan({"tasks": [t]}))


class TestMetaTaskType:
    def test_unknown_meta_task_type(self):
        t = _valid_task()
        t["meta_task_type"] = "totally_made_up"
        assert "unknown_meta_task_type" in _codes(validate_plan({"tasks": [t]}))

    def test_empty_meta_task_type(self):
        t = _valid_task()
        t["meta_task_type"] = ""
        assert "missing_meta_task_type" in _codes(validate_plan({"tasks": [t]}))

    def test_non_str_meta_task_type(self):
        t = _valid_task()
        t["meta_task_type"] = 123
        assert "missing_meta_task_type" in _codes(validate_plan({"tasks": [t]}))


class TestPriority:
    def test_non_str_priority(self):
        t = _valid_task()
        t["priority"] = 5
        assert "invalid_priority_type" in _codes(validate_plan({"tasks": [t]}))

    def test_non_canonical_priority(self):
        t = _valid_task()
        t["priority"] = "URGENT"
        assert "invalid_priority_encoding" in _codes(validate_plan({"tasks": [t]}))


class TestGraph:
    def test_duplicate_task_id(self):
        plan = {"tasks": [_valid_task("DUP"), _valid_task("DUP")]}
        assert "duplicate_task_id" in _codes(validate_plan(plan))

    def test_dependency_cycle_reported_exactly_once(self):
        """GAP-5: dfs (150-167) is dead; dfs2 (187-189) detects the cycle and
        dedups via found_cycles_nodes -> exactly one dependency_cycle row."""
        a = _valid_task("A")
        b = _valid_task("B")
        a["dependencies"] = ["B"]
        b["dependencies"] = ["A"]
        violations = validate_plan({"tasks": [a, b]})
        cycle_rows = [v for v in violations if v.code == "dependency_cycle"]
        assert len(cycle_rows) == 1, (
            f"cycle must be reported exactly once, got {len(cycle_rows)}"
        )


class TestTestRatioRules:
    def test_test_ratio_violation_when_below_1_5x(self):
        t = _valid_task()
        t["meta_task_type"] = "refactor"  # non-test -> ratio rules apply
        t["token_budget_ratio"] = {"implementation_tokens": 100, "test_tokens": 100, "note": "n"}
        assert "test_ratio_violation" in _codes(validate_plan({"tasks": [t]}))

    def test_test_ratio_violation_when_impl_zero_and_test_zero(self):
        t = _valid_task()
        t["meta_task_type"] = "refactor"
        t["token_budget_ratio"] = {"implementation_tokens": 0, "test_tokens": 0, "note": "n"}
        assert "test_ratio_violation" in _codes(validate_plan({"tasks": [t]}))

    def test_insufficient_unit_tests(self):
        t = _valid_task()
        t["meta_task_type"] = "refactor"
        t["spec"]["functional_requirements"] = ["r1", "r2", "r3"]
        t["test_spec"]["unit_tests"] = [{"name": "u1"}]  # < 3
        assert "insufficient_unit_tests" in _codes(validate_plan({"tasks": [t]}))

    def test_missing_integration_test(self):
        t = _valid_task()
        t["meta_task_type"] = "refactor"
        t["spec"]["non_goals"] = ["something unrelated"]  # not excused
        t["test_spec"]["integration_tests"] = []
        assert "missing_integration_test" in _codes(validate_plan({"tasks": [t]}))

    def test_integration_test_excused_via_non_goal(self):
        t = _valid_task()
        t["meta_task_type"] = "refactor"
        t["spec"]["non_goals"] = ["no integration tests for this leaf"]
        t["test_spec"]["integration_tests"] = []
        assert "missing_integration_test" not in _codes(validate_plan({"tasks": [t]}))

    def test_missing_edge_case_tests(self):
        t = _valid_task()
        t["meta_task_type"] = "refactor"
        t["spec"]["edge_cases"] = ["e1", "e2"]
        t["test_spec"]["property_tests"] = []
        t["test_spec"]["regression_tests"] = []  # needed=2, have 0
        assert "missing_edge_case_tests" in _codes(validate_plan({"tasks": [t]}))

    def test_insufficient_total_tests(self):
        t = _valid_task()
        t["meta_task_type"] = "refactor"
        t["spec"]["functional_requirements"] = ["r1", "r2"]
        t["test_spec"]["minimum_test_count"] = 1  # < 1.5*2 = 3
        # keep unit_tests >= frs to isolate the total-count rule
        t["test_spec"]["unit_tests"] = [{"name": "u1"}, {"name": "u2"}]
        assert "insufficient_total_tests" in _codes(validate_plan({"tasks": [t]}))

    def test_test_meta_task_type_skips_ratio_rules(self):
        """meta_task_type startswith 'test_' bypasses ratio/test-count rules."""
        t = _valid_task()
        t["meta_task_type"] = "test_authoring"
        t["token_budget_ratio"] = {"implementation_tokens": 100, "test_tokens": 0, "note": "n"}
        t["test_spec"]["minimum_test_count"] = 0
        t["test_spec"]["unit_tests"] = []
        codes = _codes(validate_plan({"tasks": [t]}))
        # taxonomy may reject 'test_authoring'; the POINT is no ratio/count codes fire.
        for c in ("test_ratio_violation", "insufficient_unit_tests",
                  "insufficient_total_tests", "missing_integration_test",
                  "missing_edge_case_tests"):
            assert c not in codes, f"{c} should be skipped for test_ meta type"


class TestWrapper:
    def test_missing_source_brief_path(self):
        plan = {"source_brief_sha256": "a" * 64, "tasks": []}
        assert "missing_wrapper_field" in _codes(validate_plan_wrapper(plan))

    def test_missing_source_brief_sha256(self):
        plan = {"source_brief_path": "brief.md", "tasks": []}
        assert "missing_wrapper_field" in _codes(validate_plan_wrapper(plan))

    def test_bad_sha_length(self):
        plan = {"source_brief_path": "b.md", "source_brief_sha256": "abc", "tasks": []}
        assert "invalid_sha256" in _codes(validate_plan_wrapper(plan))

    def test_bad_sha_charset(self):
        plan = {"source_brief_path": "b.md", "source_brief_sha256": "z" * 64, "tasks": []}
        assert "invalid_sha256" in _codes(validate_plan_wrapper(plan))

    def test_well_formed_wrapper_no_violations(self):
        plan = {
            "source_brief_path": "b.md",
            "source_brief_sha256": "a" * 64,
            "tasks": [_valid_task()],
        }
        assert validate_plan_wrapper(plan) == []

    def test_blank_verification_command_raises(self):
        t = _valid_task()
        t["verification_command"] = "   "
        plan = {
            "source_brief_path": "b.md",
            "source_brief_sha256": "a" * 64,
            "tasks": [t],
        }
        with pytest.raises(ValueError, match="verification_command"):
            validate_plan_wrapper(plan)


class TestDeadDfsGap5:
    def test_dfs_is_defined_but_unreferenced(self):
        """GAP-5: ``dfs`` exists in source but is never called; ``dfs2`` is the
        only invoked cycle detector. Pin both presence + that dfs2 is the caller."""
        import inspect
        from harness.planner import plan_validator
        src = inspect.getsource(plan_validator.validate_plan)
        assert "def dfs(" in src and "def dfs2(" in src
        # dfs2 is invoked in the node loop; bare dfs( is only its own def.
        assert "dfs2(node, [])" in src, "dfs2 must be the live cycle detector"
        # The only `dfs(` reference outside its own def line is the self-recursive
        # `if dfs(neighbor):` INSIDE dfs's body — and since dfs is never entered
        # from the module-level node loop, that recursion is unreachable too.
        # The node loop invokes ONLY dfs2; there is no `dfs2(neighbor` recursion
        # collision because dfs2's recursion is `dfs2(neighbor, current_path)`.
        non_def = [ln.strip() for ln in src.splitlines()
                   if "dfs(" in ln and "def dfs(" not in ln and "dfs2" not in ln]
        assert non_def == ["if dfs(neighbor):"], (
            f"unexpected dfs() references (dfs should be dead): {non_def!r}"
        )
        # Confirm the live driver loop calls dfs2, not dfs.
        loop_calls_dfs2 = any(
            "dfs2(node, [])" in ln for ln in src.splitlines()
        )
        assert loop_calls_dfs2
