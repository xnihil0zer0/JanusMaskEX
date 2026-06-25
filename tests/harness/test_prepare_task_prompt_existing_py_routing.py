"""
RED behavioral oracle for prepare_task_prompt routing.
Asserts correct routing of single-existing-py validation tasks.
"""
from typing import Any
import pytest
from harness.orchestrator import prepare_task_prompt
from harness.planner.taxonomies import BYPASS_FUZZER_TYPES

def test_validation_single_existing_py_gets_patches_block(tmp_path):
    task = {'task_id': 'test_val_single_py', 'meta_task_type': 'validation', 'files_touched': ['foo.py'], 'working_dir': str(tmp_path)}
    (tmp_path / 'foo.py').write_text('def f(): pass')
    prompt = prepare_task_prompt(task)
    assert 'PARTIAL-EDIT DISPATCH' in prompt
    assert '__JANUSMASK_PATCHES__' in prompt

def test_test_authoring_single_existing_py_does_not_get_patches_block(tmp_path):
    task = {'task_id': 'test_auth_single_py', 'meta_task_type': 'test_authoring', 'files_touched': ['foo.py'], 'working_dir': str(tmp_path)}
    (tmp_path / 'foo.py').write_text('def f(): pass')
    prompt = prepare_task_prompt(task)
    assert '__JANUSMASK_PATCHES__' not in prompt
    assert 'TEST-AUTHORING DISPATCH' in prompt

def test_validation_absent_py_does_not_get_patches_block(tmp_path):
    task = {'task_id': 'test_val_absent_py', 'meta_task_type': 'validation', 'files_touched': ['absent.py'], 'working_dir': str(tmp_path)}
    prompt = prepare_task_prompt(task)
    assert '__JANUSMASK_PATCHES__' not in prompt

def test_validation_multi_file_gets_manifest_block(tmp_path):
    task = {'task_id': 'test_val_multi_py', 'meta_task_type': 'validation', 'files_touched': ['foo.py', 'bar.py'], 'working_dir': str(tmp_path)}
    (tmp_path / 'foo.py').write_text('def f(): pass')
    (tmp_path / 'bar.py').write_text('def g(): pass')
    prompt = prepare_task_prompt(task)
    assert '__JANUSMASK_MANIFEST__' in prompt
    assert '__JANUSMASK_PATCHES__' not in prompt

def test_validation_non_py_single_file_does_not_get_patches_block(tmp_path):
    task = {'task_id': 'test_val_non_py', 'meta_task_type': 'validation', 'files_touched': ['foo.txt'], 'working_dir': str(tmp_path)}
    (tmp_path / 'foo.txt').write_text('hello')
    prompt = prepare_task_prompt(task)
    assert '__JANUSMASK_PATCHES__' not in prompt

def test_pre_existing_partial_edit_flag_preserved(tmp_path):
    task = {'task_id': 'test_pe_flag', 'meta_task_type': 'validation', 'files_touched': ['foo.py'], 'working_dir': str(tmp_path), 'partial_edit': True}
    (tmp_path / 'foo.py').write_text('def f(): pass')
    prompt = prepare_task_prompt(task)
    assert '__JANUSMASK_PATCHES__' in prompt

def test_pre_existing_bypass_fuzzer_type_preserved(tmp_path):
    bypass_type = list(BYPASS_FUZZER_TYPES)[0] if BYPASS_FUZZER_TYPES else 'config_schema'
    task = {'task_id': 'test_bypass_type', 'meta_task_type': bypass_type, 'files_touched': ['foo.py'], 'working_dir': str(tmp_path)}
    (tmp_path / 'foo.py').write_text('def f(): pass')
    prompt = prepare_task_prompt(task)
    assert '__JANUSMASK_PATCHES__' in prompt

def test_determinism_of_prepare_task_prompt(tmp_path):
    task = {'task_id': 'test_det', 'meta_task_type': 'validation', 'files_touched': ['foo.py'], 'working_dir': str(tmp_path)}
    (tmp_path / 'foo.py').write_text('def f(): pass')
    prompt1 = prepare_task_prompt(task)
    prompt2 = prepare_task_prompt(task)
    assert prompt1 == prompt2

def test_regression_non_py_multi_file_gets_manifest_block(tmp_path):
    task = {'task_id': 'test_reg_non_py_multi', 'meta_task_type': 'validation', 'files_touched': ['foo.txt', 'bar.txt'], 'working_dir': str(tmp_path)}
    (tmp_path / 'foo.txt').write_text('hello')
    (tmp_path / 'bar.txt').write_text('world')
    prompt = prepare_task_prompt(task)
    assert '__JANUSMASK_MANIFEST__' in prompt
    assert '__JANUSMASK_PATCHES__' not in prompt

def test_regression_empty_files_touched_does_not_raise(tmp_path):
    for files_val in ([], None, 'not_a_list', 123):
        task = {'task_id': 'test_reg_empty', 'meta_task_type': 'validation', 'files_touched': files_val, 'working_dir': str(tmp_path)}
        prompt = prepare_task_prompt(task)
        assert '__JANUSMASK_PATCHES__' not in prompt