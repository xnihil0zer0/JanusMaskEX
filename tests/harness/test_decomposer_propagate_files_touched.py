import importlib.util
from pathlib import Path
import sys
import json
import pytest
import shutil
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
from harness.diff_fuzzer import FuzzFailure

def get_decomposer():
    decomposer_path = repo_root / 'harness' / 'task_decomposer.py'
    spec = importlib.util.spec_from_file_location('harness.task_decomposer', str(decomposer_path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
task_decomposer = get_decomposer()

def assert_propagation_keys(subtask, expected_files, expected_mutation):
    if hasattr(subtask, 'files_touched'):
        actual_files = subtask.files_touched
    elif isinstance(subtask.constraints, dict) and 'files_touched' in subtask.constraints:
        actual_files = subtask.constraints['files_touched']
    else:
        raise AttributeError("Subtask does not carry 'files_touched' in attributes or constraints")
    assert actual_files == expected_files, f'Expected files_touched {expected_files}, got {actual_files}'
    if hasattr(subtask, 'mutation_target'):
        actual_mutation = subtask.mutation_target
    elif isinstance(subtask.constraints, dict) and 'mutation_target' in subtask.constraints:
        actual_mutation = subtask.constraints['mutation_target']
    else:
        raise AttributeError("Subtask does not carry 'mutation_target' in attributes or constraints")
    assert actual_mutation == expected_mutation, f'Expected mutation_target {expected_mutation}, got {actual_mutation}'

def assert_no_propagation_keys(subtask):
    if hasattr(subtask, 'files_touched'):
        assert subtask.files_touched in (None, [], '')
    if hasattr(subtask, 'mutation_target'):
        assert subtask.mutation_target in (None, '')
    if isinstance(subtask.constraints, dict):
        assert 'files_touched' not in subtask.constraints or subtask.constraints['files_touched'] in (None, [], '')
        assert 'mutation_target' not in subtask.constraints or subtask.constraints['mutation_target'] in (None, '')

def assert_keys_absent_in_json(task_data):
    assert 'files_touched' not in task_data
    assert 'mutation_target' not in task_data

def test_propagate_files_touched_in_memory():
    parent_task = {'task_id': 'parent-edge-case-in-memory', 'specification': 'Decompose this task.', 'files_touched': ['harness/brand_new_mod.py'], 'mutation_target': 'harness.brand_new_mod'}
    f1 = FuzzFailure(input_args=[[]], input_kwargs={}, result_a='a', result_b='b', reason='general')
    f2 = FuzzFailure(input_args=[0], input_kwargs={}, result_a='a', result_b='b', reason='general')
    failures = [f1, f2]
    config = {'decomposition': {'max_subtasks': 5, 'max_depth': 3}}
    result = task_decomposer.decompose_task(parent_task, failures, config, depth=0)
    assert result.strategy == 'edge_case'
    assert len(result.subtasks) >= 2
    for subtask in result.subtasks:
        assert_propagation_keys(subtask, ['harness/brand_new_mod.py'], 'harness.brand_new_mod')

def test_propagate_files_touched_on_disk(tmp_path):
    parent_task = {'task_id': 'parent-edge-case-on-disk', 'specification': 'Decompose this task.', 'files_touched': ['harness/brand_new_mod.py'], 'mutation_target': 'harness.brand_new_mod'}
    f1 = FuzzFailure(input_args=[[]], input_kwargs={}, result_a='a', result_b='b', reason='general')
    f2 = FuzzFailure(input_args=[0], input_kwargs={}, result_a='a', result_b='b', reason='general')
    failures = [f1, f2]
    config = {'decomposition': {'max_subtasks': 5, 'max_depth': 3}}
    result = task_decomposer.decompose_task(parent_task, failures, config, depth=0)
    assert len(result.subtasks) >= 2
    task_decomposer.enqueue_subtasks(result.subtasks, tmp_path)
    for subtask in result.subtasks:
        json_path = tmp_path / 'tasks' / f'{subtask.task_id}.json'
        assert json_path.is_file()
        with open(json_path) as f:
            data = json.load(f)
        assert data.get('files_touched') == ['harness/brand_new_mod.py']
        assert data.get('mutation_target') == 'harness.brand_new_mod'

def test_regression_no_propagation_keys_in_memory():
    parent_task = {'task_id': 'parent-regression-in-memory', 'specification': 'Decompose this task.'}
    f1 = FuzzFailure(input_args=[[]], input_kwargs={}, result_a='a', result_b='b', reason='general')
    f2 = FuzzFailure(input_args=[0], input_kwargs={}, result_a='a', result_b='b', reason='general')
    failures = [f1, f2]
    config = {'decomposition': {'max_subtasks': 5, 'max_depth': 3}}
    result = task_decomposer.decompose_task(parent_task, failures, config, depth=0)
    assert len(result.subtasks) >= 2
    for subtask in result.subtasks:
        assert_no_propagation_keys(subtask)

def test_regression_no_propagation_keys_on_disk(tmp_path):
    parent_task = {'task_id': 'parent-regression-on-disk', 'specification': 'Decompose this task.'}
    f1 = FuzzFailure(input_args=[[]], input_kwargs={}, result_a='a', result_b='b', reason='general')
    f2 = FuzzFailure(input_args=[0], input_kwargs={}, result_a='a', result_b='b', reason='general')
    failures = [f1, f2]
    config = {'decomposition': {'max_subtasks': 5, 'max_depth': 3}}
    result = task_decomposer.decompose_task(parent_task, failures, config, depth=0)
    assert len(result.subtasks) >= 2
    task_decomposer.enqueue_subtasks(result.subtasks, tmp_path)
    for subtask in result.subtasks:
        json_path = tmp_path / 'tasks' / f'{subtask.task_id}.json'
        assert json_path.is_file()
        with open(json_path) as f:
            data = json.load(f)
        assert_keys_absent_in_json(data)

def test_propagate_files_touched_custom_depth_retry(tmp_path):
    parent_task = {'task_id': 'parent-retry-custom-depth', 'specification': 'Decompose this task.', 'files_touched': ['harness/brand_new_mod.py'], 'mutation_target': 'harness.brand_new_mod'}
    failures = []
    config = {'decomposition': {'max_subtasks': 5, 'max_depth': 3}}
    result = task_decomposer.decompose_task(parent_task, failures, config, depth=1)
    assert result.strategy == 'retry'
    assert len(result.subtasks) == 1
    for subtask in result.subtasks:
        assert_propagation_keys(subtask, ['harness/brand_new_mod.py'], 'harness.brand_new_mod')
    task_decomposer.enqueue_subtasks(result.subtasks, tmp_path)
    for subtask in result.subtasks:
        json_path = tmp_path / 'tasks' / f'{subtask.task_id}.json'
        assert json_path.is_file()
        with open(json_path) as f:
            data = json.load(f)
        assert data.get('files_touched') == ['harness/brand_new_mod.py']
        assert data.get('mutation_target') == 'harness.brand_new_mod'

def test_propagate_files_touched_custom_depth_planner_review(tmp_path):
    parent_task = {'task_id': 'parent-planner-review-custom-depth', 'specification': 'Decompose this task.', 'files_touched': ['harness/brand_new_mod.py'], 'mutation_target': 'harness.brand_new_mod'}
    failures = [FuzzFailure(input_args=[[]], input_kwargs={}, result_a='a', result_b='b', reason='general')]
    config = {'decomposition': {'max_subtasks': 5, 'max_depth': 3}}
    result = task_decomposer.decompose_task(parent_task, failures, config, depth=3)
    assert result.strategy == 'planner_review'
    assert len(result.subtasks) == 1
    for subtask in result.subtasks:
        assert_propagation_keys(subtask, ['harness/brand_new_mod.py'], 'harness.brand_new_mod')
    task_decomposer.enqueue_subtasks(result.subtasks, tmp_path)
    for subtask in result.subtasks:
        json_path = tmp_path / 'tasks' / f'{subtask.task_id}.json'
        assert json_path.is_file()
        with open(json_path) as f:
            data = json.load(f)
        assert data.get('files_touched') == ['harness/brand_new_mod.py']
        assert data.get('mutation_target') == 'harness.brand_new_mod'

def test_propagate_files_touched_function_split(tmp_path):
    parent_task = {'task_id': 'parent-function-split', 'specification': 'Decompose this task.', 'files_touched': ['harness/brand_new_mod.py'], 'mutation_target': 'harness.brand_new_mod'}
    f1 = FuzzFailure(input_args=[[]], input_kwargs={}, result_a='a', result_b='b', reason='general')
    failures = [f1]
    code_a = '\ndef process_data(x):\n    if x > 0:\n        return x\n    for item in range(x):\n        pass\n    return 0\n'
    code_b = code_a
    config = {'decomposition': {'max_subtasks': 5, 'max_depth': 3}}
    result = task_decomposer.decompose_task(parent_task, failures, config, code_a=code_a, code_b=code_b, depth=0)
    assert result.strategy == 'function_split'
    assert len(result.subtasks) >= 2
    for subtask in result.subtasks:
        assert_propagation_keys(subtask, ['harness/brand_new_mod.py'], 'harness.brand_new_mod')
    task_decomposer.enqueue_subtasks(result.subtasks, tmp_path)
    for subtask in result.subtasks:
        json_path = tmp_path / 'tasks' / f'{subtask.task_id}.json'
        assert json_path.is_file()
        with open(json_path) as f:
            data = json.load(f)
        assert data.get('files_touched') == ['harness/brand_new_mod.py']
        assert data.get('mutation_target') == 'harness.brand_new_mod'

def test_propagate_files_touched_guard_fail_planner_review(tmp_path):
    parent_task = {'task_id': 'parent-guard-fail', 'specification': 'planner review initiated planner review initiated planner review initiated', 'files_touched': ['harness/brand_new_mod.py'], 'mutation_target': 'harness.brand_new_mod'}
    failures = [FuzzFailure(input_args=[[]], input_kwargs={}, result_a='a', result_b='b', reason='general')]
    config = {'decomposition': {'max_subtasks': 5, 'max_depth': 3}}
    result = task_decomposer.decompose_task(parent_task, failures, config, depth=0)
    assert result.strategy == 'planner_review'
    assert len(result.subtasks) == 1
    for subtask in result.subtasks:
        assert_propagation_keys(subtask, ['harness/brand_new_mod.py'], 'harness.brand_new_mod')
    task_decomposer.enqueue_subtasks(result.subtasks, tmp_path)
    for subtask in result.subtasks:
        json_path = tmp_path / 'tasks' / f'{subtask.task_id}.json'
        assert json_path.is_file()
        with open(json_path) as f:
            data = json.load(f)
        assert data.get('files_touched') == ['harness/brand_new_mod.py']
        assert data.get('mutation_target') == 'harness.brand_new_mod'

def test_propagate_files_touched_empty_values(tmp_path):
    parent_task = {'task_id': 'parent-empty-values', 'specification': 'Decompose this task.', 'files_touched': [], 'mutation_target': ''}
    f1 = FuzzFailure(input_args=[[]], input_kwargs={}, result_a='a', result_b='b', reason='general')
    f2 = FuzzFailure(input_args=[0], input_kwargs={}, result_a='a', result_b='b', reason='general')
    failures = [f1, f2]
    config = {'decomposition': {'max_subtasks': 5, 'max_depth': 3}}
    result = task_decomposer.decompose_task(parent_task, failures, config, depth=0)
    assert len(result.subtasks) >= 2
    for subtask in result.subtasks:
        assert_propagation_keys(subtask, [], '')
    task_decomposer.enqueue_subtasks(result.subtasks, tmp_path)
    for subtask in result.subtasks:
        json_path = tmp_path / 'tasks' / f'{subtask.task_id}.json'
        assert json_path.is_file()
        with open(json_path) as f:
            data = json.load(f)
        assert data.get('files_touched') == []
        assert data.get('mutation_target') == ''

def test_propagate_files_touched_none_values(tmp_path):
    parent_task = {'task_id': 'parent-none-values', 'specification': 'Decompose this task.', 'files_touched': None, 'mutation_target': None}
    f1 = FuzzFailure(input_args=[[]], input_kwargs={}, result_a='a', result_b='b', reason='general')
    f2 = FuzzFailure(input_args=[0], input_kwargs={}, result_a='a', result_b='b', reason='general')
    failures = [f1, f2]
    config = {'decomposition': {'max_subtasks': 5, 'max_depth': 3}}
    result = task_decomposer.decompose_task(parent_task, failures, config, depth=0)
    assert len(result.subtasks) >= 2
    for subtask in result.subtasks:
        assert_no_propagation_keys(subtask)
    task_decomposer.enqueue_subtasks(result.subtasks, tmp_path)
    for subtask in result.subtasks:
        json_path = tmp_path / 'tasks' / f'{subtask.task_id}.json'
        assert json_path.is_file()
        with open(json_path) as f:
            data = json.load(f)
        assert_keys_absent_in_json(data)

def test_propagate_files_touched_only_one_key(tmp_path):
    parent_task_1 = {'task_id': 'parent-only-files', 'specification': 'Decompose this task.', 'files_touched': ['harness/brand_new_mod.py']}
    parent_task_2 = {'task_id': 'parent-only-mutation', 'specification': 'Decompose this task.', 'mutation_target': 'harness.brand_new_mod'}
    f1 = FuzzFailure(input_args=[[]], input_kwargs={}, result_a='a', result_b='b', reason='general')
    f2 = FuzzFailure(input_args=[0], input_kwargs={}, result_a='a', result_b='b', reason='general')
    failures = [f1, f2]
    config = {'decomposition': {'max_subtasks': 5, 'max_depth': 3}}
    result1 = task_decomposer.decompose_task(parent_task_1, failures, config, depth=0)
    for subtask in result1.subtasks:
        actual_files = getattr(subtask, 'files_touched', None)
        if actual_files is None and isinstance(subtask.constraints, dict):
            actual_files = subtask.constraints.get('files_touched')
        assert actual_files == ['harness/brand_new_mod.py']
        actual_mutation = getattr(subtask, 'mutation_target', None)
        if actual_mutation is None and isinstance(subtask.constraints, dict):
            actual_mutation = subtask.constraints.get('mutation_target')
        assert actual_mutation in (None, '')
    result2 = task_decomposer.decompose_task(parent_task_2, failures, config, depth=0)
    for subtask in result2.subtasks:
        actual_files = getattr(subtask, 'files_touched', None)
        if actual_files is None and isinstance(subtask.constraints, dict):
            actual_files = subtask.constraints.get('files_touched')
        assert actual_files in (None, [], '')
        actual_mutation = getattr(subtask, 'mutation_target', None)
        if actual_mutation is None and isinstance(subtask.constraints, dict):
            actual_mutation = subtask.constraints.get('mutation_target')
        assert actual_mutation == 'harness.brand_new_mod'
    task_decomposer.enqueue_subtasks(result1.subtasks, tmp_path)
    for subtask in result1.subtasks:
        json_path = tmp_path / 'tasks' / f'{subtask.task_id}.json'
        assert json_path.is_file()
        with open(json_path) as f:
            data = json.load(f)
        assert data.get('files_touched') == ['harness/brand_new_mod.py']
        assert 'mutation_target' not in data
    shutil.rmtree(tmp_path / 'tasks')
    task_decomposer.enqueue_subtasks(result2.subtasks, tmp_path)
    for subtask in result2.subtasks:
        json_path = tmp_path / 'tasks' / f'{subtask.task_id}.json'
        assert json_path.is_file()
        with open(json_path) as f:
            data = json.load(f)
        assert 'files_touched' not in data
        assert data.get('mutation_target') == 'harness.brand_new_mod'