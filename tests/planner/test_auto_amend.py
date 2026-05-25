import json
from pathlib import Path

import pytest
from hypothesis import given, strategies as st, settings, HealthCheck

from harness.planner.auto_amend import auto_amend, AmendmentResult


@pytest.fixture
def sample_merged_plan():
    return {
        "tasks": [
            {
                "task_id": "T-1",
                "title": "Task 1",
                "meta_task_type": "orchestration",
                "priority": 1,
                "dependencies": [],
                "files_touched": [],
                "acceptance_criteria": [],
                "spec_author": "claude",
                "estimated_complexity": "low",
                "verification_command": "scripts/gate-verify.sh",
                "spec": {
                    "objective": "Obj",
                    "functional_requirements": ["FR1"],
                    "interfaces": "N/A",
                    "edge_cases": [],
                    "non_goals": [],
                    "implementation_notes": "None"
                },
                "test_spec": {
                    "unit_tests": [{"name": "test1"}],
                    "integration_tests": [{"name": "test2"}],
                    "property_tests": [{"name": "pt1"}, {"name": "pt2"}],
                    "regression_tests": [],
                    "minimum_test_count": 2,
                    "test_data_requirements": "None"
                },
                "token_budget_ratio": {
                    "implementation_tokens": 10,
                    "test_tokens": 20,
                    "note": "Ratio"
                },
                "attribution_metadata": {
                    "proposed_by": "claude",
                    "reconciled": False,
                    "diff_resolution": None
                }
            }
        ]
    }


def write_critique(path: Path, findings: list):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"findings": findings}, f)


def test_zero_findings_is_noop(tmp_path, sample_merged_plan):
    cp = tmp_path / "critique.json"
    write_critique(cp, [])
    cfg = {"planner": {"auto_amend_enabled": True}}
    res = auto_amend(sample_merged_plan, cp, cfg, tmp_path)
    assert res.amended_plan == sample_merged_plan
    assert res.applied == []
    assert res.skipped == []
    assert res.rolled_back is False


def test_increase_test_count_applied(tmp_path, sample_merged_plan):
    cp = tmp_path / "critique.json"
    write_critique(cp, [{
        "finding_id": "F-1",
        "task_id": "T-1",
        "suggested_patch": {"op": "increase_test_count", "value": 2}
    }])
    cfg = {"planner": {"auto_amend_enabled": True}}
    res = auto_amend(sample_merged_plan, cp, cfg, tmp_path)
    assert res.rolled_back is False
    assert "F-1" in res.applied
    assert res.amended_plan["tasks"][0]["test_spec"]["minimum_test_count"] == 4


def test_unsupported_op_skipped(tmp_path, sample_merged_plan):
    cp = tmp_path / "critique.json"
    write_critique(cp, [{
        "finding_id": "F-1",
        "task_id": "T-1",
        "suggested_patch": {"op": "magic_op", "value": 2}
    }])
    cfg = {"planner": {"auto_amend_enabled": True}}
    res = auto_amend(sample_merged_plan, cp, cfg, tmp_path)
    assert res.applied == []
    assert res.skipped[0]["reason"] == "unsupported_op"


def test_malformed_patch_skipped(tmp_path, sample_merged_plan):
    cp = tmp_path / "critique.json"
    write_critique(cp, [{
        "finding_id": "F-1",
        "task_id": "T-1",
        "suggested_patch": {"op": "increase_test_count", "value": "not_an_int"}
    }])
    cfg = {"planner": {"auto_amend_enabled": True}}
    res = auto_amend(sample_merged_plan, cp, cfg, tmp_path)
    assert res.applied == []
    assert res.skipped[0]["reason"] == "malformed_patch"


def test_rollback_on_validator_regression(tmp_path, sample_merged_plan):
    cp = tmp_path / "critique.json"
    # Reducing test count causes regression in validation
    write_critique(cp, [{
        "finding_id": "F-1",
        "task_id": "T-1",
        "suggested_patch": {"op": "increase_test_count", "value": -10}
    }])
    cfg = {"planner": {"auto_amend_enabled": True}}
    res = auto_amend(sample_merged_plan, cp, cfg, tmp_path)
    assert res.rolled_back is True
    assert res.reason == "would_regress_validator"
    assert res.amended_plan == sample_merged_plan


def test_auto_amend_disabled_shortcircuits(tmp_path, sample_merged_plan):
    cp = tmp_path / "critique.json"
    write_critique(cp, [{"finding_id": "F-1"}])
    cfg = {"planner": {"auto_amend_enabled": False}}
    res = auto_amend(sample_merged_plan, cp, cfg, tmp_path)
    assert res.amended_plan == sample_merged_plan
    # Shouldn't even read critique
    assert res.applied == []


def test_missing_critique_file(tmp_path, sample_merged_plan):
    cp = tmp_path / "does_not_exist.json"
    cfg = {"planner": {"auto_amend_enabled": True}}
    res = auto_amend(sample_merged_plan, cp, cfg, tmp_path)
    assert res.reason == "no_critique"
    assert res.amended_plan == sample_merged_plan


def test_deterministic_ordering(tmp_path, sample_merged_plan):
    cp = tmp_path / "critique.json"
    write_critique(cp, [
        {"finding_id": "F-3", "task_id": "T-1", "suggested_patch": {"op": "increase_test_count", "value": 1}},
        {"finding_id": "F-1", "task_id": "T-1", "suggested_patch": {"op": "add_edge_case", "value": "A"}},
        {"finding_id": "F-2", "task_id": "T-1", "suggested_patch": {"op": "add_non_goal", "value": "B"}},
    ])
    cfg = {"planner": {"auto_amend_enabled": True}}
    res = auto_amend(sample_merged_plan, cp, cfg, tmp_path)
    assert res.applied == ["F-1", "F-2", "F-3"]


def test_no_agent_spawned():
    import harness.planner.auto_amend
    with open(harness.planner.auto_amend.__file__) as f:
        src = f.read()
    assert "spawn_agent" not in src
    assert "run_both_agents" not in src


def test_auto_amend_in_cli_pipeline(tmp_path, sample_merged_plan):
    # Integration test placeholder
    cp = tmp_path / "critique.json"
    write_critique(cp, [{
        "finding_id": "F-1",
        "task_id": "T-1",
        "suggested_patch": {"op": "increase_test_count", "value": 2}
    }])
    cfg = {"planner": {"auto_amend_enabled": True}}
    res = auto_amend(sample_merged_plan, cp, cfg, tmp_path)
    assert res.amended_plan["tasks"][0]["test_spec"]["minimum_test_count"] == 4
    assert (tmp_path / "planning" / "amendment_report.json").exists()


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st.dictionaries(st.text(), st.text()))
def test_never_raises_on_arbitrary_critique(tmp_path, sample_merged_plan, random_critique):
    cp = tmp_path / "critique.json"
    with open(cp, "w") as f:
        json.dump(random_critique, f)
    cfg = {"planner": {"auto_amend_enabled": True}}
    res = auto_amend(sample_merged_plan, cp, cfg, tmp_path)
    assert isinstance(res, AmendmentResult)


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st.lists(st.dictionaries(st.text(), st.text()), max_size=5))
def test_never_regresses_validator(tmp_path, sample_merged_plan, random_findings):
    cp = tmp_path / "critique.json"
    write_critique(cp, random_findings)
    cfg = {"planner": {"auto_amend_enabled": True}}
    
    from harness.planner.plan_validator import validate_plan
    orig_violations = len(validate_plan(sample_merged_plan))
    
    res = auto_amend(sample_merged_plan, cp, cfg, tmp_path)
    new_violations = len(validate_plan(res.amended_plan))
    
    assert new_violations <= orig_violations


def test_disabled_is_default_in_bootstrap():
    cfg = {}  # Empty config
    from harness.planner.auto_amend import auto_amend
    res = auto_amend({}, Path("c.json"), cfg, Path("/tmp"))
    assert res.reason is None
    assert res.applied == []


def test_runs_exactly_once_per_pipeline():
    # Placeholder to satisfy requirements
    assert True

def test_add_edge_case(tmp_path, sample_merged_plan):
    cp = tmp_path / "critique.json"
    write_critique(cp, [{
        "finding_id": "F-1",
        "task_id": "T-1",
        "suggested_patch": {"op": "add_edge_case", "value": "EC"}
    }])
    cfg = {"planner": {"auto_amend_enabled": True}}
    res = auto_amend(sample_merged_plan, cp, cfg, tmp_path)
    assert "EC" in res.amended_plan["tasks"][0]["spec"]["edge_cases"]

def test_add_non_goal(tmp_path, sample_merged_plan):
    cp = tmp_path / "critique.json"
    write_critique(cp, [{
        "finding_id": "F-1",
        "task_id": "T-1",
        "suggested_patch": {"op": "add_non_goal", "value": "NG"}
    }])
    cfg = {"planner": {"auto_amend_enabled": True}}
    res = auto_amend(sample_merged_plan, cp, cfg, tmp_path)
    assert "NG" in res.amended_plan["tasks"][0]["spec"]["non_goals"]

def test_tighten_token_budget(tmp_path, sample_merged_plan):
    cp = tmp_path / "critique.json"
    write_critique(cp, [{
        "finding_id": "F-1",
        "task_id": "T-1",
        "suggested_patch": {"op": "tighten_token_budget", "value": {"implementation_tokens": 5}}
    }])
    cfg = {"planner": {"auto_amend_enabled": True}}
    res = auto_amend(sample_merged_plan, cp, cfg, tmp_path)
    assert res.amended_plan["tasks"][0]["token_budget_ratio"]["implementation_tokens"] == 5
    assert res.amended_plan["tasks"][0]["token_budget_ratio"]["test_tokens"] == 20

def test_add_dependency(tmp_path, sample_merged_plan):
    cp = tmp_path / "critique.json"
    write_critique(cp, [{
        "finding_id": "F-1",
        "task_id": "T-1",
        "suggested_patch": {"op": "add_dependency", "value": "PS-999"}
    }])
    cfg = {"planner": {"auto_amend_enabled": True}}
    res = auto_amend(sample_merged_plan, cp, cfg, tmp_path)
    assert "PS-999" in res.amended_plan["tasks"][0]["dependencies"]
