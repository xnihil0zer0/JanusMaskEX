"""Hermetic, non-vacuous oracle for read-derived failure propagation in
``harness.brief_status.compute_epic_status`` / ``epic_has_failed_descendant``.

The tests import the REAL committed symbols and exercise their actual observable
behaviour. They are hermetic (tmp_path only) and prove that:

* flag ON  + a *transitive* failed descendant  => epic surfaces ``'blocked'``
* flag OFF (or the config key absent)          => the exact Phase-1 result,
                                                  unchanged by a failed descendant

Each behavioural assertion is sensitive to the real propagation logic (see the
non-vacuity guard, which neutralises the helper and shows the assertion flips).
"""
import inspect
import json
from pathlib import Path
import pytest
from harness.brief_status import compute_epic_status, epic_has_failed_descendant

def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')

def _append(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'a', encoding='utf-8') as f:
        f.write(text)

def _make_epic(repo_root: Path, slug: str, child_slugs: list) -> None:
    """An epic plan file (read by compute_epic_status + _build_epic_children_map)."""
    _write(repo_root / f'plan_hooks_{slug}.json', json.dumps({'plan_kind': 'epic', 'epic_slug': slug, 'child_slugs': child_slugs}))

def _make_leaf(repo_root: Path, state_dir: Path, slug: str, *, status: str) -> None:
    """A leaf brief/plan whose compute_brief_status state == ``status``.

    Drives the slug->state roll-up that compute_epic_status reads, by placing the
    same on-disk markers the substrate already consults (blocked/processed/ledger).
    """
    tid = f'{slug}_t1'
    _write(repo_root / f'brief_hooks_{slug}.md', f'# brief {slug}\n')
    _write(repo_root / f'plan_hooks_{slug}.json', json.dumps({'plan_kind': 'leaf', 'tasks': [{'task_id': tid}]}))
    if status == 'blocked':
        _write(state_dir / 'tasks' / 'blocked' / f'{tid}.json', '{}')
    elif status == 'zombie':
        _write(state_dir / 'tasks' / 'processed' / f'{tid}.json', '{}')
    elif status == 'complete':
        _append(state_dir / 'impl_progress.jsonl', json.dumps({'phase': 'accepted', 'event': 'auto_commit', 'task_id': tid, 'commit_sha': 'deadbeef', 'ts': 1}) + '\n')
    else:
        raise ValueError(f'unsupported leaf status: {status!r}')

def _dirs(tmp_path: Path):
    repo_root = tmp_path / 'repo'
    state_dir = tmp_path / 'state'
    repo_root.mkdir()
    state_dir.mkdir()
    return (repo_root, state_dir)

def _transitive_fixture(tmp_path: Path, *, leaf_status: str='blocked'):
    """epic_root -> child_mid -> leaf  (the leaf is the only graded slug).

    ``child_mid`` has no brief, so it is 'unplanned' in the roll-up; epic_root is
    therefore NOT blocked by Phase-1 logic -- only the transitive walk can block it.
    """
    repo_root, state_dir = _dirs(tmp_path)
    _make_epic(repo_root, 'epic_root', ['child_mid'])
    _make_epic(repo_root, 'child_mid', ['leaf'])
    _make_leaf(repo_root, state_dir, 'leaf', status=leaf_status)
    return (repo_root, state_dir)

def _matrix_fixture(tmp_path: Path):
    """Multi-level fixture combining transitive / direct-failed / clean epics."""
    repo_root, state_dir = _dirs(tmp_path)
    _make_epic(repo_root, 'epic_transitive', ['mid'])
    _make_epic(repo_root, 'mid', ['leaf_t'])
    _make_leaf(repo_root, state_dir, 'leaf_t', status='blocked')
    _make_epic(repo_root, 'epic_direct', ['leaf_d'])
    _make_leaf(repo_root, state_dir, 'leaf_d', status='blocked')
    _make_epic(repo_root, 'epic_clean', ['leaf_done'])
    _make_leaf(repo_root, state_dir, 'leaf_done', status='complete')
    return (repo_root, state_dir)

def _state_of(result: list, epic_slug: str) -> str:
    for rec in result:
        if rec.get('epic_slug') == epic_slug:
            return rec['state']
    raise AssertionError(f'epic {epic_slug!r} not present in {[r.get('epic_slug') for r in result]}')

def _snapshot(root: Path) -> set:
    return {str(p.relative_to(root)) for p in Path(root).rglob('*') if p.is_file()}
FLAG_ON = {'hierarchical_planning': {'failure_propagation': True}}
FLAG_OFF = {'hierarchical_planning': {'failure_propagation': False}}

def test_epic_has_failed_descendant_transitive_true_else_false():
    epic_children = {'e': ['a'], 'a': ['b'], 'b': ['c']}
    assert epic_has_failed_descendant('e', epic_children, {'c': 'blocked'}) is True
    assert epic_has_failed_descendant('e', epic_children, {'c': 'zombie'}) is True
    assert epic_has_failed_descendant('e', {'e': ['x']}, {'x': 'blocked'}) is True
    assert epic_has_failed_descendant('e', epic_children, {'c': 'complete'}) is False
    assert epic_has_failed_descendant('e', {}, {}) is False

def test_epic_has_failed_descendant_real_signature_no_invented_params():
    sig = inspect.signature(epic_has_failed_descendant)
    assert list(sig.parameters) == ['epic_slug', 'epic_children', 'status_index']
    esig = inspect.signature(compute_epic_status)
    assert list(esig.parameters) == ['repo_root', 'state_dir', 'config']

def test_compute_epic_status_blocked_when_flag_on_and_transitive_failed(tmp_path):
    repo_root, state_dir = _transitive_fixture(tmp_path, leaf_status='blocked')
    result = compute_epic_status(repo_root, state_dir, FLAG_ON)
    assert _state_of(result, 'epic_root') == 'blocked'

def test_compute_epic_status_returns_exact_phase1_result_when_flag_off(tmp_path):
    repo_root, state_dir = _transitive_fixture(tmp_path, leaf_status='blocked')
    off = compute_epic_status(repo_root, state_dir, FLAG_OFF)
    none = compute_epic_status(repo_root, state_dir, None)
    assert off == none
    assert _state_of(off, 'epic_root') == 'in_flight'
    assert _state_of(off, 'epic_root') != 'blocked'

def test_config_missing_failure_propagation_key_treated_as_off(tmp_path):
    repo_root, state_dir = _transitive_fixture(tmp_path, leaf_status='blocked')
    baseline = compute_epic_status(repo_root, state_dir, None)
    for cfg in ({}, {'hierarchical_planning': {}}, {'hierarchical_planning': {'enabled': True}}):
        result = compute_epic_status(repo_root, state_dir, cfg)
        assert result == baseline
        assert _state_of(result, 'epic_root') == 'in_flight'

def test_compute_epic_status_flag_matrix_over_multilevel_fixture(tmp_path):
    repo_root, state_dir = _matrix_fixture(tmp_path)
    off = compute_epic_status(repo_root, state_dir, FLAG_OFF)
    expected_off = {'epic_transitive': 'in_flight', 'epic_direct': 'blocked', 'epic_clean': 'complete', 'mid': 'blocked'}
    for slug, state in expected_off.items():
        assert _state_of(off, slug) == state
    on = compute_epic_status(repo_root, state_dir, FLAG_ON)
    expected_on = {'epic_transitive': 'blocked', 'epic_direct': 'blocked', 'epic_clean': 'complete', 'mid': 'blocked'}
    for slug, state in expected_on.items():
        assert _state_of(on, slug) == state
    assert _state_of(off, 'epic_transitive') == 'in_flight'
    assert _state_of(on, 'epic_transitive') == 'blocked'

def test_flag_off_status_invariant_to_injected_failed_descendant(tmp_path):
    healthy_root = tmp_path / 'healthy'
    failed_root = tmp_path / 'failed'
    healthy_root.mkdir()
    failed_root.mkdir()
    repo_h, state_h = _transitive_fixture(healthy_root, leaf_status='complete')
    repo_f, state_f = _transitive_fixture(failed_root, leaf_status='blocked')
    state_healthy = _state_of(compute_epic_status(repo_h, state_h, FLAG_OFF), 'epic_root')
    state_failed = _state_of(compute_epic_status(repo_f, state_f, FLAG_OFF), 'epic_root')
    assert state_healthy == state_failed == 'in_flight'
    state_failed_on = _state_of(compute_epic_status(repo_f, state_f, FLAG_ON), 'epic_root')
    assert state_failed_on == 'blocked'

def test_no_new_files_written_during_computation(tmp_path):
    repo_root, state_dir = _transitive_fixture(tmp_path, leaf_status='blocked')
    before = _snapshot(tmp_path)
    compute_epic_status(repo_root, state_dir, FLAG_ON)
    compute_epic_status(repo_root, state_dir, FLAG_OFF)
    epic_has_failed_descendant('epic_root', {'epic_root': ['child_mid'], 'child_mid': ['leaf']}, {'leaf': 'blocked'})
    after = _snapshot(tmp_path)
    assert after == before, f'computation created files: {after - before}'

def test_non_vacuity_guard_blocking_depends_on_real_helper(tmp_path, monkeypatch):
    repo_root, state_dir = _transitive_fixture(tmp_path, leaf_status='blocked')
    real = compute_epic_status(repo_root, state_dir, FLAG_ON)
    assert _state_of(real, 'epic_root') == 'blocked'
    monkeypatch.setattr('harness.brief_status.epic_has_failed_descendant', lambda *a, **k: False)
    mutated = compute_epic_status(repo_root, state_dir, FLAG_ON)
    assert _state_of(mutated, 'epic_root') != 'blocked'
    assert _state_of(mutated, 'epic_root') == 'in_flight'