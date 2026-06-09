"""RED oracle — authoritative contract for autocompiler/flags.py (leaf ac-flags).

Contract: ``ac_enabled(key, state_dir=None, config=None) -> bool`` is the single
fail-closed flag reader for the ``autocompiler:`` config subtree (clone of the
``_wire_up_gate_enabled`` idiom). When ``config`` is None it loads via the
module-level name ``load_config`` (imported from harness.config_loader so tests
can inject failures). It returns True ONLY when ``config['autocompiler']['enabled']``
is truthy AND the (possibly dotted) ``key`` resolves truthy under the
``autocompiler:`` subtree. ANY error, missing key, or missing subtree => False.
It must never raise.
"""
import pytest

from autocompiler.flags import ac_enabled


def test_no_subtree_is_false():
    assert ac_enabled('population', config={}) is False


def test_master_off_gates_everything():
    cfg = {'autocompiler': {'enabled': False, 'population': True}}
    assert ac_enabled('population', config=cfg) is False


def test_enabled_key_true():
    cfg = {'autocompiler': {'enabled': True, 'population': True}}
    assert ac_enabled('population', config=cfg) is True


def test_missing_key_is_false():
    cfg = {'autocompiler': {'enabled': True}}
    assert ac_enabled('population', config=cfg) is False


def test_dotted_key_resolves_nested():
    cfg = {'autocompiler': {'enabled': True, 'population': {'evolve': True, 'js': False}}}
    assert ac_enabled('population.evolve', config=cfg) is True
    assert ac_enabled('population.js', config=cfg) is False
    assert ac_enabled('population.missing', config=cfg) is False


def test_loader_error_fail_closed(monkeypatch):
    import autocompiler.flags as flags_mod

    def _boom(*a, **k):
        raise RuntimeError('config unreadable')
    monkeypatch.setattr(flags_mod, 'load_config', _boom)
    assert ac_enabled('population') is False


def test_garbage_inputs_never_raise():
    assert ac_enabled(12345, config={'autocompiler': {'enabled': True}}) is False
    assert ac_enabled('', config={'autocompiler': {'enabled': True}}) is False
    assert ac_enabled('x', config='not-a-dict') is False
    assert ac_enabled(None, config=None) in (True, False)
