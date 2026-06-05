"""Oracle for Brief 4: register the epic_planning meta-task-type.

RED on HEAD: META_TASK_POLICY has no epic_planning key, so it is absent from
every derived frozenset.

epic_planning emits BRIEFS, not code — so it must bypass the fuzzer, skip
structural decomposition, and skip smoke gates (mirrors harness_self_fix /
test_* policy). The derived frozensets must pick the new key up automatically.
"""
from __future__ import annotations

from harness.planner.taxonomies import (
    BYPASS_FUZZER_TYPES,
    META_TASK_POLICY,
    META_TASK_TYPES,
    SIDE_EFFECT_META_TYPES,
    SKIP_SMOKE_GATE_TYPES,
)


def test_epic_planning_registered() -> None:
    assert "epic_planning" in META_TASK_POLICY
    assert "epic_planning" in META_TASK_TYPES


def test_epic_planning_policy_flags() -> None:
    policy = META_TASK_POLICY["epic_planning"]
    assert policy.get("bypass_fuzzer") is True
    assert policy.get("skip_structural_decomp") is True
    assert policy.get("skip_smoke_gates") is True


def test_epic_planning_in_derived_frozensets() -> None:
    # The derived frozensets are computed from the policy dict at import time;
    # they must include epic_planning without any extra wiring.
    assert "epic_planning" in BYPASS_FUZZER_TYPES
    assert "epic_planning" in SIDE_EFFECT_META_TYPES
    assert "epic_planning" in SKIP_SMOKE_GATE_TYPES


def test_existing_taxonomy_untouched() -> None:
    # Regression guard: the new key is additive — a representative sample of the
    # pre-existing taxonomy must still be present and unchanged.
    for existing in ("harness_self_fix", "data_model", "refactor", "test_unit"):
        assert existing in META_TASK_TYPES
    assert META_TASK_POLICY["harness_self_fix"]["bypass_fuzzer"] is True
