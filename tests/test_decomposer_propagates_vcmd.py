from __future__ import annotations
import json
from pathlib import Path
import pytest
from harness.task_decomposer import decompose_task, enqueue_subtasks, Subtask
from harness.diff_fuzzer import FuzzFailure
from harness.planner.taxonomies import SIDE_EFFECT_META_TYPES

def test_planner_review_propagation(tmp_path):
    """Test 1: builds a parent task with verification_command='python -m pytest some_oracle.py -q',
    depth=3, implementation meta_task_type, and files_touched=['ngv2/x.py'],
    calls decompose_task with depth=3, enqueues the resulting subtasks via enqueue_subtasks
    into a temporary directory, and asserts that the subtask JSON carries the verification_command.
    """
    parent_task = {'task_id': 'parent_task_1', 'verification_command': 'python -m pytest some_oracle.py -q', 'meta_task_type': 'implementation', 'files_touched': ['ngv2/x.py'], 'specification': 'Implement some feature'}
    failures = []
    config = {'decomposition': {'max_subtasks': 5, 'max_depth': 3}}
    result = decompose_task(parent_task, failures, config, depth=3)
    enqueue_subtasks(result.subtasks, tmp_path)
    tasks_dir = tmp_path / 'tasks'
    assert tasks_dir.exists()
    subtask_files = list(tasks_dir.glob('*.json'))
    assert len(subtask_files) == 1
    with open(subtask_files[0], 'r') as f:
        subtask_data = json.load(f)
    assert subtask_data.get('verification_command') == 'python -m pytest some_oracle.py -q'

def test_edge_case_propagation(tmp_path):
    """Test 2: asserts edge-case strategy propagation:
    builds a parent task with verification_command, multiple FuzzFailures, depth=0,
    enqueues subtasks, and asserts that every emitted subtask JSON carries the parent verification_command.
    """
    parent_task = {'task_id': 'parent_task_2', 'verification_command': 'python -m pytest tests/test_decomposer_propagates_vcmd.py -q', 'meta_task_type': 'implementation', 'specification': 'Process some collection'}
    failures = [FuzzFailure(input_args=[[]], input_kwargs={}, result_a='a', result_b='b', reason='general'), FuzzFailure(input_args=[[1]], input_kwargs={}, result_a='a', result_b='b', reason='general')]
    config = {'decomposition': {'max_subtasks': 5, 'max_depth': 3}}
    result = decompose_task(parent_task, failures, config, depth=0)
    assert result.strategy == 'edge_case'
    assert len(result.subtasks) > 1
    enqueue_subtasks(result.subtasks, tmp_path)
    tasks_dir = tmp_path / 'tasks'
    assert tasks_dir.exists()
    subtask_files = list(tasks_dir.glob('*.json'))
    assert len(subtask_files) == len(result.subtasks)
    for subtask_file in subtask_files:
        with open(subtask_file, 'r') as f:
            subtask_data = json.load(f)
        assert subtask_data.get('verification_command') == 'python -m pytest tests/test_decomposer_propagates_vcmd.py -q'

def test_none_propagation(tmp_path):
    """Test 3: parent task with verification_command is None, empty, or missing
    verifies that none of the enqueued subtasks have verification_command set.
    """
    parent_task = {'task_id': 'parent_task_none', 'meta_task_type': 'implementation', 'specification': 'Do something without vcmd'}
    failures = [FuzzFailure(input_args=[[]], input_kwargs={}, result_a='a', result_b='b', reason='general'), FuzzFailure(input_args=[[1]], input_kwargs={}, result_a='a', result_b='b', reason='general')]
    config = {'decomposition': {'max_subtasks': 5, 'max_depth': 3}}
    result = decompose_task(parent_task, failures, config, depth=0)
    enqueue_subtasks(result.subtasks, tmp_path)
    tasks_dir = tmp_path / 'tasks'
    subtask_files = list(tasks_dir.glob('*.json'))
    assert len(subtask_files) > 0
    for subtask_file in subtask_files:
        with open(subtask_file, 'r') as f:
            subtask_data = json.load(f)
        assert subtask_data.get('verification_command') is None

def test_empty_verification_command_propagation(tmp_path):
    """Test 4: parent task with empty string verification_command
    verifies it propagates as empty string.
    """
    parent_task = {'task_id': 'parent_task_empty', 'verification_command': '', 'meta_task_type': 'implementation', 'specification': 'Do something with empty vcmd'}
    failures = [FuzzFailure(input_args=[[]], input_kwargs={}, result_a='a', result_b='b', reason='general'), FuzzFailure(input_args=[[1]], input_kwargs={}, result_a='a', result_b='b', reason='general')]
    config = {'decomposition': {'max_subtasks': 5, 'max_depth': 3}}
    result = decompose_task(parent_task, failures, config, depth=0)
    enqueue_subtasks(result.subtasks, tmp_path)
    tasks_dir = tmp_path / 'tasks'
    subtask_files = list(tasks_dir.glob('*.json'))
    assert len(subtask_files) > 0
    for subtask_file in subtask_files:
        with open(subtask_file, 'r') as f:
            subtask_data = json.load(f)
        assert subtask_data.get('verification_command') == ''

def test_function_split_propagation(tmp_path):
    """Test 5: function split strategy propagation
    verifies that verification_command is propagated in function split.
    """
    parent_task = {'task_id': 'parent_task_split', 'verification_command': 'pytest tests/test_decomposer_propagates_vcmd.py', 'meta_task_type': 'implementation', 'specification': 'Split this function'}
    failures = [FuzzFailure(input_args=[[]], input_kwargs={}, result_a='a', result_b='b', reason='general')]
    code_a = '\ndef my_func(x):\n    if x > 0:\n        pass\n    for i in range(x):\n        pass\n    return x\n'
    config = {'decomposition': {'max_subtasks': 5, 'max_depth': 3}}
    result = decompose_task(parent_task, failures, config, code_a=code_a, code_b=code_a, depth=0)
    assert result.strategy == 'function_split'
    enqueue_subtasks(result.subtasks, tmp_path)
    tasks_dir = tmp_path / 'tasks'
    subtask_files = list(tasks_dir.glob('*.json'))
    assert len(subtask_files) > 0
    for subtask_file in subtask_files:
        with open(subtask_file, 'r') as f:
            subtask_data = json.load(f)
        assert subtask_data.get('verification_command') == 'pytest tests/test_decomposer_propagates_vcmd.py'

def test_retry_propagation(tmp_path):
    """Test 6: retry strategy propagation
    verifies that verification_command is propagated in retry fallback.
    """
    parent_task = {'task_id': 'parent_task_retry', 'verification_command': 'pytest tests/test_decomposer_propagates_vcmd.py', 'meta_task_type': 'implementation', 'specification': 'Retry this'}
    failures = []
    config = {'decomposition': {'max_subtasks': 5, 'max_depth': 3}}
    result = decompose_task(parent_task, failures, config, depth=0)
    assert result.strategy == 'retry'
    enqueue_subtasks(result.subtasks, tmp_path)
    tasks_dir = tmp_path / 'tasks'
    subtask_files = list(tasks_dir.glob('*.json'))
    assert len(subtask_files) == 1
    with open(subtask_files[0], 'r') as f:
        subtask_data = json.load(f)
    assert subtask_data.get('verification_command') == 'pytest tests/test_decomposer_propagates_vcmd.py'

def test_guard_fail_planner_review_propagation(tmp_path):
    """Test 7: guard-fail planner review path
    verifies verification_command is propagated.
    """
    parent_task = {'task_id': 'parent_task_guard_fail', 'verification_command': 'pytest tests/test_decomposer_propagates_vcmd.py', 'meta_task_type': 'implementation', 'specification': 'Guard fail path'}
    failures = [FuzzFailure(input_args=[[]], input_kwargs={}, result_a='a', result_b='b', reason='general')]
    config = {'decomposition': {'max_subtasks': 5, 'max_depth': 3}}
    result = decompose_task(parent_task, failures, config, depth=1)
    assert result.strategy == 'planner_review'
    enqueue_subtasks(result.subtasks, tmp_path)
    tasks_dir = tmp_path / 'tasks'
    subtask_files = list(tasks_dir.glob('*.json'))
    assert len(subtask_files) == 1
    with open(subtask_files[0], 'r') as f:
        subtask_data = json.load(f)
    assert subtask_data.get('verification_command') == 'pytest tests/test_decomposer_propagates_vcmd.py'

def test_side_effect_heavy_propagation(tmp_path):
    """Test 8: side-effect-heavy task category triggers guard failure and routes to planner review,
    verifying verification_command is propagated.
    """
    assert len(SIDE_EFFECT_META_TYPES) > 0
    side_effect_type = list(SIDE_EFFECT_META_TYPES)[0]
    parent_task = {'task_id': 'parent_task_side_effect', 'verification_command': 'pytest tests/test_decomposer_propagates_vcmd.py', 'meta_task_type': side_effect_type, 'specification': 'Side effect task'}
    failures = [FuzzFailure(input_args=[[]], input_kwargs={}, result_a='a', result_b='b', reason='general'), FuzzFailure(input_args=[[1]], input_kwargs={}, result_a='a', result_b='b', reason='general')]
    config = {'decomposition': {'max_subtasks': 5, 'max_depth': 3}}
    result = decompose_task(parent_task, failures, config, depth=0)
    assert result.strategy == 'planner_review'
    enqueue_subtasks(result.subtasks, tmp_path)
    tasks_dir = tmp_path / 'tasks'
    subtask_files = list(tasks_dir.glob('*.json'))
    assert len(subtask_files) == 1
    with open(subtask_files[0], 'r') as f:
        subtask_data = json.load(f)
    assert subtask_data.get('verification_command') == 'pytest tests/test_decomposer_propagates_vcmd.py'

def test_custom_config_propagation(tmp_path):
    """Test 9: custom decomposition max_depth configuration
    verifies propagation at custom limits.
    """
    parent_task = {'task_id': 'parent_task_custom_depth', 'verification_command': 'pytest tests/test_decomposer_propagates_vcmd.py', 'meta_task_type': 'implementation', 'specification': 'Custom depth test'}
    failures = [FuzzFailure(input_args=[[]], input_kwargs={}, result_a='a', result_b='b', reason='general')]
    config = {'decomposition': {'max_subtasks': 5, 'max_depth': 1}}
    result = decompose_task(parent_task, failures, config, depth=1)
    assert result.strategy == 'planner_review'
    enqueue_subtasks(result.subtasks, tmp_path)
    tasks_dir = tmp_path / 'tasks'
    subtask_files = list(tasks_dir.glob('*.json'))
    assert len(subtask_files) == 1
    with open(subtask_files[0], 'r') as f:
        subtask_data = json.load(f)
    assert subtask_data.get('verification_command') == 'pytest tests/test_decomposer_propagates_vcmd.py'

def test_missing_meta_task_type_propagation(tmp_path):
    """Test 10: missing meta_task_type in parent task
    verifies that verification_command is still propagated.
    """
    parent_task = {'task_id': 'parent_task_no_mtt', 'verification_command': 'pytest tests/test_decomposer_propagates_vcmd.py', 'specification': 'No meta task type'}
    failures = [FuzzFailure(input_args=[[]], input_kwargs={}, result_a='a', result_b='b', reason='general'), FuzzFailure(input_args=[[1]], input_kwargs={}, result_a='a', result_b='b', reason='general')]
    config = {'decomposition': {'max_subtasks': 5, 'max_depth': 3}}
    result = decompose_task(parent_task, failures, config, depth=0)
    enqueue_subtasks(result.subtasks, tmp_path)
    tasks_dir = tmp_path / 'tasks'
    subtask_files = list(tasks_dir.glob('*.json'))
    assert len(subtask_files) > 0
    for subtask_file in subtask_files:
        with open(subtask_file, 'r') as f:
            subtask_data = json.load(f)
        assert subtask_data.get('verification_command') == 'pytest tests/test_decomposer_propagates_vcmd.py'

def test_no_constraints_propagation(tmp_path):
    """Test 11: parent task with no constraints dictionary
    verifies verification_command propagates successfully.
    """
    parent_task = {'task_id': 'parent_task_no_constraints', 'verification_command': 'pytest tests/test_decomposer_propagates_vcmd.py', 'meta_task_type': 'implementation', 'specification': 'No constraints task'}
    failures = [FuzzFailure(input_args=[[]], input_kwargs={}, result_a='a', result_b='b', reason='general'), FuzzFailure(input_args=[[1]], input_kwargs={}, result_a='a', result_b='b', reason='general')]
    config = {'decomposition': {'max_subtasks': 5, 'max_depth': 3}}
    result = decompose_task(parent_task, failures, config, depth=0)
    enqueue_subtasks(result.subtasks, tmp_path)
    tasks_dir = tmp_path / 'tasks'
    subtask_files = list(tasks_dir.glob('*.json'))
    assert len(subtask_files) > 0
    for subtask_file in subtask_files:
        with open(subtask_file, 'r') as f:
            subtask_data = json.load(f)
        assert subtask_data.get('verification_command') == 'pytest tests/test_decomposer_propagates_vcmd.py'