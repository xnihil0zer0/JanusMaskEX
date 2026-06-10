"""RED oracle — authoritative contract for the ac-config-tree leaf (harness/config.yaml).

Contract: an ADDITIVE, default-OFF ``autocompiler:`` subtree lands in
``harness/config.yaml``. Master gate ``enabled`` plus the four capability
sub-keys (``population``, ``determinism``, ``decode``, ``js``) all exist and
are the YAML boolean ``false`` — so ``ac_enabled`` remains fail-closed False
everywhere and the Phase-A/B modules stay inert until each key is flipped
deliberately. The edit must be PURELY additive: every pre-existing top-level
section survives byte-meaningfully (autowork/hierarchical_planning/synthesis
spot-pinned, including the live ``autowork.wire_up_gate: true``).
"""
import pytest

from harness.orchestrator import load_config


def _cfg():
    cfg = load_config()
    assert isinstance(cfg, dict)
    return cfg


def test_autocompiler_subtree_exists_default_off():
    sub = _cfg().get('autocompiler')
    assert isinstance(sub, dict), 'autocompiler: subtree missing from harness/config.yaml'
    assert sub.get('enabled') is False


def test_capability_subkeys_present_and_off():
    sub = _cfg().get('autocompiler') or {}
    for key in ('population', 'determinism', 'decode', 'js'):
        assert key in sub, f'autocompiler.{key} missing'
        assert sub[key] is False, f'autocompiler.{key} must default to false'


def test_ac_enabled_still_fail_closed_with_real_config():
    # Regression: the subtree existing must NOT activate anything.
    from autocompiler.flags import ac_enabled
    cfg = _cfg()
    for key in ('population', 'determinism', 'decode', 'js'):
        assert ac_enabled(key, config=cfg) is False


def test_edit_was_additive_existing_sections_survive():
    # Edge case: a clobbered whole-file rewrite would drop live sections.
    cfg = _cfg()
    for section in ('autowork', 'hierarchical_planning', 'synthesis'):
        assert isinstance(cfg.get(section), dict), f'{section}: section lost'
    assert cfg['autowork'].get('wire_up_gate') is True
    assert cfg['hierarchical_planning'].get('enabled') is True
