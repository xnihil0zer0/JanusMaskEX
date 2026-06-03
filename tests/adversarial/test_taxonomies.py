"""Tests for harness.planner.taxonomies policy record and derived frozensets."""

import pytest

from harness.planner.taxonomies import (
    BYPASS_FUZZER_TYPES,
    META_TASK_POLICY,
    META_TASK_TYPES,
    SIDE_EFFECT_META_TYPES,
    SKIP_SMOKE_GATE_TYPES,
    is_test_prefixed,
)


def test_policy_dict_is_populated():
    assert isinstance(META_TASK_POLICY, dict)
    assert len(META_TASK_POLICY) >= 12


def test_every_policy_entry_has_required_flags():
    required = {"bypass_fuzzer", "skip_structural_decomp"}
    optional = {"skip_smoke_gates", "skip_interface_fuzz", "stateful_fuzz"}
    allowed = required | optional
    for key, policy in META_TASK_POLICY.items():
        assert isinstance(key, str) and key
        assert required.issubset(policy.keys())
        assert set(policy.keys()).issubset(allowed)
        assert isinstance(policy["bypass_fuzzer"], bool)
        assert isinstance(policy["skip_structural_decomp"], bool)
        if "skip_smoke_gates" in policy:
            assert isinstance(policy["skip_smoke_gates"], bool)


def test_meta_task_types_matches_policy_keys():
    assert META_TASK_TYPES == frozenset(META_TASK_POLICY.keys())


def test_bypass_fuzzer_types_derives_from_policy():
    expected = frozenset(k for k, v in META_TASK_POLICY.items() if v["bypass_fuzzer"])
    assert BYPASS_FUZZER_TYPES == expected


def test_side_effect_meta_types_derives_from_policy():
    expected = frozenset(k for k, v in META_TASK_POLICY.items() if v["skip_structural_decomp"])
    assert SIDE_EFFECT_META_TYPES == expected


def test_bypass_and_side_effect_are_subsets_of_canonical():
    assert BYPASS_FUZZER_TYPES.issubset(META_TASK_TYPES)
    assert SIDE_EFFECT_META_TYPES.issubset(META_TASK_TYPES)
    assert SKIP_SMOKE_GATE_TYPES.issubset(META_TASK_TYPES)


def test_skip_smoke_gate_types_derives_from_policy():
    expected = frozenset(
        k for k, v in META_TASK_POLICY.items() if v.get("skip_smoke_gates", False)
    )
    assert SKIP_SMOKE_GATE_TYPES == expected


def test_skip_smoke_gate_is_subset_of_bypass():
    assert SKIP_SMOKE_GATE_TYPES.issubset(BYPASS_FUZZER_TYPES)


def test_harness_self_fix_skips_smoke_gates():
    assert "harness_self_fix" in SKIP_SMOKE_GATE_TYPES


def test_test_authoring_policy_entry():
    assert "test_authoring" in META_TASK_POLICY
    policy = META_TASK_POLICY["test_authoring"]
    assert policy["bypass_fuzzer"] is False
    assert "test_authoring" not in BYPASS_FUZZER_TYPES
    assert policy.get("skip_interface_fuzz") is True
    assert is_test_prefixed("test_authoring") is True


@pytest.mark.parametrize(
    "value",
    [
        "planner_tooling",
        "orchestration",
        "harness_plumbing",
        "sandbox_infra",
        "hooks_integration",
        "validation",
        "harness_self_fix",
    ],
)
def test_known_bypass_values_are_in_bypass_set(value):
    assert value in BYPASS_FUZZER_TYPES


@pytest.mark.parametrize(
    "value",
    [
        "sandbox_infra",
        "data_model",
        "harness_plumbing",
        "orchestration",
        "planner_tooling",
        "mcp_plumbing",
        "state_machine",
        "io_adapter",
        "harness_self_fix",
    ],
)
def test_known_side_effect_values_are_in_side_effect_set(value):
    assert value in SIDE_EFFECT_META_TYPES


