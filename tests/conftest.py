"""Shared fixtures for JanusMask test suite."""
import json
import sys
import os
from pathlib import Path
import pytest
import yaml
from hypothesis import settings as _hypothesis_settings
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Suite-wide Hypothesis profile: no per-example wall-clock deadline.
# Hypothesis's default 200ms deadline measures wall-clock per example, which
# flakes under full-suite load (the first example pays import/fixture warm-up:
# e.g. test_never_mutates_input_plan hit 456ms once, 0.92ms on replay ->
# DeadlineExceeded -> FlakyFailure). The suite's real performance guards are
# explicit elapsed-time asserts, not Hypothesis deadlines. Tests that set an
# explicit ``deadline=...`` in their own @settings keep their value.
_hypothesis_settings.register_profile("janusmask_no_deadline", deadline=None)
_hypothesis_settings.load_profile("janusmask_no_deadline")

@pytest.fixture(scope='session', autouse=True)
def _hermetic_population_state(tmp_path_factory):
    """Redirect the autocompiler population hook's DEFAULT state base into a
    session tmp dir so tests never write the LIVE ``state/autocompiler/``.

    ``harness.diff_fuzzer._record_population_safe`` defaults its DB base to
    ``<repo>/state`` when ``state_dir`` is None (correct for the production
    worker, which runs at the repo root). With ``population: true`` now the
    shipped default, any test that drives a real non-equivalent fuzz round
    (e.g. via ``fuzz_from_task``) was leaking durable, cross-sweep-growing
    population DBs into live ``state/autocompiler/<task_id>/`` — the same
    live-state-pollution class as the hermeticized webui tests (8d5a88d).
    Only the ``state_dir=None`` default is redirected: oracle tests that
    inject an explicit ``state_dir`` are untouched, and the hook stays fully
    exercised (it writes to the hermetic base instead).
    """
    import harness.diff_fuzzer as _df
    _orig = _df._record_population_safe
    _base = tmp_path_factory.mktemp('ac_population_hermetic')

    def _wrapped(code_a, code_b, task, result, state_dir=None):
        return _orig(code_a, code_b, task, result,
                     state_dir=_base if state_dir is None else state_dir)

    _df._record_population_safe = _wrapped
    try:
        yield
    finally:
        _df._record_population_safe = _orig

@pytest.fixture(autouse=True)
def _reset_janusmask_task_id_env():
    """Reset all JANUSMASK_* env vars around every test (function-scoped, autouse).

    Snapshots every ``JANUSMASK_*``-prefixed entry in ``os.environ`` on entry,
    removes them so the test body sees a clean ``JANUSMASK_*`` namespace,
    yields, then in a ``finally`` block scrubs any ``JANUSMASK_*`` added by
    the test body and restores the original snapshot via
    ``os.environ.update(saved)``. The ``try/finally`` guarantees restoration
    even if the test body raises.

    Why the broader scope (vs. the pre-G3b TASK_ID-only version):
    ``harness/orchestrator.py`` (``run_pipeline`` and friends) mutate several
    ``JANUSMASK_*`` env vars directly (``JANUSMASK_TASK_ID``,
    ``JANUSMASK_AGENT``, ``JANUSMASK_STATE_DIR``, ...). When the harness
    invokes pytest under a parent process that has any of these set, the leak
    corrupts ``TestCollectSubmissions`` and similar suites (session-filename
    generation in ``collect_submissions`` keys off ``JANUSMASK_TASK_ID``).
    The wildcard prefix scrub closes the parent->test-body leak class.

    Why the name ``_reset_janusmask_task_id_env`` is preserved:
    The AST-merge step in the harness keys on ``FunctionDef`` name. Renaming
    this fixture (e.g. to ``_reset_janusmask_env``) would NOT replace the old
    definition in the target file -- it would append a second autouse fixture
    while leaving the original in place, producing two competing autouse
    fixtures and breaking test isolation. The name is therefore load-bearing
    for the keyed-replace and must NOT be changed even though its scope has
    grown beyond ``JANUSMASK_TASK_ID``.
    """
    saved = {k: v for k, v in os.environ.items() if k.startswith('JANUSMASK_')}
    for k in saved:
        os.environ.pop(k, None)
    try:
        yield
    finally:
        leaked = [k for k in list(os.environ) if k.startswith('JANUSMASK_')]
        for k in leaked:
            os.environ.pop(k, None)
        os.environ.update(saved)

@pytest.fixture
def tmp_state_dir(tmp_path):
    """Fresh temp directory with state/, sessions/, tasks/ subdirs."""
    for sub in ('sessions', 'tasks', 'tasks/processed'):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    return tmp_path

@pytest.fixture
def state_dir(tmp_path, monkeypatch):
    """Canonical test state directory (T3-5 W1).

    Creates ``tmp_path/state/`` with ``sessions/``, ``tasks/``, and
    ``tasks/processed/`` subdirs, then sets ``JANUSMASK_STATE_DIR`` to
    that path so harness code resolving ``_default_state_dir()`` lands
    on the temp. Does NOT initialize ``STATE.json`` or
    ``track_record.jsonl`` — layer ``seeded_state_dir`` /
    ``initialized_state_dir`` on top of this for that.
    """
    sd = tmp_path / 'state'
    sd.mkdir()
    for sub in ('sessions', 'tasks', 'tasks/processed'):
        (sd / sub).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv('JANUSMASK_STATE_DIR', str(sd))
    return sd

@pytest.fixture
def initialized_state_dir(tmp_state_dir):
    """tmp_state_dir with STATE.json already written."""
    from harness.state import init_state
    init_state(tmp_state_dir)
    return tmp_state_dir

@pytest.fixture
def seeded_state_dir(state_dir):
    """Canonical state_dir + taxonomies seeded from fixture files + track_record initialized.

    Reads tests/fixtures/taxonomies/{meta_task_v1,synthesis_target_v1}.json (raw key arrays),
    transforms to live-shape {"version": 1, "keys": {...}}, writes to state_dir, then calls
    init_track_record(state_dir). Env var already set by parent state_dir fixture.
    """
    from harness.track_record import init_track_record
    src_meta = PROJECT_ROOT / 'tests' / 'fixtures' / 'taxonomies' / 'meta_task_v1.json'
    src_synth = PROJECT_ROOT / 'tests' / 'fixtures' / 'taxonomies' / 'synthesis_target_v1.json'
    meta_keys = json.loads(src_meta.read_text())
    synth_keys = json.loads(src_synth.read_text())
    meta_tax = {'version': 1, 'keys': {k: k for k in meta_keys}}
    synth_tax = {'version': 1, 'keys': {k: k for k in synth_keys}}
    (state_dir / 'meta_task_taxonomy.json').write_text(json.dumps(meta_tax))
    (state_dir / 'synthesis_target_taxonomy.json').write_text(json.dumps(synth_tax))
    init_track_record(state_dir)
    return state_dir

@pytest.fixture
def initialized_state_dir_v2(state_dir):
    """Canonical state_dir + STATE.json via init_state() (nested tmp_path/state)."""
    from harness.state import init_state
    init_state(state_dir)
    return state_dir

@pytest.fixture
def initialized_track_record_dir(seeded_state_dir):
    """Alias for seeded_state_dir; semantic clarity when tests need both state + track_record."""
    return seeded_state_dir

@pytest.fixture
def sample_config():
    """Default config.yaml loaded as dict."""
    config_path = PROJECT_ROOT / 'harness' / 'config.yaml'
    with open(config_path) as f:
        return yaml.safe_load(f)

@pytest.fixture
def fast_config(sample_config):
    """Config with reduced fuzz inputs for fast testing."""
    cfg = dict(sample_config)
    cfg['fuzzing'] = dict(cfg.get('fuzzing', {}))
    cfg['fuzzing']['function_level_inputs'] = 50
    cfg['fuzzing']['program_level_inputs'] = 20
    cfg['fuzzing']['timeout_per_input_ms'] = 2000
    cfg['sandbox'] = dict(cfg.get('sandbox', {}))
    cfg['sandbox']['cpu_time_limit_seconds'] = 5
    return cfg

@pytest.fixture
def sample_task():
    """A simple merge_sorted task dict."""
    return {'task_id': 'task-001', 'round': 1, 'specification': 'Write a function `merge_sorted(a, b)` that merges two sorted lists into a single sorted list.', 'constraints': {'language': 'python', 'function_signature': 'def merge_sorted(a: list[int], b: list[int]) -> list[int]', 'deterministic': True, 'max_lines': 50}, 'feedback': None}

@pytest.fixture
def sample_code_valid():
    return 'def merge_sorted(a: list[int], b: list[int]) -> list[int]:\n    result = []\n    i = j = 0\n    while i < len(a) and j < len(b):\n        if a[i] <= b[j]:\n            result.append(a[i])\n            i += 1\n        else:\n            result.append(b[j])\n            j += 1\n    result.extend(a[i:])\n    result.extend(b[j:])\n    return result\n'

@pytest.fixture
def sample_code_invalid_syntax():
    return 'def merge_sorted(a, b):\n    return a +\n'

@pytest.fixture
def sample_code_nondeterministic():
    return 'import random\ndef shuffle_list(items: list[int]) -> list[int]:\n    result = list(items)\n    random.shuffle(result)\n    return result\n'

@pytest.fixture
def equivalent_code_pair():
    code_a = 'def add(a: int, b: int) -> int:\n    return a + b\n'
    code_b = 'def add(a: int, b: int) -> int:\n    result = a + b\n    return result\n'
    return (code_a, code_b)

@pytest.fixture
def divergent_code_pair():
    code_a = 'def is_palindrome(s: str) -> bool:\n    return s == s[::-1]\n'
    code_b = 'def is_palindrome(s: str) -> bool:\n    s = s.lower()\n    return s == s[::-1]\n'
    return (code_a, code_b)

@pytest.fixture
def load_fixture():
    """Helper to load a JSON/JSONL fixture by category and name."""

    def _load(category: str, name: str):
        fixture_path = Path(__file__).parent / 'fixtures' / category / name
        if fixture_path.suffix == '.json':
            with open(fixture_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        elif fixture_path.suffix == '.jsonl':
            with open(fixture_path, 'r', encoding='utf-8') as f:
                return [json.loads(line) for line in f if line.strip()]
        else:
            raise ValueError(f'Unsupported fixture format: {fixture_path.suffix}')
    return _load