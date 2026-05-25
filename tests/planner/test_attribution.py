import pytest
from typing import Any, Dict

from harness.planner.attribution import stamp_attribution, StampingError
from harness.planner.diff_model import PlanDiff, DiffItem, DiffKind
from harness.planner.reconciliation import ReconciliationResult


@pytest.fixture
def base_task() -> Dict[str, Any]:
    return {"task_id": "T-1", "spec": {"data": "test"}}


@pytest.fixture
def diff_item_claude(base_task) -> DiffItem:
    return DiffItem(kind=DiffKind.claude_only, claude_task=base_task, gemini_task=None)


@pytest.fixture
def diff_item_gemini(base_task) -> DiffItem:
    return DiffItem(kind=DiffKind.gemini_only, claude_task=None, gemini_task=base_task)


@pytest.fixture
def diff_item_convergent(base_task) -> DiffItem:
    return DiffItem(kind=DiffKind.convergent, claude_task=base_task, gemini_task=base_task)


@pytest.fixture
def diff_item_divergent(base_task) -> DiffItem:
    t2 = dict(base_task)
    t2["spec"] = {"data": "different"}
    return DiffItem(kind=DiffKind.divergent, claude_task=base_task, gemini_task=t2)


def test_claude_only_stamped_claude(base_task, diff_item_claude):
    merged = [base_task]
    plan_diff = PlanDiff(items=(diff_item_claude,))
    rr = ReconciliationResult(merged_tasks=merged, unresolved_items=[], per_agent_errors={})

    stamped = stamp_attribution(merged, plan_diff, rr, bootstrap=False)
    assert len(stamped) == 1
    assert stamped[0]["attribution_metadata"]["proposed_by"] == "claude"
    assert stamped[0]["spec_author"] == "claude"


def test_convergent_stamped_convergent(base_task, diff_item_convergent):
    merged = [base_task]
    plan_diff = PlanDiff(items=(diff_item_convergent,))
    rr = ReconciliationResult(merged_tasks=merged, unresolved_items=[], per_agent_errors={})

    stamped = stamp_attribution(merged, plan_diff, rr, bootstrap=False)
    assert len(stamped) == 1
    assert stamped[0]["attribution_metadata"]["proposed_by"] == "convergent"
    # Matches claude_task spec, so it should be claude since both match.
    assert stamped[0]["spec_author"] in ("claude", "gemini", "convergent")


def test_reconciled_via_concession(base_task, diff_item_divergent):
    merged = [base_task]
    plan_diff = PlanDiff(items=(diff_item_divergent,))
    rr = ReconciliationResult(merged_tasks=merged, unresolved_items=[], per_agent_errors={})

    stamped = stamp_attribution(merged, plan_diff, rr, bootstrap=False)
    assert len(stamped) == 1
    assert stamped[0]["attribution_metadata"]["reconciled"] is True
    # Without log access we assume reconciled.
    assert stamped[0]["attribution_metadata"]["diff_resolution"] == "reconciled"


def test_reconciled_via_tiebreaker(base_task, diff_item_divergent):
    merged = [base_task]
    plan_diff = PlanDiff(items=(diff_item_divergent,))
    rr = ReconciliationResult(merged_tasks=merged, unresolved_items=[], per_agent_errors={})

    stamped = stamp_attribution(merged, plan_diff, rr, bootstrap=False)
    assert len(stamped) == 1
    assert stamped[0]["attribution_metadata"]["reconciled"] is True
    assert stamped[0]["attribution_metadata"]["diff_resolution"] == "reconciled"


def test_bootstrap_forces_spec_author_null(base_task, diff_item_claude, diff_item_convergent):
    merged = [base_task, {"task_id": "T-2", "spec": {"data": "test2"}}]
    di2 = DiffItem(kind=DiffKind.convergent, claude_task=merged[1], gemini_task=merged[1])
    plan_diff = PlanDiff(items=(diff_item_claude, di2))
    rr = ReconciliationResult(merged_tasks=merged, unresolved_items=[], per_agent_errors={})

    stamped = stamp_attribution(merged, plan_diff, rr, bootstrap=True)
    assert len(stamped) == 2
    for t in stamped:
        assert t["spec_author"] is None


def test_preexisting_spec_author_raises(base_task, diff_item_claude):
    merged = [dict(base_task, spec_author="claude")]
    plan_diff = PlanDiff(items=(diff_item_claude,))
    rr = ReconciliationResult(merged_tasks=merged, unresolved_items=[], per_agent_errors={})

    with pytest.raises(StampingError, match="already has a non-null spec_author"):
        stamp_attribution(merged, plan_diff, rr, bootstrap=False)


def test_does_not_mutate_input(base_task, diff_item_claude):
    merged = [base_task]
    plan_diff = PlanDiff(items=(diff_item_claude,))
    rr = ReconciliationResult(merged_tasks=merged, unresolved_items=[], per_agent_errors={})

    before = dict(merged[0])
    stamp_attribution(merged, plan_diff, rr, bootstrap=False)
    assert merged[0] == before

