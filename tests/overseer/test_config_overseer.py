"""RED oracle for the harness/config.yaml EDIT leaf (harness_self_fix + decision file).

Adds a default-OFF overseer: block. Asserts the REAL config (as loaded by the
real consumer harness.orchestrator.load_config) exposes the block with the
fail-safe defaults the brief requires.
"""
from harness.orchestrator import load_config


def test_overseer_block_exists_and_is_default_off():
    cfg = load_config()
    assert "overseer" in cfg, "config.yaml has no overseer: block"
    ov = cfg["overseer"]
    # Ships OFF — no enabled-by-default autonomy.
    assert ov["enabled"] is False


def test_overseer_defaults_are_fail_safe():
    ov = load_config()["overseer"]
    assert ov["default_mode"] == "observe"      # boot in the read-only mode
    assert ov["default_backend"] == "claude"
    assert ov["models"]["claude"] == ["opus", "sonnet", "haiku"]
    assert "store_path" in ov
    assert "unlock_policy" in ov                # which Tier-S modes need unlock


def test_overseer_block_does_not_disturb_existing_blocks():
    cfg = load_config()
    # Sanity: the edit is additive — core blocks remain intact.
    assert "autowork" in cfg
    assert "synthesis" in cfg
