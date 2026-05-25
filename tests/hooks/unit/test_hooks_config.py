"""Unit tests for the hooks config flag (HOOK-13-config-flag).

Pins the typed reader added to harness.config_loader:

    get_hooks_config(cfg: dict) -> HooksConfig

Backed by the new ``hooks:`` block in harness/config.yaml:

    hooks:
      mode: off              # off | shadow | enforce
      enforce_verbs: []      # subset of ALLOWED_VERBS
      shadow_dir: state/hooks/shadow/

See hooks-implementation-plan.md §Phase 1 item 4 and
hooks-implementation-sub-plan-02.md §3.2.
"""

from __future__ import annotations

import pathlib

import pytest

import harness.config_loader as config_loader
from harness.config_loader import (
    ConfigError,
    HooksConfig,
    HOOKS_ALLOWED_VERBS,
    HOOKS_VALID_MODES,
    get_hooks_config,
)


class TestDefaults:
    def test_missing_hooks_block_returns_off_defaults(self):
        h = get_hooks_config({})
        assert isinstance(h, HooksConfig)
        assert h.mode == "off"
        assert h.enforce_verbs == []
        assert h.shadow_dir == "state/hooks/shadow/"

    def test_hooks_is_none_returns_defaults(self):
        h = get_hooks_config({"hooks": None})
        assert h.mode == "off"
        assert h.enforce_verbs == []

    def test_empty_dict_returns_defaults(self):
        h = get_hooks_config({"hooks": {}})
        assert h.mode == "off"


class TestModeValidation:
    def test_valid_modes(self):
        for m in ("off", "shadow", "enforce"):
            h = get_hooks_config({"hooks": {"mode": m, "enforce_verbs": []}})
            assert h.mode == m

    def test_invalid_mode_raises(self):
        with pytest.raises(ConfigError) as exc:
            get_hooks_config({"hooks": {"mode": "ENABLED"}})
        assert "mode" in str(exc.value)

    def test_mode_must_be_string(self):
        with pytest.raises(ConfigError):
            get_hooks_config({"hooks": {"mode": 1}})

    def test_valid_modes_constant_shape(self):
        assert HOOKS_VALID_MODES == frozenset({"off", "shadow", "enforce"})


class TestEnforceVerbs:
    def test_allowed_verbs_set_matches_sub_plan(self):
        assert HOOKS_ALLOWED_VERBS == frozenset({
            "submit_code",
            "submit_plan_draft",
            "submit_reconciliation_response",
            "request_clarification",
            "report_error",
        })

    def test_accepts_subset(self):
        h = get_hooks_config({"hooks": {
            "mode": "shadow",
            "enforce_verbs": ["submit_code", "report_error"],
        }})
        assert h.enforce_verbs == ["submit_code", "report_error"]

    def test_rejects_unknown_verb(self):
        with pytest.raises(ConfigError) as exc:
            get_hooks_config({"hooks": {
                "mode": "shadow",
                "enforce_verbs": ["submit_code", "bogus_verb"],
            }})
        assert "bogus_verb" in str(exc.value)

    def test_enforce_verbs_must_be_list(self):
        with pytest.raises(ConfigError):
            get_hooks_config({"hooks": {"enforce_verbs": "submit_code"}})

    def test_enforce_verbs_entries_must_be_strings(self):
        with pytest.raises(ConfigError):
            get_hooks_config({"hooks": {"enforce_verbs": [1, 2]}})


class TestShadowDir:
    def test_accepts_string_path(self):
        h = get_hooks_config({"hooks": {"shadow_dir": "state/alt/"}})
        assert h.shadow_dir == "state/alt/"

    def test_shadow_dir_type_checked(self):
        with pytest.raises(ConfigError):
            get_hooks_config({"hooks": {"shadow_dir": 42}})


class TestUnknownKeys:
    def test_unknown_key_rejected(self):
        with pytest.raises(ConfigError) as exc:
            get_hooks_config({"hooks": {"unknown": 1}})
        assert "unknown" in str(exc.value).lower()

    def test_hooks_block_must_be_dict(self):
        with pytest.raises(ConfigError):
            get_hooks_config({"hooks": ["a", "b"]})


class TestYamlFileShape:
    """The committed harness/config.yaml must ship the new hooks: block,
    so the orchestrator can start reading the flag without any extra guards."""

    def test_config_yaml_has_hooks_block(self):
        # Load without depending on PyYAML — simple substring sanity check is
        # enough for this gate.
        path = pathlib.Path(__file__).resolve().parents[3] / "harness" / "config.yaml"
        text = path.read_text(encoding="utf-8")
        assert "\nhooks:" in text or text.startswith("hooks:")
        assert "mode:" in text
        assert "enforce_verbs" in text
        assert "shadow_dir" in text

    def test_config_yaml_mode_is_shadow_during_p5(self):
        """HOOK-50 flipped mode off -> shadow. The invariant now is that
        mode stays in the set {shadow} during the P5 shadow stage; HOOK-53
        (canary enforce) will widen this to also accept 'enforce' once
        the first verb canary passes its human gate."""
        path = pathlib.Path(__file__).resolve().parents[3] / "harness" / "config.yaml"
        text = path.read_text(encoding="utf-8")
        # Find the hooks: block and inspect mode line.
        lines = text.splitlines()
        in_hooks = False
        value = None
        for line in lines:
            if line.rstrip().startswith("hooks:"):
                in_hooks = True
                continue
            if in_hooks:
                if line and not line.startswith(" ") and not line.startswith("\t"):
                    break
                stripped = line.strip()
                if stripped.startswith("mode:"):
                    raw = stripped.split(":", 1)[1]
                    if "#" in raw:
                        raw = raw.split("#", 1)[0]
                    value = raw.strip().strip('"').strip("'").lower()
                    break
        assert value in {"shadow"}, (
            f"hooks.mode must be 'shadow' during P5 shadow stage "
            f"(HOOK-50 flip, pre HOOK-53); got {value!r}"
        )
