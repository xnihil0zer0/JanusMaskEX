"""A2 — the planner must attach a mutation_target to test_authoring tasks.

Blocker-2 root cause: the auto-commit non-vacuity gate
(orchestrator.py: ``if _mtt == 'test_authoring' ...``) rejects any
``test_authoring`` task that declares neither ``mutation_target`` nor
``mutations[]`` as ``mutation_gate_missing`` (fail-closed). No planner emitted
one, so every test-authoring child task hung at the gate. The fix is two-pronged:

  * blind_draft.py planning prompt instructs the agent to emit a bare-dotted
    ``mutation_target`` (the module-under-test) for every ``test_authoring`` task.
  * plan_validator.validate_plan rejects a ``test_authoring`` task that carries
    neither a valid ``mutation_target`` nor a non-empty ``mutations[]`` — so a
    non-complying draft is caught at planning time (``invalid``) instead of
    failing late at the auto-commit mutation gate.

These oracles pin both halves.
"""
from harness.planner.plan_validator import validate_plan
from harness.planner.blind_draft import _planning_prompt
from harness.planner.brief_loader import PlanningBrief


def _ta_task(**overrides):
    """A schema-complete ``test_authoring`` task (test_* meta skips the
    token-budget/test_spec ratio checks, so only top-level fields + the new
    mutation_target rule apply)."""
    task = {
        "task_id": "T-TA",
        "title": "Hermetic oracle for symbol_ledger",
        "meta_task_type": "test_authoring",
        "priority": "high",
        "dependencies": [],
        "files_touched": ["tests/test_symbol_ledger.py"],
        "acceptance_criteria": ["oracle fails against a mutant"],
        "spec_author": None,
        "estimated_complexity": "low",
        "verification_command": "true",
        "spec": {
            "objective": "pin symbol_ledger signatures",
            "functional_requirements": ["fr1"],
            "interfaces": {},
            "edge_cases": [],
            "non_goals": [],
            "implementation_notes": "notes",
        },
        "test_spec": {
            "unit_tests": ["u1"],
            "integration_tests": ["i1"],
            "property_tests": [],
            "regression_tests": [],
            "minimum_test_count": 1,
            "test_data_requirements": "",
        },
        "token_budget_ratio": {"implementation_tokens": 0, "test_tokens": 20, "note": ""},
        "attribution_metadata": {"proposed_by": "claude", "reconciled": False, "diff_resolution": ""},
    }
    task.update(overrides)
    return task


def _plan(task):
    return {"tasks": [task]}


def test_A2a_test_authoring_without_mutation_target_flagged():
    v = validate_plan(_plan(_ta_task()))
    assert any(x.code == "missing_mutation_target" for x in v), (
        f"test_authoring task lacking mutation_target/mutations[] must be flagged; got {v}"
    )


def test_A2b_test_authoring_with_valid_mutation_target_ok():
    v = validate_plan(_plan(_ta_task(mutation_target="harness.symbol_ledger")))
    assert not any(x.code in ("missing_mutation_target", "invalid_mutation_target") for x in v), (
        f"valid bare-dotted mutation_target must satisfy the gate; got {v}"
    )


def test_A2c_test_authoring_with_mutations_list_ok():
    v = validate_plan(_plan(_ta_task(mutations=[{"stub_target": "harness.symbol_ledger"}])))
    assert not any(x.code == "missing_mutation_target" for x in v), (
        f"a non-empty mutations[] is an accepted alternative to mutation_target; got {v}"
    )


def test_A2d_malformed_mutation_target_flagged():
    # path-like / .py-suffixed values are not bare dotted module names
    v = validate_plan(_plan(_ta_task(mutation_target="tests/test_symbol_ledger.py")))
    assert any(x.code == "invalid_mutation_target" for x in v), (
        f"a path-like mutation_target must be flagged invalid; got {v}"
    )


def test_A2e_non_test_authoring_task_not_required_to_declare_mutant():
    # A refactor task without mutation_target must NOT trip the new rule.
    v = validate_plan(_plan(_ta_task(meta_task_type="refactor", task_id="T-RF")))
    assert not any(x.code in ("missing_mutation_target", "invalid_mutation_target") for x in v), (
        f"the mutation_target rule must only apply to test_authoring; got {v}"
    )


def test_A2f_planning_prompt_instructs_mutation_target():
    brief = PlanningBrief(
        title="t", scope="s", non_goals=[], inputs=[], deliverables=[],
        raw_text="body", source_path="b.md", sha256="0" * 64,
    )
    prompt = _planning_prompt(brief)
    assert "mutation_target" in prompt and "test_authoring" in prompt, (
        "the leaf planning prompt must instruct the agent to emit a mutation_target "
        "for test_authoring tasks"
    )
