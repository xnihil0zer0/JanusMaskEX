"""RED oracle for the fix-forward red-pair acceptance predicate.

This is a standalone ``test_authoring`` oracle pinning the contract of the
not-yet-existing pure helper ``harness.redpair_acceptance.is_fix_forward_redpair``
and the thin impure reader ``harness.redpair_acceptance.load_sibling_tasks``.

It is RED-by-absence on HEAD: ``harness.redpair_acceptance`` does not exist, so
the top-level import raises ``ModuleNotFoundError`` and the entire file fails to
collect. Once the separate ``redpair-predicate-impl`` brief lands the module the
file turns GREEN.

The predicate is the existing-module complement of the orchestrator's
``_new_module_red_by_absence`` gate, mirroring the keystone file-keyed red-pair
predicate in ``harness/planner/plan_normalizer.py``: a sibling impl task counts
only when its ``verification_command`` substring-contains one of the oracle's own
``files_touched`` AND its ``files_touched`` contains ``mt.replace('.', '/') + '.py'``.
"""
import json
from pathlib import Path
from harness.redpair_acceptance import is_fix_forward_redpair, load_sibling_tasks

def _make_target_module(root: Path, dotted: str='pkg.mod') -> Path:
    """Create the existing-module file ``<root>/<mt-as-path>.py`` and return it."""
    rel = dotted.replace('.', '/') + '.py'
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('# target module under test\n')
    return path

def _valid_task() -> dict:
    return {'meta_task_type': 'test_authoring', 'mutation_target': 'pkg.mod', 'files_touched': ['tests/x/test_mod.py']}

def _valid_impl() -> dict:
    return {'meta_task_type': 'harness_self_fix', 'files_touched': ['pkg/mod.py'], 'verification_command': 'python -m pytest tests/x/test_mod.py -q'}

def _make_processed_dir(state_dir: Path) -> Path:
    processed = state_dir / 'tasks' / 'processed'
    processed.mkdir(parents=True, exist_ok=True)
    return processed

def test_import_red_by_absence_module_not_found():
    import importlib
    module = importlib.import_module('harness.redpair_acceptance')
    assert callable(getattr(module, 'is_fix_forward_redpair', None))
    assert callable(getattr(module, 'load_sibling_tasks', None))

def test_p1_valid_red_pair_returns_true(tmp_path):
    _make_target_module(tmp_path)
    task = _valid_task()
    impl = _valid_impl()
    assert is_fix_forward_redpair(task, tmp_path, [impl]) is True

def test_p2_wrong_verifier_returns_false(tmp_path):
    _make_target_module(tmp_path)
    task = _valid_task()
    impl = _valid_impl()
    impl['verification_command'] = 'python -m pytest tests/x/test_other.py -q'
    assert is_fix_forward_redpair(task, tmp_path, [impl]) is False

def test_p2b_impl_does_not_touch_target_returns_false(tmp_path):
    _make_target_module(tmp_path)
    task = _valid_task()
    impl = _valid_impl()
    impl['files_touched'] = ['pkg/other.py']
    assert is_fix_forward_redpair(task, tmp_path, [impl]) is False

def test_p3_no_impl_sibling_empty_returns_false(tmp_path):
    _make_target_module(tmp_path)
    assert is_fix_forward_redpair(_valid_task(), tmp_path, []) is False

def test_p3_sibling_is_test_authoring_not_impl_returns_false(tmp_path):
    _make_target_module(tmp_path)
    task = _valid_task()
    impl = _valid_impl()
    impl['meta_task_type'] = 'test_authoring'
    assert is_fix_forward_redpair(task, tmp_path, [impl]) is False

def test_p3_task_own_meta_not_test_authoring_returns_false(tmp_path):
    _make_target_module(tmp_path)
    task = _valid_task()
    task['meta_task_type'] = 'harness_self_fix'
    assert is_fix_forward_redpair(task, tmp_path, [_valid_impl()]) is False

def test_p4_module_absent_returns_false(tmp_path):
    assert is_fix_forward_redpair(_valid_task(), tmp_path, [_valid_impl()]) is False

def test_p5_malformed_mutation_target_path_returns_false(tmp_path):
    _make_target_module(tmp_path)
    task = _valid_task()
    task['mutation_target'] = 'pkg/mod.py'
    assert is_fix_forward_redpair(task, tmp_path, [_valid_impl()]) is False

def test_p5_malformed_mutation_target_dotdot_empty_none_pysuffix_returns_false(tmp_path):
    _make_target_module(tmp_path)
    for bad in ['..pkg', '', None, 'pkg.mod.py']:
        task = _valid_task()
        task['mutation_target'] = bad
        assert is_fix_forward_redpair(task, tmp_path, [_valid_impl()]) is False

def test_p5_garbage_task_and_sibling_tasks_returns_false_no_raise(tmp_path):
    _make_target_module(tmp_path)
    assert is_fix_forward_redpair({}, tmp_path, [None, 3]) is False
    assert is_fix_forward_redpair(None, tmp_path, [_valid_impl()]) is False
    assert is_fix_forward_redpair(3, tmp_path, []) is False
    assert is_fix_forward_redpair(_valid_task(), tmp_path, [None, 3]) is False

def test_load_sibling_tasks_reads_dependency_dict(tmp_path):
    processed = _make_processed_dir(tmp_path)
    dep = {'task_id': 'dep1', 'meta_task_type': 'harness_self_fix'}
    (processed / 'dep1.json').write_text(json.dumps(dep))
    task = {'dependencies': ['dep1']}
    result = load_sibling_tasks(tmp_path, task, 'main')
    assert isinstance(result, list)
    assert any((isinstance(d, dict) and d.get('task_id') == 'dep1' for d in result))

def test_load_sibling_tasks_reads_reverse_dependency(tmp_path):
    processed = _make_processed_dir(tmp_path)
    rev = {'task_id': 'rev1', 'dependencies': ['main']}
    (processed / 'rev1.json').write_text(json.dumps(rev))
    task = {'dependencies': []}
    result = load_sibling_tasks(tmp_path, task, 'main')
    assert isinstance(result, list)
    assert any((isinstance(d, dict) and d.get('task_id') == 'rev1' for d in result))

def test_load_sibling_tasks_skips_missing_and_corrupt_no_raise(tmp_path):
    processed = _make_processed_dir(tmp_path)
    good = {'task_id': 'good', 'meta_task_type': 'harness_self_fix'}
    (processed / 'good.json').write_text(json.dumps(good))
    (processed / 'corrupt.json').write_text('{not valid json')
    task = {'dependencies': ['good', 'missing', 'corrupt']}
    result = load_sibling_tasks(tmp_path, task, 'main')
    assert isinstance(result, list)
    assert any((isinstance(d, dict) and d.get('task_id') == 'good' for d in result))
    assert all((not (isinstance(d, dict) and d.get('task_id') == 'corrupt') for d in result))