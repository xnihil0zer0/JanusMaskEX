"""RED behavioural oracle for the jailed detonation runner.

Pins the ground-truth result table of the NEW top-level runner

    detonate_oracle(oracle_source: str, symbols, live_root_files, *,
                    repo_root, jailed: bool = True) -> dict[str, bool]

in ``harness/wire_up.py``. It drives the REAL ``detonate_oracle`` over real
child processes (jailed by default) -- the runner is never mocked or stubbed,
and the live-root list is imported (``LIVE_ROOTS``) rather than hardcoded.

RED hinge: on HEAD ``detonate_oracle`` does not yet exist, so the top-level
``from harness.wire_up import detonate_oracle, ...`` raises ImportError and the
whole file fails to collect. It turns GREEN once TASK 2 lands the primitive.

Non-goals: this is a standalone UNIT oracle of the ``detonate_oracle`` callable;
it is explicitly NOT an integration / end-to-end factory-or-gate exercise, it
does not wire the runner into the gate, and it does not emit runtime oracles.

The ``oracle_source`` strings below are RUNTIME DATA (plain Python text handed
to the runner), NOT part of this test's own AST, so their importlib spec-load /
file-write content is exempt from this file's exec/eval/__import__ AST ban; the
test's own code never calls exec/eval/__import__.
"""
import os
from pathlib import Path
import pytest
import harness.wire_up as _wu
from harness.wire_up import detonate_oracle, LIVE_ROOTS, observe_symbol_execution
from harness.agent_jail import bwrap_available
REPO_ROOT = Path(_wu.__file__).resolve().parent.parent

def _live_root_basename():
    """Derive the live-root seed basename from the imported LIVE_ROOTS.

    Prefer the orchestrator.py seed (a real LIVE_ROOTS entry); never hardcode.
    """
    for rel in LIVE_ROOTS:
        if os.path.basename(rel) == 'orchestrator.py':
            return 'orchestrator.py'
    return os.path.basename(LIVE_ROOTS[0])

def _live_root_loader_src(basename):
    """Return oracle_source TEXT that synthesises a hermetic live-root frame.

    Writes a tiny module to a temp file whose BASENAME is a LIVE_ROOTS basename
    and loads it via the sanctioned importlib spec-load path, exposing
    ``_lrmod.call(fn)`` -- invoking ``fn()`` from inside that live-root frame so
    the watched symbol acquires a live-root ancestor on its captured lineage.
    """
    return "import importlib.util as _ilu\nimport os as _os\nimport tempfile as _tf\n_lrdir = _tf.mkdtemp()\n_lrpath = _os.path.join(_lrdir, %r)\nwith open(_lrpath, 'w') as _lrf:\n    _lrf.write('def call(fn):\\n    return fn()\\n')\n_lrspec = _ilu.spec_from_file_location('jm_live_root', _lrpath)\n_lrmod = _ilu.module_from_spec(_lrspec)\n_lrspec.loader.exec_module(_lrmod)\n" % (basename,)

def _case1_source():
    return _live_root_loader_src(_live_root_basename()) + 'def tgt():\n    return 1\n_lrmod.call(tgt)\n'

def _case2_source():
    return 'def tgt():\n    return 1\ntgt()\n'

def _case2_regression_source():
    return _live_root_loader_src(_live_root_basename()) + 'def tgt():\n    return 1\ndef marker():\n    return 1\ntgt()\n_lrmod.call(marker)\n'

def _case3_source():
    return _live_root_loader_src(_live_root_basename()) + "import os as _o\nimport socket as _s\ndef cred_dropped():\n    return True\ndef net_isolated():\n    return True\n_gem = _o.path.exists(_o.path.expanduser('~/.gemini'))\n_cla = _o.path.exists(_o.path.expanduser('~/.claude'))\nif (not _gem) and (not _cla):\n    _lrmod.call(cred_dropped)\n_ifaces = sorted(n for _i, n in _s.if_nameindex())\nif _ifaces == ['lo']:\n    _lrmod.call(net_isolated)\n"

def _shape_source():
    return _live_root_loader_src(_live_root_basename()) + 'def tgt():\n    return 1\ndef never():\n    return 1\n_lrmod.call(tgt)\n'

@pytest.fixture(scope='module')
def cred_net_verdict():
    """One real jailed detonation, shared by the cred/net guard tests."""
    if not bwrap_available():
        pytest.skip('bwrap unavailable; jailed cred/net guard needs a real jail')
    src = _case3_source()
    return detonate_oracle(src, ['cred_dropped', 'net_isolated'], LIVE_ROOTS, repo_root=REPO_ROOT)

def test_imports_real_detonate_oracle_and_live_roots_without_mock_or_hardcode():
    assert callable(detonate_oracle)
    assert getattr(detonate_oracle, '__module__', None) == 'harness.wire_up'
    assert 'mock' not in type(detonate_oracle).__module__.lower()
    assert callable(observe_symbol_execution)
    assert getattr(observe_symbol_execution, '__module__', None) == 'harness.wire_up'
    assert isinstance(LIVE_ROOTS, list) and LIVE_ROOTS
    assert any((r.endswith('orchestrator.py') for r in LIVE_ROOTS))

def test_case1_live_root_ancestor_detonation_returns_tgt_true():
    src = _case1_source()
    verdict = detonate_oracle(src, ['tgt'], LIVE_ROOTS, repo_root=REPO_ROOT)
    assert verdict == {'tgt': True}

def test_case2_direct_call_no_ancestor_returns_tgt_false_soundness_hinge():
    src = _case2_source()
    verdict = detonate_oracle(src, ['tgt'], LIVE_ROOTS, repo_root=REPO_ROOT)
    assert verdict == {'tgt': False}

@pytest.mark.skipif(not bwrap_available(), reason='bwrap (bubblewrap) unavailable; the jailed credential-drop guard is only meaningful inside a real bwrap jail')
def test_case3_credential_drop_gemini_and_claude_absent_inside_jail_skipif_no_bwrap(cred_net_verdict):
    assert cred_net_verdict['cred_dropped'] is True

@pytest.mark.skipif(not bwrap_available(), reason='bwrap (bubblewrap) unavailable; the jailed network-isolation guard is only meaningful inside a real bwrap jail')
def test_case3b_network_isolation_only_loopback_via_if_nameindex_skipif_no_bwrap(cred_net_verdict):
    assert cred_net_verdict['net_isolated'] is True

def test_case4_idempotent_verdict_dict_identical_across_two_fresh_calls():
    src = _case1_source()
    v1 = detonate_oracle(src, ['tgt'], LIVE_ROOTS, repo_root=REPO_ROOT)
    v2 = detonate_oracle(src, ['tgt'], LIVE_ROOTS, repo_root=REPO_ROOT)
    assert v1 == {'tgt': True}
    assert v1 == v2

def test_full_verdict_dict_shape_one_bool_per_requested_symbol():
    src = _shape_source()
    symbols = ['tgt', 'never']
    verdict = detonate_oracle(src, symbols, LIVE_ROOTS, repo_root=REPO_ROOT)
    assert set(verdict.keys()) == set(symbols)
    assert all((isinstance(v, bool) for v in verdict.values()))
    assert verdict == {'tgt': True, 'never': False}

def test_red_on_head_importerror_until_primitive_lands():
    assert hasattr(_wu, 'detonate_oracle')
    assert _wu.detonate_oracle is detonate_oracle

@pytest.mark.parametrize('symbols', [['alpha'], ['one', 'two', 'three']])
def test_verdict_keys_exactly_match_requested_symbols_for_arbitrary_symbol_lists(symbols):
    src = 'value = 1 + 1\n'
    verdict = detonate_oracle(src, symbols, LIVE_ROOTS, repo_root=REPO_ROOT)
    assert set(verdict.keys()) == set(symbols)
    assert all((isinstance(v, bool) for v in verdict.values()))
    assert all((v is False for v in verdict.values()))

def test_case2_remains_false_no_false_positive_for_executed_but_unrooted_symbol():
    src = _case2_regression_source()
    verdict = detonate_oracle(src, ['tgt', 'marker'], LIVE_ROOTS, repo_root=REPO_ROOT)
    assert verdict == {'tgt': False, 'marker': True}

@pytest.mark.skipif(not bwrap_available(), reason="bwrap (bubblewrap) unavailable; observing the real spawn's net namespace requires a real bwrap jail")
def test_case3b_observes_actual_spawn_effect_not_freshly_built_argv(cred_net_verdict):
    assert cred_net_verdict['net_isolated'] is True