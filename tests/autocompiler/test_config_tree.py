"""Oracle — authoritative contract for the autocompiler flag subtree.

Contract (updated 2026-06-10, owner-enabled default-ON): the ``autocompiler:``
subtree exists with the master gate ``enabled`` plus the four capability
sub-keys (``population``, ``determinism``, ``decode``, ``js``), and they are all
the YAML boolean ``true`` — so the layer is LIVE. Two sources of truth must
agree: the documented subtree in ``harness/config.yaml`` (asserted here via
``orchestrator.load_config``) and the RUNTIME gate at
``config/autocompiler.yaml`` (the file ``autocompiler.flags.ac_enabled``
actually reads, asserted here against the real flag reader). The subtree must
not have clobbered any pre-existing top-level section (autowork/
hierarchical_planning/synthesis spot-pinned, including ``autowork.wire_up_gate:
true``).
"""
import pytest

from harness.orchestrator import load_config


def _cfg():
    cfg = load_config()
    assert isinstance(cfg, dict)
    return cfg


def test_autocompiler_subtree_exists_default_on():
    sub = _cfg().get('autocompiler')
    assert isinstance(sub, dict), 'autocompiler: subtree missing from harness/config.yaml'
    assert sub.get('enabled') is True


def test_capability_subkeys_present_and_on():
    sub = _cfg().get('autocompiler') or {}
    for key in ('population', 'determinism', 'decode', 'js'):
        assert key in sub, f'autocompiler.{key} missing'
        assert sub[key] is True, f'autocompiler.{key} must default to true (owner-enabled)'


def test_documented_subtree_activates_ac_enabled():
    # The harness/config.yaml subtree, when fed to ac_enabled, activates.
    from autocompiler.flags import ac_enabled
    cfg = _cfg()
    for key in ('population', 'determinism', 'decode', 'js'):
        assert ac_enabled(key, config=cfg) is True


def test_runtime_gate_file_is_live():
    # The file ac_enabled ACTUALLY reads (config/autocompiler.yaml, resolved via
    # the real loader from the repo cwd) must enable every capability — this is
    # the gate the live worker/fuzzer hooks consult, not harness/config.yaml.
    import os
    from autocompiler.flags import ac_enabled
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for key in ('population', 'determinism', 'decode', 'js'):
        assert ac_enabled(key, state_dir=repo_root) is True, (
            f'config/autocompiler.yaml runtime gate does not enable {key}'
        )


def test_fail_closed_idiom_intact():
    # The gate is still fail-closed: master gate off, or a missing/non-bool key,
    # resolves to False even though the live config is on.
    from autocompiler.flags import ac_enabled
    assert ac_enabled('population', config={'autocompiler': {'enabled': False, 'population': True}}) is False
    assert ac_enabled('nope', config={'autocompiler': {'enabled': True}}) is False


def test_existing_sections_survive():
    # A clobbered whole-file rewrite would drop live sections.
    cfg = _cfg()
    for section in ('autowork', 'hierarchical_planning', 'synthesis'):
        assert isinstance(cfg.get(section), dict), f'{section}: section lost'
    assert cfg['autowork'].get('wire_up_gate') is True
    assert cfg['hierarchical_planning'].get('enabled') is True
