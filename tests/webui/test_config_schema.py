"""RED-first oracle for harness/webui_config_schema.py (leaf: webui-config-schema).

Constrains the typed schema + server-side validator:
  - typed coercion (int/float/bool/path) with per-field rejection on bad input
  - DUAL-AGENT roles must have two DIFFERENT chosen agents (reject if same)
  - a role assigned to an api-backed provider with an EMPTY key is rejected
    (provider-locked-unless-keyed); a keyed provider is accepted
  - atomic_save_config round-trips and does not clobber unrelated config blocks

This test is authored separately from the implementation; it must FAIL against a
bare `raise NotImplementedError` stub and PASS only on a real implementation.
"""
import importlib

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


def test_schema_surface_exists():
    for sym in ("CONFIG_FIELDS", "ROLES", "PROVIDERS", "validate_config",
                "atomic_save_config", "ConfigValidationError", "ValidatedConfig"):
        assert hasattr(mod, sym), f"missing public symbol {sym}"
    # every field carries a recognised dtype
    valid = {"int", "float", "str", "bool", "path-file", "path-dir", "enum"}
    assert mod.CONFIG_FIELDS, "CONFIG_FIELDS must be non-empty"
    for f in mod.CONFIG_FIELDS:
        assert f.dtype in valid, f"field {f.name!r} has bad dtype {f.dtype!r}"


def test_dual_agent_role_is_declared():
    dual = [r for r in mod.ROLES if getattr(r, "dual", False)]
    assert dual, "at least one DUAL-AGENT role must be declared"
    assert any(r.config_key == "synthesis.active_agents" for r in dual), \
        "synthesis.active_agents must be the dual-agent role"


def test_api_backed_providers_have_env_vars():
    # The 5 Chinese providers + OpenAI/Gemini/Anthropic must be registered, api-backed,
    # each with a non-empty api_key_env.
    required = {"openai", "anthropic", "deepseek", "moonshot", "zhipu", "qwen", "minimax"}
    ids = set(mod.PROVIDERS.keys())
    assert required <= ids, f"missing providers: {required - ids}"
    for pid in required:
        spec = mod.PROVIDERS[pid]
        assert spec.api_backed is True
        assert spec.api_key_env, f"{pid} has no api_key_env"
    # CLI agents are NOT api-backed (no key required to select them).
    for cli in ("claude", "gemini", "codex"):
        assert cli in mod.PROVIDERS and mod.PROVIDERS[cli].api_backed is False


def test_valid_submission_accepts_and_coerces_types():
    out = mod.validate_config(_base_submitted(), secrets={})
    v = out.values
    assert v["parallel_cap"] == 5 and isinstance(v["parallel_cap"], int)
    assert v["cooldown_tier_1"] == 300.0 and isinstance(v["cooldown_tier_1"], float)
    assert v["antigravity_mode"] is False


def test_non_coercible_int_is_rejected_per_field():
    sub = _base_submitted()
    sub["parallel_cap"] = "not-a-number"
    with pytest.raises(mod.ConfigValidationError) as ei:
        mod.validate_config(sub, secrets={})
    assert "parallel_cap" in ei.value.field_errors


def test_out_of_bounds_int_is_rejected():
    sub = _base_submitted()
    sub["parallel_cap"] = "999"  # max is 16
    with pytest.raises(mod.ConfigValidationError) as ei:
        mod.validate_config(sub, secrets={})
    assert "parallel_cap" in ei.value.field_errors


def test_dual_agent_same_agent_is_rejected():
    sub = _base_submitted()
    sub["synthesis.active_agents"] = ["claude", "claude"]
    with pytest.raises(mod.ConfigValidationError) as ei:
        mod.validate_config(sub, secrets={})
    assert "synthesis.active_agents" in ei.value.field_errors


def test_role_assigned_keyless_api_provider_is_rejected():
    sub = _base_submitted()
    sub["overseer.default_backend"] = "deepseek"  # api-backed
    with pytest.raises(mod.ConfigValidationError) as ei:
        mod.validate_config(sub, secrets={})  # no DEEPSEEK_API_KEY
    assert "overseer.default_backend" in ei.value.field_errors


def test_role_assigned_keyed_api_provider_is_accepted():
    sub = _base_submitted()
    sub["overseer.default_backend"] = "deepseek"
    env = mod.PROVIDERS["deepseek"].api_key_env
    out = mod.validate_config(sub, secrets={env: "sk-real-key"})
    assert out.values["overseer.default_backend"] == "deepseek"


def test_atomic_save_roundtrips_without_clobbering(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump({
        "autowork": {"parallel_cap": 1, "poll_interval_sec": 5},
        "overseer": {"enabled": True},
    }), encoding="utf-8")
    validated = mod.validate_config(_base_submitted(), secrets={})
    mod.atomic_save_config(validated, cfg)
    loaded = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert loaded["autowork"]["parallel_cap"] == 5
    # unrelated keys/blocks preserved
    assert loaded["autowork"]["poll_interval_sec"] == 5
    assert loaded["overseer"]["enabled"] is True
