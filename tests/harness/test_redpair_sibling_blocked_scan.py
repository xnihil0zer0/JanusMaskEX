"""RED oracle: ``load_sibling_tasks`` must scan ``state/tasks/blocked/`` for
sibling impls, including live-retryable ones (carrying only a ``<id>.retry.json``
sidecar) and EXCLUDING permanently-dead ones (carrying a ``<id>.exhausted``
sidecar), and that discovery change must flow through to
``is_fix_forward_redpair``.

This is a hermetic, unit-level oracle over synthetic ``tmp_path`` state trees and
a synthetic worktree. It calls the REAL ``harness.redpair_acceptance`` functions
(no reimplementation, no monkeypatching of those functions). It is RED against the
current code (which scans only ``processed/`` and the base ``tasks/`` dir, so the
blocked-live case misses the sibling) and GREEN once the paired impl lands.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
import pytest
_HERE = Path(__file__).resolve()
for _cand in _HERE.parents:
    if (_cand / 'harness' / 'redpair_acceptance.py').is_file():
        if str(_cand) not in sys.path:
            sys.path.insert(0, str(_cand))
        break
import harness.redpair_acceptance as rp
ORACLE_ID = 'redpair-sibling-blocked-scan-oracle'
IMPL_ID = 'redpair-sibling-blocked-scan-impl'
ORACLE_TEST_FILE = 'tests/harness/test_redpair_sibling_blocked_scan.py'
IMPL_TARGET_FILE = 'harness/redpair_acceptance.py'
MUTATION_TARGET = 'harness.redpair_acceptance'

def _make_oracle_task() -> dict:
    """The RED test_authoring oracle task for the EXISTING module under test."""
    return {'task_id': ORACLE_ID, 'meta_task_type': 'test_authoring', 'mutation_target': MUTATION_TARGET, 'files_touched': [ORACLE_TEST_FILE], 'dependencies': [IMPL_ID]}

def _make_impl_task() -> dict:
    """The paired non-test_authoring impl sibling. Its verification_command
    substring-contains the oracle's own files_touched[0] so the file-keyed
    red-pair binding in ``is_fix_forward_redpair`` holds."""
    return {'task_id': IMPL_ID, 'meta_task_type': 'harness_self_fix', 'files_touched': [IMPL_TARGET_FILE], 'dependencies': [ORACLE_ID], 'verification_command': 'python -m pytest ' + ORACLE_TEST_FILE + ' -q'}

def _build_state_tree(tmp_path: Path):
    """Create state/tasks/, state/tasks/processed/, state/tasks/blocked/."""
    state_dir = tmp_path / 'state'
    tasks = state_dir / 'tasks'
    processed = tasks / 'processed'
    blocked = tasks / 'blocked'
    for d in (tasks, processed, blocked):
        d.mkdir(parents=True, exist_ok=True)
    return (state_dir, tasks, processed, blocked)

def _build_worktree(tmp_path: Path) -> Path:
    """Synthetic worktree whose harness/redpair_acceptance.py exists so the
    target_rel is_file() check inside is_fix_forward_redpair passes."""
    worktree = tmp_path / 'wt'
    target = worktree / 'harness' / 'redpair_acceptance.py'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('# synthetic target file (content irrelevant)\n')
    return worktree

def _place_impl(directory: Path, impl_task: dict, *, retry: bool=False, exhausted: bool=False) -> None:
    """Serialize the impl task JSON into ``directory`` plus optional sidecars."""
    (directory / (IMPL_ID + '.json')).write_text(json.dumps(impl_task))
    if retry:
        (directory / (IMPL_ID + '.retry.json')).write_text(json.dumps({'retryable': True}))
    if exhausted:
        (directory / (IMPL_ID + '.exhausted')).write_text('dead\n')

def _has_impl(sibs) -> bool:
    """True iff the impl sibling (task_id == IMPL_ID) is present in the result."""
    return any((isinstance(s, dict) and s.get('task_id') == IMPL_ID for s in sibs))

def test_blocked_retry_only_sibling_returned_and_flips_redpair_true(tmp_path):
    state_dir, tasks, processed, blocked = _build_state_tree(tmp_path)
    worktree = _build_worktree(tmp_path)
    oracle_task = _make_oracle_task()
    impl_task = _make_impl_task()
    _place_impl(blocked, impl_task, retry=True, exhausted=False)
    sibs = rp.load_sibling_tasks(str(state_dir), oracle_task, ORACLE_ID)
    assert isinstance(sibs, list)
    assert _has_impl(sibs), 'a blocked/ sibling carrying only <id>.retry.json must be discovered by load_sibling_tasks'
    assert rp.is_fix_forward_redpair(oracle_task, str(worktree), sibs) is True

def test_blocked_exhausted_sibling_excluded_and_redpair_false(tmp_path):
    state_dir, tasks, processed, blocked = _build_state_tree(tmp_path)
    worktree = _build_worktree(tmp_path)
    oracle_task = _make_oracle_task()
    impl_task = _make_impl_task()
    _place_impl(blocked, impl_task, retry=False, exhausted=True)
    sibs = rp.load_sibling_tasks(str(state_dir), oracle_task, ORACLE_ID)
    assert isinstance(sibs, list)
    assert not _has_impl(sibs), 'a blocked/ sibling carrying a <id>.exhausted sidecar must be EXCLUDED from load_sibling_tasks'
    assert rp.is_fix_forward_redpair(oracle_task, str(worktree), sibs) is False

def test_base_sibling_still_found_and_accepts_oracle(tmp_path):
    state_dir, tasks, processed, blocked = _build_state_tree(tmp_path)
    worktree = _build_worktree(tmp_path)
    oracle_task = _make_oracle_task()
    impl_task = _make_impl_task()
    _place_impl(tasks, impl_task)
    sibs = rp.load_sibling_tasks(str(state_dir), oracle_task, ORACLE_ID)
    assert isinstance(sibs, list)
    assert _has_impl(sibs), 'base/ sibling discovery must not regress'
    assert rp.is_fix_forward_redpair(oracle_task, str(worktree), sibs) is True

def test_processed_sibling_still_found_and_accepts_oracle(tmp_path):
    state_dir, tasks, processed, blocked = _build_state_tree(tmp_path)
    worktree = _build_worktree(tmp_path)
    oracle_task = _make_oracle_task()
    impl_task = _make_impl_task()
    _place_impl(processed, impl_task)
    sibs = rp.load_sibling_tasks(str(state_dir), oracle_task, ORACLE_ID)
    assert isinstance(sibs, list)
    assert _has_impl(sibs), 'processed/ sibling discovery must not regress'
    assert rp.is_fix_forward_redpair(oracle_task, str(worktree), sibs) is True

def test_load_sibling_tasks_returns_list_and_never_raises(tmp_path):
    state_dir, tasks, processed, blocked = _build_state_tree(tmp_path)
    oracle_task = _make_oracle_task()
    (tasks / (IMPL_ID + '.json')).write_text('{ this is not valid json ]]]')
    (processed / 'corrupt.json').write_text('not json at all')
    (blocked / (IMPL_ID + '.json')).write_text('\x00\x01 garbage {')
    (blocked / (IMPL_ID + '.retry.json')).write_text('also not json')
    sibs = rp.load_sibling_tasks(str(state_dir), oracle_task, ORACLE_ID)
    assert isinstance(sibs, list)
    sibs_missing = rp.load_sibling_tasks(str(tmp_path / 'no_such_state'), oracle_task, ORACLE_ID)
    assert isinstance(sibs_missing, list)

def test_regression_base_sibling_acceptance_unchanged(tmp_path):
    state_dir, tasks, processed, blocked = _build_state_tree(tmp_path)
    worktree = _build_worktree(tmp_path)
    oracle_task = _make_oracle_task()
    impl_task = _make_impl_task()
    _place_impl(tasks, impl_task)
    sibs = rp.load_sibling_tasks(str(state_dir), oracle_task, ORACLE_ID)
    assert isinstance(sibs, list)
    assert _has_impl(sibs)
    assert rp.is_fix_forward_redpair(oracle_task, str(worktree), sibs) is True

def test_regression_processed_sibling_acceptance_unchanged(tmp_path):
    state_dir, tasks, processed, blocked = _build_state_tree(tmp_path)
    worktree = _build_worktree(tmp_path)
    oracle_task = _make_oracle_task()
    impl_task = _make_impl_task()
    _place_impl(processed, impl_task)
    sibs = rp.load_sibling_tasks(str(state_dir), oracle_task, ORACLE_ID)
    assert isinstance(sibs, list)
    assert _has_impl(sibs)
    assert rp.is_fix_forward_redpair(oracle_task, str(worktree), sibs) is True