import pytest
import json
import subprocess
from pathlib import Path
from harness.planner.plan_validator import validate_plan, PlanViolation

def get_valid_plan():
    return {
      "source_brief_path": "brief_stab_001.md",
      "source_brief_sha256": "dfc7d0e0de0fe2a2adfc2460bddafec3c54620f462425dfc1473266865bdf985",
      "tasks": [
        {
          "task_id": "T-001",
          "title": "Minimal Valid Task",
          "meta_task_type": "data_model",
          "priority": "critical",
          "dependencies": [],
          "files_touched": [],
          "acceptance_criteria": [],
          "spec_author": None,
          "estimated_complexity": "low",
          "verification_command": "true",
          "spec": {
            "objective": "obj",
            "functional_requirements": ["fr1"],
            "interfaces": {},
            "edge_cases": [],
            "non_goals": [],
            "implementation_notes": "notes"
          },
          "test_spec": {
            "unit_tests": ["u1"],
            "integration_tests": ["i1"],
            "property_tests": [],
            "regression_tests": [],
            "minimum_test_count": 2,
            "test_data_requirements": ""
          },
          "token_budget_ratio": {
            "implementation_tokens": 10,
            "test_tokens": 20,
            "note": ""
          },
          "attribution_metadata": {
            "proposed_by": "claude",
            "reconciled": True,
            "diff_resolution": "tiebreaker"
          }
        }
      ]
    }

def test_valid_plan_returns_no_violations():
    plan = get_valid_plan()
    violations = validate_plan(plan)
    assert len(violations) == 0, f"Expected no violations, got: {violations}"

def test_missing_required_field_flagged():
    plan = get_valid_plan()
    del plan["tasks"][0]["spec"]["objective"]
    violations = validate_plan(plan)
    assert any(v.code == "missing_field" and "objective" in v.path for v in violations)

def test_test_heavy_ratio_violation():
    plan = get_valid_plan()
    plan["tasks"][0]["token_budget_ratio"]["implementation_tokens"] = 2
    plan["tasks"][0]["token_budget_ratio"]["test_tokens"] = 2
    violations = validate_plan(plan)
    assert any(v.code == "test_ratio_violation" for v in violations)

def test_unit_test_count_below_fr_count_flagged():
    plan = get_valid_plan()
    plan["tasks"][0]["spec"]["functional_requirements"] = ["fr1", "fr2", "fr3", "fr4", "fr5"]
    plan["tasks"][0]["test_spec"]["unit_tests"] = ["u1", "u2", "u3"]
    plan["tasks"][0]["test_spec"]["minimum_test_count"] = 10 # to avoid this failing
    violations = validate_plan(plan)
    assert any(v.code == "insufficient_unit_tests" for v in violations)

def test_unknown_meta_task_type_flagged():
    plan = get_valid_plan()
    plan["tasks"][0]["meta_task_type"] = "bogus"
    violations = validate_plan(plan)
    assert any(v.code == "unknown_meta_task_type" for v in violations)

def test_test_prefix_exempts_ratio():
    plan = get_valid_plan()
    plan["tasks"][0]["meta_task_type"] = "test_unit"
    plan["tasks"][0]["token_budget_ratio"]["implementation_tokens"] = 10
    plan["tasks"][0]["token_budget_ratio"]["test_tokens"] = 5
    violations = validate_plan(plan)
    assert not any(v.code == "test_ratio_violation" for v in violations)

def test_duplicate_task_id_flagged():
    plan = get_valid_plan()
    task2 = json.loads(json.dumps(plan["tasks"][0]))
    plan["tasks"].append(task2)
    violations = validate_plan(plan)
    assert any(v.code == "duplicate_task_id" for v in violations)

def test_dependency_cycle_flagged():
    plan = get_valid_plan()
    task2 = json.loads(json.dumps(plan["tasks"][0]))
    task2["task_id"] = "T-002"
    plan["tasks"].append(task2)
    plan["tasks"][0]["dependencies"] = ["T-002"]
    plan["tasks"][1]["dependencies"] = ["T-001"]
    violations = validate_plan(plan)
    assert any(v.code == "dependency_cycle" for v in violations)

def test_attribution_mismatch_flagged():
    plan = get_valid_plan()
    plan["tasks"][0]["spec_author"] = "claude"
    plan["tasks"][0]["attribution_metadata"]["proposed_by"] = None
    violations = validate_plan(plan)
    assert any(v.code == "attribution_mismatch" for v in violations)

def test_plan_validate_cli_exit_codes(tmp_path):
    good_json = tmp_path / "good.json"
    bad_json = tmp_path / "bad.json"
    with open(good_json, "w") as f:
        json.dump(get_valid_plan(), f)
    bad_plan = get_valid_plan()
    del bad_plan["tasks"][0]["title"]
    with open(bad_json, "w") as f:
        json.dump(bad_plan, f)
        
    script_path = str(Path(__file__).parent.parent.parent / "scripts" / "plan-validate.sh")
    good_res = subprocess.run([script_path, str(good_json)], capture_output=True)
    assert good_res.returncode == 0
    
    bad_res = subprocess.run([script_path, str(bad_json)], capture_output=True)
    assert bad_res.returncode != 0
    assert b"missing_field" in bad_res.stdout or b"missing_field" in bad_res.stderr

from hypothesis import given, strategies as st

@given(st.recursive(st.dictionaries(st.text(), st.integers() | st.text() | st.booleans() | st.none()), st.lists))
def test_validator_never_raises(plan_dict):
    if not isinstance(plan_dict, dict):
        return
    try:
        violations = validate_plan(plan_dict)
        assert isinstance(violations, list)
    except Exception as e:
        pytest.fail(f"validate_plan raised {e} on dict {plan_dict}")

def test_zero_fr_task_does_not_crash():
    plan = get_valid_plan()
    plan["tasks"][0]["spec"]["functional_requirements"] = []
    plan["tasks"][0]["test_spec"]["minimum_test_count"] = 0
    plan["tasks"][0]["test_spec"]["unit_tests"] = []
    violations = validate_plan(plan)
    assert not any(v.code == "insufficient_unit_tests" for v in violations)
    assert not any(v.code == "insufficient_total_tests" for v in violations)

def test_zero_impl_tokens_handled():
    plan = get_valid_plan()
    plan["tasks"][0]["token_budget_ratio"]["implementation_tokens"] = 0
    plan["tasks"][0]["token_budget_ratio"]["test_tokens"] = 1
    violations = validate_plan(plan)
    assert not any(v.code == "test_ratio_violation" for v in violations)
    
    plan["tasks"][0]["token_budget_ratio"]["test_tokens"] = 0
    violations = validate_plan(plan)
    assert any(v.code == "test_ratio_violation" for v in violations)


# ── validate_plan_wrapper ───────────────────────────────────────────────

from harness.planner.plan_validator import validate_plan_wrapper


class TestValidatePlanWrapper:
    def test_canonical_wrapper_no_violations(self):
        plan = {
            "source_brief_path": "brief_stab_001.md",
            "source_brief_sha256": "dfc7d0e0de0fe2a2adfc2460bddafec3c54620f462425dfc1473266865bdf985",
            "tasks": [],
        }
        assert validate_plan_wrapper(plan) == []

    def test_missing_source_brief_path_flagged(self):
        plan = {"source_brief_sha256": "a" * 64, "tasks": []}
        violations = validate_plan_wrapper(plan)
        assert any(v.code == "missing_wrapper_field" and v.path.endswith("source_brief_path") for v in violations)

    def test_missing_source_brief_sha256_flagged(self):
        plan = {"source_brief_path": "brief.md", "tasks": []}
        violations = validate_plan_wrapper(plan)
        assert any(v.code == "missing_wrapper_field" and v.path.endswith("source_brief_sha256") for v in violations)

    def test_empty_string_wrapper_fields_flagged(self):
        plan = {"source_brief_path": "", "source_brief_sha256": ""}
        violations = validate_plan_wrapper(plan)
        assert len(violations) == 2
        assert all(v.code == "missing_wrapper_field" for v in violations)

    def test_non_str_source_brief_path_flagged(self):
        plan = {"source_brief_path": 123, "source_brief_sha256": "a" * 64}
        violations = validate_plan_wrapper(plan)
        assert any(v.code == "invalid_wrapper_type" for v in violations)

    def test_short_sha256_flagged(self):
        plan = {"source_brief_path": "brief.md", "source_brief_sha256": "abc"}
        violations = validate_plan_wrapper(plan)
        assert any(v.code == "invalid_sha256" for v in violations)

    def test_non_hex_sha256_flagged(self):
        plan = {"source_brief_path": "brief.md", "source_brief_sha256": "zzz" + "a" * 61}
        violations = validate_plan_wrapper(plan)
        assert any(v.code == "invalid_sha256" for v in violations)

    def test_uppercase_hex_sha256_accepted(self):
        plan = {"source_brief_path": "brief.md", "source_brief_sha256": "A" * 64}
        assert validate_plan_wrapper(plan) == []

    def test_non_object_plan_flagged(self):
        violations = validate_plan_wrapper("not a dict")
        # Interpreted as path by validate_plan_wrapper — will parse_error
        assert any(v.code == "parse_error" for v in violations)

    def test_list_plan_flagged(self):
        violations = validate_plan_wrapper([{"tasks": []}])
        assert any(v.code == "invalid_structure" for v in violations)

    def test_path_argument_missing_file(self, tmp_path):
        violations = validate_plan_wrapper(str(tmp_path / "does_not_exist.json"))
        assert any(v.code == "parse_error" for v in violations)

    def test_path_argument_valid_file(self, tmp_path):
        import json as _json
        plan = {
            "source_brief_path": "brief.md",
            "source_brief_sha256": "a" * 64,
        }
        pfile = tmp_path / "plan.json"
        pfile.write_text(_json.dumps(plan))
        assert validate_plan_wrapper(str(pfile)) == []

    def test_validate_plan_does_not_regress_on_wrapper_only_check(self):
        """validate_plan must NOT start rejecting plans that lack wrapper fields —
        wrapper validation is opt-in via validate_plan_wrapper, not auto-enforced."""
        plan = {"tasks": [get_valid_plan()["tasks"][0]]}
        body_violations = validate_plan(plan)
        # Existing body checks may still flag things, but no missing_wrapper_field
        assert not any(v.code == "missing_wrapper_field" for v in body_violations)

