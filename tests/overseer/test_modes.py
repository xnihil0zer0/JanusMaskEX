"""RED oracle for overseer/modes.py — the mode registry.

Pins the public surface the blind worker must reproduce EXACTLY (this oracle is
authoritative per the brief). The registry is pure DATA: a frozen ``ModeSpec``
per mode + the lookup/availability helpers. The 14 modes and their tier/unlock
posture are the security spine of the overseer — every Tier-S mode must be
unlock-only and never auto-available, every Tier-R mode must be auto-granted.
"""
import dataclasses

import pytest

from overseer.modes import (
    ModeSpec,
    MODE_REGISTRY,
    get_mode,
    list_available_modes,
    requires_unlock,
)

# The full mode set, grouped by tier (the brief's "The 14 modes").
TIER_R = {"observe", "analyze", "audit"}
TIER_W = {
    "brief-author",
    "oracle-author",
    "dispatch",
    "triage",
    "daemon-supervisor",
    "ui-tester",
}
TIER_S = {
    "flag-steward",
    "harness-self-fix",
    "security-review",
    "rebuild-factory",
    "push",
}
ALL_MODES = TIER_R | TIER_W | TIER_S

VALID_JM_MODES = {"synthesis", "planning", "reconciliation", "none"}
VALID_TIERS = {"R", "W", "S"}


def test_registry_has_exactly_the_14_modes():
    assert set(MODE_REGISTRY) == ALL_MODES
    assert len(MODE_REGISTRY) == 14


def test_modespec_is_a_dataclass_with_the_pinned_fields():
    fields = {f.name for f in dataclasses.fields(ModeSpec)}
    required = {
        "name",
        "tier",
        "janusmask_mode",
        "allowed_tools",
        "allowed_routes",
        "allowed_meta_task_types",
        "inbox_contract",
        "outbox_contract",
        "apply_authority",
        "default_available",
        "requires_unlock",
        "fallback_mode",
    }
    assert required <= fields


@pytest.mark.parametrize("name", sorted(ALL_MODES))
def test_every_mode_is_well_formed(name):
    spec = MODE_REGISTRY[name]
    assert isinstance(spec, ModeSpec)
    assert spec.name == name
    assert spec.tier in VALID_TIERS
    assert spec.janusmask_mode in VALID_JM_MODES
    # collections are concrete, iterable, and string-typed
    for coll in (spec.allowed_tools, spec.allowed_routes, spec.allowed_meta_task_types):
        assert all(isinstance(x, str) for x in coll)
    assert isinstance(spec.default_available, bool)
    assert isinstance(spec.requires_unlock, bool)
    # fallback must itself be a real mode (revert target on ambiguity/expiry)
    assert spec.fallback_mode in MODE_REGISTRY


@pytest.mark.parametrize("name", sorted(ALL_MODES))
def test_tier_assignment_matches_the_spec(name):
    expected_tier = "R" if name in TIER_R else "W" if name in TIER_W else "S"
    assert MODE_REGISTRY[name].tier == expected_tier


def test_tier_r_modes_are_auto_granted_never_unlock():
    for name in TIER_R:
        spec = MODE_REGISTRY[name]
        assert spec.default_available is True
        assert spec.requires_unlock is False


def test_tier_s_modes_are_unlock_only_never_auto_available():
    # The cardinal safety invariant: a security-gated mode can never be
    # self-selected or auto-available.
    for name in TIER_S:
        spec = MODE_REGISTRY[name]
        assert spec.requires_unlock is True
        assert spec.default_available is False


def test_observe_is_the_default_boot_and_fallback_mode():
    observe = MODE_REGISTRY["observe"]
    assert observe.tier == "R"
    assert observe.janusmask_mode == "none"  # read-only, no inbox staging
    assert observe.default_available is True
    assert observe.requires_unlock is False
    # On ambiguity/error/expired-unlock every mode reverts to observe.
    for spec in MODE_REGISTRY.values():
        assert spec.fallback_mode == "observe"


def test_get_mode_returns_spec_and_rejects_unknown():
    assert get_mode("observe") is MODE_REGISTRY["observe"]
    with pytest.raises(KeyError):
        get_mode("no-such-mode")


def test_requires_unlock_helper_tracks_the_tier_s_set():
    for name in TIER_S:
        assert requires_unlock(name) is True
    for name in TIER_R | TIER_W:
        assert requires_unlock(name) is False


def test_list_available_modes_excludes_locked_tier_s_until_unlocked():
    # With nothing unlocked: every default-available mode, and NO Tier-S mode.
    available = set(list_available_modes(frozenset()))
    assert TIER_R <= available
    assert available.isdisjoint(TIER_S)
    assert all(MODE_REGISTRY[m].default_available for m in available)

    # Unlocking a Tier-S mode surfaces exactly that one.
    with_push = set(list_available_modes(frozenset({"push"})))
    assert "push" in with_push
    assert with_push.isdisjoint(TIER_S - {"push"})


def test_brief_author_authors_only_does_not_dispatch():
    # brief-author is Tier-W, default-available, and its authority is authoring
    # brief/plan files — NOT dispatching them.
    spec = MODE_REGISTRY["brief-author"]
    assert spec.tier == "W"
    assert spec.default_available is True
    assert spec.requires_unlock is False
