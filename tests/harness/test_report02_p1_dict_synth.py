"""RED behavioral oracle for report02-p1-dict-synth (domain-dict input synthesis).

Pins the SIX behaviors of the P1 lock-step change-set across the two seams:

  Seam 1 -- ``harness/diff_fuzzer.py``:  ``_dict_corpus_synthesis_enabled``,
            ``_dict_strategy_for``, the ``_DICT_CORPUS_*`` / name-keyed corpus
            tables, and the shadow-mode dispatch wired into
            ``build_input_strategy``.
  Seam 2 -- ``harness/rebuild/harvest.py``:  the lock-step widening of
            ``_is_fuzzable_annotation`` (gated by harvest's own
            ``_dict_corpus_synthesis_enabled``).

The change-set ships DEFAULT-OFF (``autowork.dict_corpus_synthesis``); the OFF
path is byte-identical to HEAD and the ON path is SHADOW-MODE (compute + log,
non-blocking).  This file is RED at HEAD because the new symbols / widening do
not yet exist; it turns GREEN only after report02-p1-dict-synth-impl lands BOTH
seams in one change-set.

The flag is toggled by monkeypatching the guarded reader(s)
(``diff_fuzzer._dict_corpus_synthesis_enabled`` /
``harvest._dict_corpus_synthesis_enabled``).  Tier-3 ``hypothesis_jsonschema``
is NOT installed in the factory interpreter, so the oracle exercises ONLY the
tier-2 corpus path and never imports it.
"""
from __future__ import annotations
import ast
import inspect
import logging
import sys
import pytest
from hypothesis import HealthCheck, Phase, given, settings
from hypothesis import seed as h_seed
from hypothesis import strategies as st
from harness import diff_fuzzer
from harness.diff_fuzzer import build_input_strategy, extract_function_signature, _strategy_for_annotation
from harness.planner.taxonomies import BYPASS_FUZZER_TYPES
from harness.rebuild import harvest
LOGGER_NAME = 'janusmask.diff_fuzzer'
_CONFIG_CODE = 'def handle(config: dict):\n    return config\n'
_CANDIDATES_CODE = 'def run(candidates: list[dict]):\n    return candidates\n'
_SAMPLE_SIGNATURES = [('def handle(config: dict):\n    return config\n', 'handle'), ('def run(candidates: list[dict]):\n    return candidates\n', 'run'), ('def add(a: int, b: int):\n    return a + b\n', 'add'), ('def tag(name: str):\n    return name\n', 'tag')]
_EXPECTED_BYPASS = frozenset({'mcp_server_change', 'config_schema', 'test_unit', 'test_integration', 'test_e2e', 'test_acceptance', 'docs_writing', 'hooks_integration', 'mcp_plumbing', 'epic_planning'})

def _gen_inputs(strategy: st.SearchStrategy, count: int=60, seed: int=0) -> list:
    """Draw a list of DISTINCT concrete values from *strategy* deterministically.

    Uses a tiny @given collection loop (generate-phase only, no example DB) so
    the same seed yields the same sequence -- mirroring diff_fuzzer's own
    ``_generate_inputs`` without running inside the live fuzz pipeline.
    """
    collected: list = []
    seen: set[str] = set()

    @h_seed(seed)
    @settings(max_examples=max(count, 50), suppress_health_check=list(HealthCheck), phases=(Phase.generate,), deadline=None, database=None)
    @given(value=strategy)
    def _collect(value) -> None:
        key = repr(value)
        if key not in seen:
            seen.add(key)
            collected.append(value)
    _collect()
    return collected

def _ann_node(annotation: str) -> ast.expr:
    """Parse a bare annotation string into the ast.expr the classifier consumes."""
    return ast.parse(annotation, mode='eval').body

def _is_fuzzable(node: ast.expr, name: str | None=None) -> bool:
    """Call harvest._is_fuzzable_annotation, threading a param *name* if the
    (possibly widened) signature accepts one."""
    fn = harvest._is_fuzzable_annotation
    try:
        nparams = len(inspect.signature(fn).parameters)
    except (TypeError, ValueError):
        nparams = 1
    if name is not None and nparams >= 2:
        return fn(node, name)
    return fn(node)

def _off(monkeypatch) -> None:
    """Force the flag OFF on BOTH seams (byte-identical-to-HEAD path)."""
    monkeypatch.setattr(diff_fuzzer, '_dict_corpus_synthesis_enabled', lambda *a, **k: False)
    monkeypatch.setattr(harvest, '_dict_corpus_synthesis_enabled', lambda *a, **k: False)

def _on(monkeypatch) -> None:
    """Force the flag ON on BOTH seams (shadow-mode path)."""
    monkeypatch.setattr(diff_fuzzer, '_dict_corpus_synthesis_enabled', lambda *a, **k: True)
    monkeypatch.setattr(harvest, '_dict_corpus_synthesis_enabled', lambda *a, **k: True)

def test_off_byte_identity_strategy_and_classifier(monkeypatch):
    """With the flag OFF, ``_dict_strategy_for`` is NEVER consulted by
    ``build_input_strategy`` (so the strategy is the HEAD int-fallback kind) and
    ``_is_fuzzable_annotation`` gives the SAME (HEAD) verdict for a bare dict."""
    _off(monkeypatch)
    consulted: list = []

    def _spy(*args, **kwargs):
        consulted.append((args, kwargs))
        return None
    monkeypatch.setattr(diff_fuzzer, '_dict_strategy_for', _spy)
    strat = build_input_strategy(_CONFIG_CODE, 'handle')
    inputs = _gen_inputs(strat, seed=1)
    assert consulted == [], '_dict_strategy_for must NOT be consulted when OFF'
    assert inputs, 'OFF path must still generate inputs'
    for args, kwargs in inputs:
        assert kwargs == {}
        assert isinstance(args[0], int)
    assert _is_fuzzable(_ann_node('dict'), 'config') is False
    assert _is_fuzzable(_ann_node('int')) is True

def test_on_shadow_produces_config_and_list_dict_strategies(monkeypatch):
    """With the flag ON, the dict dispatch returns non-None strategies that
    generate >=5 distinct well-typed inputs for bare ``dict`` and ``list[dict]``
    -- including whitespaced / capitalized ``List`` spellings -- without raising."""
    _on(monkeypatch)
    cfg_strat = diff_fuzzer._dict_strategy_for('config', 'dict')
    assert cfg_strat is not None
    cfg_inputs = _gen_inputs(cfg_strat, seed=2)
    assert len({repr(v) for v in cfg_inputs}) >= 5
    assert all((isinstance(v, dict) for v in cfg_inputs))
    lst_strat = diff_fuzzer._dict_strategy_for('candidates', 'list[dict]')
    assert lst_strat is not None
    lst_inputs = _gen_inputs(lst_strat, seed=3)
    assert len({repr(v) for v in lst_inputs}) >= 5
    for v in lst_inputs:
        assert isinstance(v, list)
        assert all((isinstance(e, dict) for e in v))
    for spelling in ('List[dict]', 'list[ dict ]', 'List[ dict ]'):
        alt = diff_fuzzer._dict_strategy_for('candidates', spelling)
        assert alt is not None, f'{spelling!r} must resolve to the list-of-dict corpus'
    built = build_input_strategy(_CONFIG_CODE, 'handle')
    built_inputs = _gen_inputs(built, seed=4)
    assert built_inputs
    assert any((isinstance(args[0], dict) for args, _kw in built_inputs))

def test_on_shadow_telemetry_logged_via_caplog(monkeypatch, caplog):
    """The ON dispatch logs a one-line ``logger.info`` shadow record on
    ``janusmask.diff_fuzzer`` carrying the marker, param name, and annotation."""
    _on(monkeypatch)
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        build_input_strategy(_CONFIG_CODE, 'handle')
    shadow = [r for r in caplog.records if r.name == LOGGER_NAME and 'dict_corpus_synthesis shadow' in r.getMessage()]
    assert shadow, "expected a 'dict_corpus_synthesis shadow' info record"
    blob = ' '.join((r.getMessage() for r in shadow))
    assert 'config' in blob
    assert 'dict' in blob

def test_unknown_domain_returns_none_fallback(monkeypatch):
    """An unregistered param name with a bare ``dict`` annotation yields None so
    the caller falls back to ``_strategy_for_annotation`` (not an empty
    ``st.sampled_from``)."""
    _on(monkeypatch)
    assert diff_fuzzer._dict_strategy_for('mystery_blob', 'dict') is None
    assert diff_fuzzer._dict_strategy_for('config', 'dict') is not None

def test_lockstep_on_is_fuzzable_annotation_true_for_registered_dict(monkeypatch):
    """With the flag ON, ``_is_fuzzable_annotation`` classifies a bare ``dict``
    param of a registered domain as fuzzable -- in lock-step with the strategy
    that now synthesizes it (Seam 1)."""
    _on(monkeypatch)
    assert _is_fuzzable(_ann_node('dict'), 'config') is True
    assert diff_fuzzer._dict_strategy_for('config', 'dict') is not None

def test_bypass_fuzzer_types_unchanged():
    """The frozenset equals its HEAD membership; the diff_fuzzer alias is the
    same object (no member removed by the change-set)."""
    assert isinstance(BYPASS_FUZZER_TYPES, frozenset)
    assert BYPASS_FUZZER_TYPES == _EXPECTED_BYPASS
    assert diff_fuzzer.FUZZ_BYPASS_META_TYPES == _EXPECTED_BYPASS

def _head_strategy(code: str, func_name: str) -> st.SearchStrategy:
    """Reconstruct the exact HEAD ``build_input_strategy`` composite directly
    from ``_strategy_for_annotation`` (the pre-change pathway)."""
    sig = extract_function_signature(code, func_name)
    param_strategies = {name: _strategy_for_annotation(ann) for name, ann in sig.items()}
    names = list(sig.keys())

    @st.composite
    def _inp(draw):
        return ([draw(param_strategies[n]) for n in names], {})
    return _inp()

def test_build_input_strategy_off_matches_head_for_sample_signatures(monkeypatch):
    """For a sample of bare-``dict`` / ``list[dict]`` / primitive signatures, the
    OFF strategy yields byte-identical inputs to the HEAD path and never consults
    ``_dict_strategy_for``."""
    _off(monkeypatch)
    consulted: list = []
    monkeypatch.setattr(diff_fuzzer, '_dict_strategy_for', lambda *a, **k: consulted.append(a) or None)
    for code, func_name in _SAMPLE_SIGNATURES:
        off_inputs = _gen_inputs(build_input_strategy(code, func_name), seed=7)
        head_inputs = _gen_inputs(_head_strategy(code, func_name), seed=7)
        assert off_inputs == head_inputs, f'OFF != HEAD for {func_name!r}'
    assert consulted == [], '_dict_strategy_for must NOT be consulted on the OFF path'

def test_corpus_strategies_generate_ge5_distinct_well_typed_inputs(monkeypatch):
    """Every registered bare-dict domain yields >=5 distinct dicts; the
    list-of-dict domain yields >=5 distinct lists of dicts."""
    _on(monkeypatch)
    for name in ('config', 'task', 'plan'):
        strat = diff_fuzzer._dict_strategy_for(name, 'dict')
        assert strat is not None, f'{name!r} must be a registered dict domain'
        values = _gen_inputs(strat, seed=11)
        assert len({repr(v) for v in values}) >= 5, f'{name!r} corpus < 5 distinct'
        assert all((isinstance(v, dict) for v in values))
    lst = diff_fuzzer._dict_strategy_for('candidates', 'list[dict]')
    assert lst is not None
    lst_values = _gen_inputs(lst, seed=12)
    assert len({repr(v) for v in lst_values}) >= 5
    for v in lst_values:
        assert isinstance(v, list)
        assert all((isinstance(e, dict) for e in v))

def _read_config(cfg: dict) -> int:
    """A tiny real-shaped config reader: count keys, recursing into nested dicts."""
    total = 0
    for value in cfg.values():
        total += 1
        if isinstance(value, dict):
            total += len(value)
    return total

def test_non_vacuity_faithful_agrees_broken_diverges(monkeypatch):
    """Over the generated config corpus, a faithful clone agrees with the
    original on EVERY input while a deliberately-broken clone diverges on at
    least one -- proving the corpus exercises real logic."""
    _on(monkeypatch)
    strat = diff_fuzzer._dict_strategy_for('config', 'dict')
    assert strat is not None
    corpus = _gen_inputs(strat, seed=13)
    assert len(corpus) >= 5, 'non-vacuity needs a real, non-trivial corpus'
    assert all((isinstance(c, dict) and c for c in corpus)), 'corpus dicts must be non-empty'

    def original(cfg: dict) -> int:
        return _read_config(cfg)

    def faithful(cfg: dict) -> int:
        return _read_config(cfg)

    def broken(cfg: dict) -> int:
        return -_read_config(cfg)
    assert all((faithful(c) == original(c) for c in corpus)), 'faithful must agree everywhere'
    assert any((broken(c) != original(c) for c in corpus)), 'broken must diverge somewhere'

def test_tier3_import_guarded_no_hypothesis_jsonschema_required(monkeypatch):
    """The tier-2 corpus path works with ``hypothesis`` alone; importing
    ``hypothesis_jsonschema`` is NOT required (it is absent in the factory
    interpreter)."""
    _on(monkeypatch)
    monkeypatch.setitem(sys.modules, 'hypothesis_jsonschema', None)
    strat = diff_fuzzer._dict_strategy_for('config', 'dict')
    assert strat is not None
    values = _gen_inputs(strat, seed=17)
    assert len({repr(v) for v in values}) >= 5
    assert all((isinstance(v, dict) for v in values))