"""Committed contract oracle for harness/webui_config_schema.py.

Freezes the typed-schema + server-side validator contract:
  - typed coercion (int/float/bool) with per-field rejection on bad input,
  - DUAL-AGENT roles must select two DIFFERENT agents (reject if identical),
  - a role assigned an api-backed provider with an EMPTY key is locked
    ('provider locked: set <ENV> first'); a keyed provider is accepted and
    its provider id propagates into values[role.config_key],
  - atomic_save_config round-trips short->dotted nesting without clobbering
    unrelated config blocks,
  - bool rejects arbitrary truthy ints (isinstance precedence) and
    parallel_cap bounds are enforced,
  - the module is live-wired (check_wired).

Authored separately from the implementation: it must FAIL against a bare
`raise NotImplementedError` stub / declared mutant and PASS only on the real
implementation.
"""
import importlib
from pathlib import Path

import pytest
import yaml

mod = importlib.import_module("harness.webui_config_schema")


def _base_submitted():
    # A fully-valid submission used as the happy-path baseline; individual tests
    # mutate one field to drive a specific rejection.
    return {
        "parallel_cap": "5",
        "min_ram_mb": "2048",
        "cooldown_tier_1": "300",
        "cooldown_tier_2": "3600",
        "cooldown_tier_3": "86400",
        "antigravity_mode": "false",
        "synthesis.active_agents": ["claude", "gemini"],
        "overseer.default_backend": "claude",
        "control.autobrief_default_agent": "claude",
    }


def test_oracle_typed_coercion_per_field_rejection():
    # Positive control: valid submission coerces by dtype and returns values.
    out = mod.validate_config(_base_submitted(), secrets={})
    v = out.values
    assert v["parallel_cap"] == 5 and isinstance(v["parallel_cap"], int)
    assert v["cooldown_tier_1"] == 300.0 and isinstance(v["cooldown_tier_1"], float)
    assert v["antigravity_mode"] is False
    # Negative control: a non-coercible int lands in field_errors and raises.
    sub = _base_submitted()
    sub["parallel_cap"] = "not-a-number"
    with pytest.raises(mod.ConfigValidationError) as ei:
        mod.validate_config(sub, secrets={})
    assert "parallel_cap" in ei.value.field_errors


def test_oracle_dual_distinct_and_provider_lock_rules():
    # Dual synthesis role with two identical agents is rejected.
    sub = _base_submitted()
    sub["synthesis.active_agents"] = ["claude", "claude"]
    with pytest.raises(mod.ConfigValidationError) as ei:
        mod.validate_config(sub, secrets={})
    assert "synthesis.active_agents" in ei.value.field_errors
    # Role assigned a keyless api-backed provider is provider-locked.
    sub = _base_submitted()
    sub["overseer.default_backend"] = "deepseek"
    env = mod.PROVIDERS["deepseek"].api_key_env
    with pytest.raises(mod.ConfigValidationError) as ei:
        mod.validate_config(sub, secrets={})
    assert "overseer.default_backend" in ei.value.field_errors
    assert ei.value.field_errors["overseer.default_backend"] == (
        f"provider locked: set {env} first"
    )


def test_oracle_atomic_save_short_to_dotted_preserves_blocks(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump({
        "autowork": {"parallel_cap": 1, "poll_interval_sec": 5},
        "overseer": {"enabled": True},
    }), encoding="utf-8")
    validated = mod.validate_config(_base_submitted(), secrets={})
    mod.atomic_save_config(validated, cfg)
    loaded = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    # short 'parallel_cap' nests under the dotted 'autowork.parallel_cap'.
    assert loaded["autowork"]["parallel_cap"] == 5
    # unrelated keys/blocks preserved.
    assert loaded["autowork"]["poll_interval_sec"] == 5
    assert loaded["overseer"]["enabled"] is True


def test_oracle_edge_cases_and_check_wired_assertion():
    # bool rejects arbitrary truthy ints (isinstance precedence): 7 != True.
    sub = _base_submitted()
    sub["antigravity_mode"] = 7
    with pytest.raises(mod.ConfigValidationError) as ei:
        mod.validate_config(sub, secrets={})
    assert "antigravity_mode" in ei.value.field_errors
    # parallel_cap out-of-bounds is rejected.
    sub = _base_submitted()
    sub["parallel_cap"] = "17"
    with pytest.raises(mod.ConfigValidationError) as ei:
        mod.validate_config(sub, secrets={})
    assert "parallel_cap" in ei.value.field_errors
    # live-wiring anchor: the harness/** module must be reachable from LIVE_ROOT.
    from harness.wire_up import check_wired
    assert check_wired(Path('.'), 'harness/webui_config_schema.py').wired is True


def test_oracle_property_parallel_cap_bounds():
    # In-range caps (min=1..max=16) accept and coerce; out-of-range reject.
    for cap in (1, 8, 16):
        sub = _base_submitted()
        sub["parallel_cap"] = str(cap)
        out = mod.validate_config(sub, secrets={})
        assert out.values["parallel_cap"] == cap
    for cap in (0, 17):
        sub = _base_submitted()
        sub["parallel_cap"] = str(cap)
        with pytest.raises(mod.ConfigValidationError) as ei:
            mod.validate_config(sub, secrets={})
        assert "parallel_cap" in ei.value.field_errors


def test_oracle_regression_bool_rejects_truthy_ints():
    # Regression: a truthy int must NOT coerce to True; it lands in field_errors.
    for truthy in (1, 7):
        sub = _base_submitted()
        sub["antigravity_mode"] = truthy
        with pytest.raises(mod.ConfigValidationError) as ei:
            mod.validate_config(sub, secrets={})
        assert "antigravity_mode" in ei.value.field_errors


def test_oracle_regression_role_value_propagation_roundtrip():
    # A keyed api-backed provider is accepted and its id round-trips into values.
    sub = _base_submitted()
    sub["overseer.default_backend"] = "deepseek"
    env = mod.PROVIDERS["deepseek"].api_key_env
    out = mod.validate_config(sub, secrets={env: "sk-real-key"})
    assert out.values["overseer.default_backend"] == "deepseek"
