"""MD_POLICY behavioral oracle (REV25 §3 / MD-POLICY = M-D5).

Asserts the live META_TASK_POLICY routes `state_machine` tasks through the
stateful fuzz path rather than bypassing the fuzzer.

RED on HEAD because today `state_machine` has `bypass_fuzzer: True` and no
`stateful_fuzz` key; GREEN after the policy is flipped to
`bypass_fuzzer: False` + `stateful_fuzz: True`.

`banned_constructs` is INERT (read by zero harness code) and is deliberately
NOT asserted here.
"""
from harness.planner import taxonomies as t


def test_state_machine_routed_to_stateful_not_bypass():
    pol = t.META_TASK_POLICY["state_machine"]
    assert pol["bypass_fuzzer"] is False, (
        "state_machine must NOT bypass the fuzzer once Method D is wired"
    )
    assert pol.get("stateful_fuzz") is True, (
        "state_machine must carry stateful_fuzz: True so MD_ROUTING can fire"
    )


def test_state_machine_dropped_from_bypass_set():
    # BYPASS_FUZZER_TYPES is derived from the policy; the flip must remove it.
    assert "state_machine" not in t.BYPASS_FUZZER_TYPES


def test_other_policies_untouched():
    # spot-check a couple of unrelated entries stay as-is
    assert t.META_TASK_POLICY["cli_tooling"]["bypass_fuzzer"] is False
    assert t.META_TASK_POLICY["sandbox_infra"]["bypass_fuzzer"] is True
