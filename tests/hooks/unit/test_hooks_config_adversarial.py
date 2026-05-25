"""Adversarial battery for HOOK-13-config-flag.

Mutation-style tests pinning the hooks config contract so that accidental
rollbacks, unvetted mode flips, or silent unknown-key regressions cause
at least one of these tests to fail.

Coverage axes (hooks-implementation-plan.md §Phase 1 + sub-plan-06 §5):
    1. Safe default — mode must be "off" at rest and on missing block.
    2. Enforce-mode can only be requested if the full verb spelling list is
       respected (no typo-induced silent bypass).
    3. Committed YAML must not request enforce yet (Phase 5 gate);
       pre-enforce shadow is acceptable per HOOK-50.
    4. Loader is strict about unknown keys to prevent feature-flag drift.
    5. Shadow-dir default points under state/hooks/shadow/ per sub-plan 05.
"""

from __future__ import annotations

import pathlib

import pytest

from harness.config_loader import (
    ConfigError,
    HooksConfig,
    HOOKS_ALLOWED_VERBS,
    HOOKS_VALID_MODES,
    HOOKS_DEFAULT_SHADOW_DIR,
    get_hooks_config,
)


REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


class TestDefaultStaysOff:
    def test_default_mode_is_off(self):
        assert HooksConfig().mode == "off"

    def test_missing_block_is_off(self):
        assert get_hooks_config({}).mode == "off"

    def test_empty_block_is_off(self):
        assert get_hooks_config({"hooks": {}}).mode == "off"


class TestModeBoundaries:
    @pytest.mark.parametrize("bad", [
        "", "ENFORCE", "Off", "shadow_mode", "on", None, True, 1,
    ])
    def test_rejects_bad_mode_value(self, bad):
        with pytest.raises(ConfigError):
            get_hooks_config({"hooks": {"mode": bad}})

    def test_valid_modes_constant_is_minimal(self):
        # Only these three modes are allowed anywhere in the migration plan.
        assert HOOKS_VALID_MODES == frozenset({"off", "shadow", "enforce"})


class TestEnforceVerbSpellingGuard:
    @pytest.mark.parametrize("typo", [
        "submitcode",
        "submit-code",
        "submitCode",
        "submit_plan",                       # missing _draft
        "request_clarification ",            # trailing space
        "submit_reconciliation",             # missing _response
    ])
    def test_typo_is_rejected(self, typo):
        with pytest.raises(ConfigError) as exc:
            get_hooks_config({"hooks": {
                "mode": "shadow",
                "enforce_verbs": [typo],
            }})
        assert typo in str(exc.value) or "not a recognised verb" in str(exc.value)

    def test_allowed_verbs_exact_set(self):
        assert HOOKS_ALLOWED_VERBS == frozenset({
            "submit_code",
            "submit_plan_draft",
            "submit_reconciliation_response",
            "request_clarification",
            "report_error",
        })


class TestCommittedYamlSafety:
    """The on-disk config must not silently promote mode to enforce.

    Pre-enforce invariant (HOOK-50 / B2 v2 Step 1): shadow is the current
    committed mode while the shadow drain baseline is being captured.
    Flipping to 'enforce' without a P5 phase_gate_pass is a rollback risk,
    so this test accepts {'off', 'shadow'} but rejects anything else.
    """

    def test_committed_mode_is_pre_enforce(self):
        text = (REPO_ROOT / "harness" / "config.yaml").read_text(encoding="utf-8")
        # Look at the hooks: block only.
        in_hooks = False
        mode_value = None
        for line in text.splitlines():
            if line.rstrip().startswith("hooks:"):
                in_hooks = True
                continue
            if in_hooks:
                if line and not line.startswith((" ", "\t")):
                    break
                stripped = line.strip()
                if stripped.startswith("mode:"):
                    raw = stripped.split(":", 1)[1]
                    if "#" in raw:
                        raw = raw.split("#", 1)[0]
                    mode_value = raw.strip().strip('"').strip("'").lower()
                    break
        assert mode_value in ("off", "shadow"), (
            f"hooks.mode in config.yaml is {mode_value!r}, must be 'off' or 'shadow' "
            f"until the P5 enforce gate opens"
        )

    def test_committed_enforce_verbs_is_empty(self):
        text = (REPO_ROOT / "harness" / "config.yaml").read_text(encoding="utf-8")
        in_hooks = False
        found_empty = False
        for line in text.splitlines():
            if line.rstrip().startswith("hooks:"):
                in_hooks = True
                continue
            if in_hooks:
                if line and not line.startswith((" ", "\t")):
                    break
                stripped = line.strip()
                if stripped.startswith("enforce_verbs:"):
                    raw = stripped.split(":", 1)[1]
                    if "#" in raw:
                        raw = raw.split("#", 1)[0]
                    raw = raw.strip()
                    # Accept "[]", "[ ]" or an indented block that is a no-op.
                    found_empty = raw in ("[]", "[ ]", "")
                    break
        assert found_empty, (
            "enforce_verbs must be [] in the committed config until the P5 "
            "equivalence gate opens"
        )


class TestUnknownKeyDrift:
    def test_unknown_top_level_key_flags(self):
        with pytest.raises(ConfigError):
            get_hooks_config({"hooks": {"experimental_flag": True, "mode": "off"}})

    def test_non_dict_hooks_block_rejected(self):
        for bad in ("off", 42, ["off"]):
            with pytest.raises(ConfigError):
                get_hooks_config({"hooks": bad})


class TestShadowDir:
    def test_default_points_into_state_hooks_shadow(self):
        assert HOOKS_DEFAULT_SHADOW_DIR.startswith("state/hooks/")

    def test_override_is_respected(self):
        h = get_hooks_config({"hooks": {"shadow_dir": "alt/"}})
        assert h.shadow_dir == "alt/"


class TestEnforceVerbsList:
    def test_empty_list_is_fine_even_in_shadow(self):
        h = get_hooks_config({"hooks": {"mode": "shadow", "enforce_verbs": []}})
        assert h.enforce_verbs == []

    def test_mixed_type_list_rejected(self):
        with pytest.raises(ConfigError):
            get_hooks_config({"hooks": {"enforce_verbs": ["submit_code", 3]}})
