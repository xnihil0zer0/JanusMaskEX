"""Oracle: verify task_decomposer propagates files_touched and mutation_target to subtasks."""
from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import sys
import pytest

def load_decomposer():
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
    decomposer_path = repo_root / 'harness' / 'task_decomposer.py'
    spec = importlib.util.spec_from_file_location('task_decomposer_under_test', str(decomposer_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
td = load_decomposer()
decompose_task = td.decompose_task
enqueue_subtasks = td.enqueue_subtasks
FuzzFailure = td.FuzzFailure

def _make_failure(FuzzFailure, input_args=None, reason='general'):
    if input_args is None:
        input_args = [5, 10]
    return FuzzFailure(input_args=input_args, input_kwargs={}, result_a='result_a', result_b='result_b', reason=reason)

def test_propagation_in_memory_and_on_disk(tmp_path):
    parent = {'task_id': 'parent-newmod', 'files_touched': ['harness/brand_new_mod.py'], 'mutation_target': 'harness.brand_new_mod', 'specification': 'Implement a brand new module', 'meta_task_type': 'data_model'}
    failures = [_make_failure(FuzzFailure, input_args=[[]]), _make_failure(FuzzFailure, input_args=[0])]
    config = {'decomposition': {'max_subtasks': 5, 'max_depth': 3}}
    result = decompose_task(parent, failures, config, depth=0)
    assert len(result.subtasks) > 0
    for st in result.subtasks:
        assert st.files_touched == ['harness/brand_new_mod.py']
        assert st.mutation_target == 'harness.brand_new_mod'
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
    failures = [_make_failure(FuzzFailure, input_args=[[]]), _make_failure(FuzzFailure, input_args=[0])]
    config = {'decomposition': {'max_subtasks': 5, 'max_depth': 3}}
    result = decompose_task(parent, failures, config, depth=0)
    assert len(result.subtasks) > 0
    for st in result.subtasks:
        assert st.files_touched is None
        assert st.mutation_target is None
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
    failures = [_make_failure(FuzzFailure, input_args=[[]]), _make_failure(FuzzFailure, input_args=[0])]
    config = {'decomposition': {'max_subtasks': 5, 'max_depth': 3}}
    result = decompose_task(parent, failures, config, depth=0)
    assert len(result.subtasks) > 0
    for st in result.subtasks:
        assert st.files_touched == ['harness/brand_new_mod.py']
        assert st.mutation_target is None
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
    failures = [_make_failure(FuzzFailure, input_args=[[]]), _make_failure(FuzzFailure, input_args=[0])]
    config = {'decomposition': {'max_subtasks': 5, 'max_depth': 3}}
    result = decompose_task(parent, failures, config, depth=0)
    assert len(result.subtasks) > 0
    for st in result.subtasks:
        assert st.files_touched is None
        assert st.mutation_target == 'harness.brand_new_mod'
    enqueue_subtasks(result.subtasks, tmp_path)
    for st in result.subtasks:
        task_json_path = tmp_path / 'tasks' / f'{st.task_id}.json'
        assert task_json_path.exists()
        with open(task_json_path, 'r') as f:
            data = json.load(f)
        assert 'files_touched' not in data
        assert data.get('mutation_target') == 'harness.brand_new_mod'

def test_propagation_fuzz_failures_classify():
    _classify_failures = td._classify_failures
    f_empty = _make_failure(FuzzFailure, input_args=[[]])
    res = _classify_failures([f_empty])
    assert 'empty_input' in res
    assert res['empty_input'] == [f_empty]
    f_single = _make_failure(FuzzFailure, input_args=[[1]])
    res = _classify_failures([f_single])
    assert 'single_element' in res
    assert res['single_element'] == [f_single]
    f_boundary = _make_failure(FuzzFailure, input_args=[0])
    res = _classify_failures([f_boundary])
    assert 'boundary' in res
    assert res['boundary'] == [f_boundary]
    f_type = _make_failure(FuzzFailure, input_args=[1, 2], reason='exception_mismatch')
    res = _classify_failures([f_type])
    assert 'type_error' in res
    assert res['type_error'] == [f_type]
    f_general = _make_failure(FuzzFailure, input_args=[[1, 2, 3]])
    res = _classify_failures([f_general])
    assert 'general' in res
    assert res['general'] == [f_general]

def test_propagation_custom_depth_retry(tmp_path):
    parent = {'task_id': 'parent-retry', 'files_touched': ['harness/brand_new_mod.py'], 'mutation_target': 'harness.brand_new_mod', 'specification': 'Specification text'}
    failures = []
    config = {'decomposition': {'max_subtasks': 5, 'max_depth': 3}}
    result = decompose_task(parent, failures, config, depth=1)
    assert result.strategy == 'retry'
    assert len(result.subtasks) == 1
    for st in result.subtasks:
        assert st.files_touched == ['harness/brand_new_mod.py']
        assert st.mutation_target == 'harness.brand_new_mod'
    enqueue_subtasks(result.subtasks, tmp_path)
    for st in result.subtasks:
        task_json_path = tmp_path / 'tasks' / f'{st.task_id}.json'
        assert task_json_path.exists()
        with open(task_json_path, 'r') as f:
            data = json.load(f)
        assert data.get('files_touched') == ['harness/brand_new_mod.py']
        assert data.get('mutation_target') == 'harness.brand_new_mod'

def test_propagation_custom_depth_planner_review(tmp_path):
    parent = {'task_id': 'parent-planner-review', 'files_touched': ['harness/brand_new_mod.py'], 'mutation_target': 'harness.brand_new_mod', 'specification': 'Specification text'}
    failures = [_make_failure(FuzzFailure, input_args=[[]])]
    config = {'decomposition': {'max_subtasks': 5, 'max_depth': 3}}
    result = decompose_task(parent, failures, config, depth=3)
    assert result.strategy == 'planner_review'
    assert len(result.subtasks) == 1
    for st in result.subtasks:
        assert st.files_touched == ['harness/brand_new_mod.py']
        assert st.mutation_target == 'harness.brand_new_mod'
    enqueue_subtasks(result.subtasks, tmp_path)
    for st in result.subtasks:
        task_json_path = tmp_path / 'tasks' / f'{st.task_id}.json'
        assert task_json_path.exists()
        with open(task_json_path, 'r') as f:
            data = json.load(f)
        assert data.get('files_touched') == ['harness/brand_new_mod.py']
        assert data.get('mutation_target') == 'harness.brand_new_mod'

def test_propagation_function_split(tmp_path):
    parent = {'task_id': 'parent-func-split', 'files_touched': ['harness/brand_new_mod.py'], 'mutation_target': 'harness.brand_new_mod', 'specification': 'Specification text'}
    failures = [_make_failure(FuzzFailure, input_args=[[]])]
    code_a = '\ndef process_data(x):\n    if x > 0:\n        return x\n    for item in range(x):\n        pass\n    return 0\n'
    code_b = code_a
    config = {'decomposition': {'max_subtasks': 5, 'max_depth': 3}}
    result = decompose_task(parent, failures, config, code_a=code_a, code_b=code_b, depth=0)
    assert result.strategy == 'function_split'
    assert len(result.subtasks) >= 2
    for st in result.subtasks:
        assert st.files_touched == ['harness/brand_new_mod.py']
        assert st.mutation_target == 'harness.brand_new_mod'
    enqueue_subtasks(result.subtasks, tmp_path)
    for st in result.subtasks:
        task_json_path = tmp_path / 'tasks' / f'{st.task_id}.json'
        assert task_json_path.exists()
        with open(task_json_path, 'r') as f:
            data = json.load(f)
        assert data.get('files_touched') == ['harness/brand_new_mod.py']
        assert data.get('mutation_target') == 'harness.brand_new_mod'

def test_propagation_guard_fail_planner_review(tmp_path):
    parent = {'task_id': 'parent-guard-fail', 'files_touched': ['harness/brand_new_mod.py'], 'mutation_target': 'harness.brand_new_mod', 'specification': 'planner review initiated planner review initiated planner review initiated'}
    failures = [_make_failure(FuzzFailure, input_args=[[]])]
    config = {'decomposition': {'max_subtasks': 5, 'max_depth': 3}}
    result = decompose_task(parent, failures, config, depth=0)
    assert result.strategy == 'planner_review'
    assert len(result.subtasks) == 1
    for st in result.subtasks:
        assert st.files_touched == ['harness/brand_new_mod.py']
        assert st.mutation_target == 'harness.brand_new_mod'
    enqueue_subtasks(result.subtasks, tmp_path)
    for st in result.subtasks:
        task_json_path = tmp_path / 'tasks' / f'{st.task_id}.json'
        assert task_json_path.exists()
        with open(task_json_path, 'r') as f:
            data = json.load(f)
        assert data.get('files_touched') == ['harness/brand_new_mod.py']
        assert data.get('mutation_target') == 'harness.brand_new_mod'

def test_propagation_empty_values(tmp_path):
    parent = {'task_id': 'parent-empty-vals', 'files_touched': [], 'mutation_target': '', 'specification': 'Specification text'}
    failures = [_make_failure(FuzzFailure, input_args=[[]]), _make_failure(FuzzFailure, input_args=[0])]
    config = {'decomposition': {'max_subtasks': 5, 'max_depth': 3}}
    result = decompose_task(parent, failures, config, depth=0)
    assert len(result.subtasks) > 0
    for st in result.subtasks:
        assert st.files_touched == []
        assert st.mutation_target == ''
    enqueue_subtasks(result.subtasks, tmp_path)
    for st in result.subtasks:
        task_json_path = tmp_path / 'tasks' / f'{st.task_id}.json'
        assert task_json_path.exists()
        with open(task_json_path, 'r') as f:
            data = json.load(f)
        assert data.get('files_touched') == []
        assert data.get('mutation_target') == ''

def test_propagation_none_values(tmp_path):
    parent = {'task_id': 'parent-none-vals', 'files_touched': None, 'mutation_target': None, 'specification': 'Specification text'}
    failures = [_make_failure(FuzzFailure, input_args=[[]]), _make_failure(FuzzFailure, input_args=[0])]
    config = {'decomposition': {'max_subtasks': 5, 'max_depth': 3}}
    result = decompose_task(parent, failures, config, depth=0)
    assert len(result.subtasks) > 0
    for st in result.subtasks:
        assert st.files_touched is None
        assert st.mutation_target is None
    enqueue_subtasks(result.subtasks, tmp_path)
    for st in result.subtasks:
        task_json_path = tmp_path / 'tasks' / f'{st.task_id}.json'
        assert task_json_path.exists()
        with open(task_json_path, 'r') as f:
            data = json.load(f)
        assert 'files_touched' not in data
        assert 'mutation_target' not in data