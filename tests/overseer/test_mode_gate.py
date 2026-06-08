"""RED oracle for overseer/mode_gate.py — mode enforcement (tool withholding).

Mirrors harness/mcp_server.build_execute_tool: a mode is the privilege CEILING,
enforced by WITHHOLDING tools/routes, not by prompt. Encodes the mode-switching
lattice (free among Tier-R, down anytime, R->W for default-available W, Tier-S
only when unlocked) and reverts to observe on ambiguity.
"""
import pytest

from overseer.modes import MODE_REGISTRY, get_mode
from overseer.mode_gate import (
    ModeViolation,
    assert_tool_allowed,
    assert_route_allowed,
    can_switch,
    resolve_tool_allowlist,
)

TIER_R = {"observe", "analyze", "audit"}


def test_mode_violation_is_an_exception():
    assert issubclass(ModeViolation, Exception)


def test_resolve_tool_allowlist_returns_the_modes_concrete_tools():
    for name, spec in MODE_REGISTRY.items():
        assert resolve_tool_allowlist(name) == list(spec.allowed_tools)


def test_assert_tool_allowed_passes_for_an_in_allowlist_tool():
    # Use each mode's own first declared tool — must not raise.
    for name, spec in MODE_REGISTRY.items():
        if spec.allowed_tools:
            assert_tool_allowed(name, list(spec.allowed_tools)[0])  # no raise


def test_assert_tool_allowed_denies_an_unknown_tool():
    with pytest.raises(ModeViolation):
        assert_tool_allowed("observe", "DefinitelyNotARealTool")


def test_read_only_modes_deny_write_and_bash():
    # The Tier-R security property: no mutation tools, enforced by withholding.
    for name in TIER_R:
        with pytest.raises(ModeViolation):
            assert_tool_allowed(name, "Write")
        with pytest.raises(ModeViolation):
            assert_tool_allowed(name, "Bash")


def test_observe_allows_the_get_state_read_route():
    # observe is the situation room over the WebUI GET surface.
    assert_route_allowed("observe", "GET", "/api/state")  # no raise


def test_read_only_modes_deny_mutating_routes():
    for name in TIER_R:
        with pytest.raises(ModeViolation):
            assert_route_allowed(name, "POST", "/api/chat/send")
        with pytest.raises(ModeViolation):
            assert_route_allowed(name, "PUT", "/api/config/control")


def test_can_switch_is_free_among_tier_r():
    assert can_switch("observe", "analyze", frozenset()) is True
    assert can_switch("audit", "observe", frozenset()) is True


def test_can_switch_allows_r_to_default_available_w():
    assert can_switch("observe", "dispatch", frozenset()) is True
    assert can_switch("observe", "brief-author", frozenset()) is True


def test_can_switch_allows_moving_down_the_lattice_anytime():
    # From a higher tier back down to a read mode (revert) is always allowed.
    assert can_switch("dispatch", "observe", frozenset()) is True
    assert can_switch("push", "observe", frozenset({"push"})) is True


def test_can_switch_blocks_tier_s_unless_unlocked():
    assert can_switch("observe", "push", frozenset()) is False
    assert can_switch("observe", "push", frozenset({"push"})) is True
    assert can_switch("analyze", "flag-steward", frozenset()) is False
    assert can_switch("analyze", "flag-steward", frozenset({"flag-steward"})) is True


def test_can_switch_to_unknown_target_is_false():
    assert can_switch("observe", "no-such-mode", frozenset()) is False


def test_can_always_revert_to_observe():
    for name in MODE_REGISTRY:
        assert can_switch(name, "observe", frozenset()) is True
