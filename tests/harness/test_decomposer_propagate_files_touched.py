"""Oracle: verify task_decomposer propagates files_touched and mutation_target to subtasks."""
from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import pytest
import sys
current_path = Path(__file__).resolve()
repo_root = None
for parent in [current_path] + list(current_path.parents):
    if (parent / 'harness' / 'task_decomposer.py').is_file():
        repo_root = parent
        break
if repo_root is None:
    repo_root = Path('.').resolve()
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

def load_decomposer():
    decomposer_path = repo_root / 'harness' / 'task_decomposer.py'
    spec = importlib.util.spec_from_file_location('harness.task_decomposer', str(decomposer_path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
td = load_decomposer()
decompose_task = td.decompose_task
enqueue_subtasks = td.enqueue_subtasks
FuzzFailure = td.FuzzFailure

def _make_failure(input_args=None, reason='return_mismatch'):
    if input_args is None:
        input_args = [5, 10]
    from harness.sandbox import ExecutionResult
    result_a = ExecutionResult(success=True, return_value=1, return_repr='1')
    result_b = ExecutionResult(success=True, return_value=2, return_repr='2')
    return FuzzFailure(input_args=input_args, input_kwargs={}, result_a=result_a, result_b=result_b, reason=reason)

def test_propagation_in_memory_and_on_disk(tmp_path):
    parent = {'task_id': 'parent-newmod', 'files_touched': ['harness/brand_new_mod.py'], 'mutation_target': 'harness.brand_new_mod', 'specification': 'Implement a brand new module', 'meta_task_type': 'data_model'}
    failures = [_make_failure(input_args=[[]]), _make_failure(input_args=[0])]
    config = {'decomposition': {'max_subtasks': 5, 'max_depth': 3}}
    result = decompose_task(parent, failures, config, depth=0)
    assert len(result.subtasks) > 0
    for st in result.subtasks:
        assert getattr(st, 'files_touched', None) == ['harness/brand_new_mod.py']
        assert getattr(st, 'mutation_target', None) == 'harness.brand_new_mod'
    enqueue_subtasks(result.subtasks, tmp_path)
    for st in result.subtasks:
        task_json_path = tmp_path / 'tasks' / f'{st.task_id}.json'
        assert task_json_path.exists()
        with open(task_json_path, 'r') as f:
            data = json.load(f)
        assert data.get('files_touched') == ['harness/brand_new_mod.py']
        assert data.get('mutation_target') == 'harness.brand_new_mod'

def test_propagation_regression_no_keys(tmp_path):
    parent = {'task_id': 'parent-legacy', 'specification': 'Perform some refactoring', 'meta_task_type': 'refactor'}
    failures = [_make_failure(input_args=[[]]), _make_failure(input_args=[0])]
    config = {'decomposition': {'max_subtasks': 5, 'max_depth': 3}}
    result = decompose_task(parent, failures, config, depth=0)
    assert len(result.subtasks) > 0
    for st in result.subtasks:
        assert getattr(st, 'files_touched', None) is None
        assert getattr(st, 'mutation_target', None) is None
    enqueue_subtasks(result.subtasks, tmp_path)
    for st in result.subtasks:
        task_json_path = tmp_path / 'tasks' / f'{st.task_id}.json'
        assert task_json_path.exists()
        with open(task_json_path, 'r') as f:
            data = json.load(f)
        assert 'files_touched' not in data
        assert 'mutation_target' not in data

def test_propagation_regression_only_files_touched(tmp_path):
    parent = {'task_id': 'parent-files-only', 'files_touched': ['harness/brand_new_mod.py'], 'specification': 'Specification text'}
    failures = [_make_failure(input_args=[[]]), _make_failure(input_args=[0])]
    config = {'decomposition': {'max_subtasks': 5, 'max_depth': 3}}
    result = decompose_task(parent, failures, config, depth=0)
    assert len(result.subtasks) > 0
    for st in result.subtasks:
        assert getattr(st, 'files_touched', None) == ['harness/brand_new_mod.py']
        assert getattr(st, 'mutation_target', None) is None
    enqueue_subtasks(result.subtasks, tmp_path)
    for st in result.subtasks:
        task_json_path = tmp_path / 'tasks' / f'{st.task_id}.json'
        assert task_json_path.exists()
        with open(task_json_path, 'r') as f:
            data = json.load(f)
        assert data.get('files_touched') == ['harness/brand_new_mod.py']
        assert 'mutation_target' not in data

def test_propagation_regression_only_mutation_target(tmp_path):
    parent = {'task_id': 'parent-mutation-only', 'mutation_target': 'harness.brand_new_mod', 'specification': 'Specification text'}
    failures = [_make_failure(input_args=[[]]), _make_failure(input_args=[0])]
    config = {'decomposition': {'max_subtasks': 5, 'max_depth': 3}}
    result = decompose_task(parent, failures, config, depth=0)
    assert len(result.subtasks) > 0
    for st in result.subtasks:
        assert getattr(st, 'files_touched', None) is None
        assert getattr(st, 'mutation_target', None) == 'harness.brand_new_mod'
    enqueue_subtasks(result.subtasks, tmp_path)
    for st in result.subtasks:
        task_json_path = tmp_path / 'tasks' / f'{st.task_id}.json'
        assert task_json_path.exists()
        with open(task_json_path, 'r') as f:
            data = json.load(f)
        assert 'files_touched' not in data
        assert data.get('mutation_target') == 'harness.brand_new_mod'

def test_propagation_fuzz_failures_classify():
    _classify_failures = getattr(td, '_classify_failures', None)
    assert _classify_failures is not None, '_classify_failures must exist in task_decomposer'
    f_empty = _make_failure(input_args=[[]], reason='general')
    f_single = _make_failure(input_args=[[1]], reason='general')
    f_boundary = _make_failure(input_args=[0], reason='general')
    f_type_error = _make_failure(input_args=[2, 3], reason='exception_mismatch')
    f_general = _make_failure(input_args=[2, 3], reason='general')
    failures = [f_empty, f_single, f_boundary, f_type_error, f_general]
    classified = _classify_failures(failures)
    assert f_empty in classified.get('empty_input', [])
    assert f_single in classified.get('single_element', [])
    assert f_boundary in classified.get('boundary', [])
    assert f_type_error in classified.get('type_error', [])
    assert f_general in classified.get('general', [])

def test_propagation_empty_values(tmp_path):
    parent = {'task_id': 'parent-empty-values', 'files_touched': [], 'mutation_target': '', 'specification': 'Test specification'}
    failures = [_make_failure(input_args=[[]]), _make_failure(input_args=[0])]
    config = {'decomposition': {'max_subtasks': 5, 'max_depth': 3}}
    result = decompose_task(parent, failures, config, depth=0)
    assert len(result.subtasks) > 0
    for st in result.subtasks:
        assert getattr(st, 'files_touched', None) == []
        assert getattr(st, 'mutation_target', None) == ''
    enqueue_subtasks(result.subtasks, tmp_path)
    for st in result.subtasks:
        task_json_path = tmp_path / 'tasks' / f'{st.task_id}.json'
        assert task_json_path.exists()
        with open(task_json_path, 'r') as f:
            data = json.load(f)
        assert data.get('files_touched') == []
        assert data.get('mutation_target') == ''

def test_propagation_none_values(tmp_path):
    parent = {'task_id': 'parent-none-values', 'files_touched': None, 'mutation_target': None, 'specification': 'Test specification'}
    failures = [_make_failure(input_args=[[]]), _make_failure(input_args=[0])]
    config = {'decomposition': {'max_subtasks': 5, 'max_depth': 3}}
    result = decompose_task(parent, failures, config, depth=0)
    assert len(result.subtasks) > 0
    for st in result.subtasks:
        assert getattr(st, 'files_touched', None) is None
        assert getattr(st, 'mutation_target', None) is None
    enqueue_subtasks(result.subtasks, tmp_path)
    for st in result.subtasks:
        task_json_path = tmp_path / 'tasks' / f'{st.task_id}.json'
        assert task_json_path.exists()
        with open(task_json_path, 'r') as f:
            data = json.load(f)
        assert 'files_touched' not in data
        assert 'mutation_target' not in data

def test_propagation_custom_depth_retry(tmp_path):
    parent = {'task_id': 'parent-retry', 'files_touched': ['harness/brand_new_mod.py'], 'mutation_target': 'harness.brand_new_mod', 'specification': 'Test specification'}
    failures = []
    config = {'decomposition': {'max_subtasks': 5, 'max_depth': 3}}
    result = decompose_task(parent, failures, config, depth=1)
    assert result.strategy == 'retry'
    assert len(result.subtasks) == 1
    for st in result.subtasks:
        assert getattr(st, 'files_touched', None) == ['harness/brand_new_mod.py']
        assert getattr(st, 'mutation_target', None) == 'harness.brand_new_mod'
    enqueue_subtasks(result.subtasks, tmp_path)
    for st in result.subtasks:
        task_json_path = tmp_path / 'tasks' / f'{st.task_id}.json'
        assert task_json_path.exists()
        with open(task_json_path, 'r') as f:
            data = json.load(f)
        assert data.get('files_touched') == ['harness/brand_new_mod.py']
        assert data.get('mutation_target') == 'harness.brand_new_mod'

def test_propagation_custom_depth_planner_review(tmp_path):
    parent = {'task_id': 'parent-planner-review', 'files_touched': ['harness/brand_new_mod.py'], 'mutation_target': 'harness.brand_new_mod', 'specification': 'Test specification'}
    failures = [_make_failure(input_args=[[]])]
    config = {'decomposition': {'max_subtasks': 5, 'max_depth': 3}}
    result = decompose_task(parent, failures, config, depth=3)
    assert result.strategy == 'planner_review'
    assert len(result.subtasks) == 1
    for st in result.subtasks:
        assert getattr(st, 'files_touched', None) == ['harness/brand_new_mod.py']
        assert getattr(st, 'mutation_target', None) == 'harness.brand_new_mod'
    enqueue_subtasks(result.subtasks, tmp_path)
    for st in result.subtasks:
        task_json_path = tmp_path / 'tasks' / f'{st.task_id}.json'
        assert task_json_path.exists()
        with open(task_json_path, 'r') as f:
            data = json.load(f)
        assert data.get('files_touched') == ['harness/brand_new_mod.py']
        assert data.get('mutation_target') == 'harness.brand_new_mod'

def test_propagation_function_split(tmp_path):
    parent = {'task_id': 'parent-function-split', 'files_touched': ['harness/brand_new_mod.py'], 'mutation_target': 'harness.brand_new_mod', 'specification': 'Test specification'}
    failures = [_make_failure(input_args=[[1, 2]])]
    code_a = '\ndef process_data(x):\n    if x > 0:\n        return x\n    for item in range(x):\n        pass\n    return 0\n'
    code_b = code_a
    config = {'decomposition': {'max_subtasks': 5, 'max_depth': 3}}
    result = decompose_task(parent, failures, config, code_a=code_a, code_b=code_b, depth=0)
    assert result.strategy == 'function_split'
    assert len(result.subtasks) >= 2
    for st in result.subtasks:
        assert getattr(st, 'files_touched', None) == ['harness/brand_new_mod.py']
        assert getattr(st, 'mutation_target', None) == 'harness.brand_new_mod'
    enqueue_subtasks(result.subtasks, tmp_path)
    for st in result.subtasks:
        task_json_path = tmp_path / 'tasks' / f'{st.task_id}.json'
        assert task_json_path.exists()
        with open(task_json_path, 'r') as f:
            data = json.load(f)
        assert data.get('files_touched') == ['harness/brand_new_mod.py']
        assert data.get('mutation_target') == 'harness.brand_new_mod'

def test_propagation_guard_fail_planner_review(tmp_path):
    parent = {'task_id': 'parent-guard-fail', 'files_touched': ['harness/brand_new_mod.py'], 'mutation_target': 'harness.brand_new_mod', 'specification': 'Test specification', 'meta_task_type': 'sandbox_infra'}
    failures = [_make_failure(input_args=[[]]), _make_failure(input_args=[0])]
    config = {'decomposition': {'max_subtasks': 5, 'max_depth': 3}}
    result = decompose_task(parent, failures, config, depth=0)
    assert result.strategy == 'planner_review'
    assert len(result.subtasks) == 1
    for st in result.subtasks:
        assert getattr(st, 'files_touched', None) == ['harness/brand_new_mod.py']
        assert getattr(st, 'mutation_target', None) == 'harness.brand_new_mod'
    enqueue_subtasks(result.subtasks, tmp_path)
    for st in result.subtasks:
        task_json_path = tmp_path / 'tasks' / f'{st.task_id}.json'
        assert task_json_path.exists()
        with open(task_json_path, 'r') as f:
            data = json.load(f)
        assert data.get('files_touched') == ['harness/brand_new_mod.py']
        assert data.get('mutation_target') == 'harness.brand_new_mod'

def test_propagation_invalid_types_behavior(tmp_path):
    parent = {'task_id': 'parent-invalid', 'files_touched': 'not-a-list', 'mutation_target': 12345, 'specification': 'Test specification'}
    failures = [_make_failure(input_args=[[]]), _make_failure(input_args=[0])]
    config = {'decomposition': {'max_subtasks': 5, 'max_depth': 3}}
    result = decompose_task(parent, failures, config, depth=0)
    assert len(result.subtasks) > 0
    for st in result.subtasks:
        assert getattr(st, 'files_touched', None) == 'not-a-list'
        assert getattr(st, 'mutation_target', None) == 12345
    enqueue_subtasks(result.subtasks, tmp_path)
    for st in result.subtasks:
        task_json_path = tmp_path / 'tasks' / f'{st.task_id}.json'
        assert task_json_path.exists()
        with open(task_json_path, 'r') as f:
            data = json.load(f)
        assert data.get('files_touched') == 'not-a-list'
        assert data.get('mutation_target') == 12345