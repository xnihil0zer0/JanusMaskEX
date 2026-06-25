"""
RED behavioral oracle for prepare_task_prompt partial-edit routing.
Asserts correct routing of harness_self_fix single-existing-py edits to the partial-edit patches prompt.

Non-goals:
- No integration: do not perform full-system or live orchestrator integrations, or PTY worker spawns.
"""
from typing import Any
import pytest
from harness.orchestrator import prepare_task_prompt
from harness.planner.taxonomies import BYPASS_FUZZER_TYPES

def test_harness_self_fix_single_existing_py_gets_patches_block(tmp_path):
    task = {'task_id': 'test_harness_self_fix_single_existing_py', 'meta_task_type': 'harness_self_fix', 'files_touched': ['foo.py'], 'working_dir': str(tmp_path)}
    target_file = tmp_path / 'foo.py'
    target_file.write_text('def my_func(): pass')
    prompt = prepare_task_prompt(task)
    assert '__JANUSMASK_PATCHES__' in prompt
    assert 'PARTIAL-EDIT DISPATCH' in prompt
    assert 'R-ANCHOR' in prompt

def test_multi_file_still_takes_manifest_path(tmp_path):
    task = {'task_id': 'test_multi_file', 'meta_task_type': 'harness_self_fix', 'files_touched': ['foo.py', 'bar.py'], 'working_dir': str(tmp_path)}
    (tmp_path / 'foo.py').write_text('x = 1')
    (tmp_path / 'bar.py').write_text('y = 2')
    prompt = prepare_task_prompt(task)
    assert '__JANUSMASK_MANIFEST__' in prompt
    assert '__JANUSMASK_PATCHES__' not in prompt

def test_brand_new_file_does_not_get_patches_block(tmp_path):
    task = {'task_id': 'test_brand_new', 'meta_task_type': 'harness_self_fix', 'files_touched': ['absent.py'], 'working_dir': str(tmp_path)}
    prompt = prepare_task_prompt(task)
    assert '__JANUSMASK_PATCHES__' not in prompt

def test_non_py_single_target_does_not_get_patches_block(tmp_path):
    task = {'task_id': 'test_non_py', 'meta_task_type': 'harness_self_fix', 'files_touched': ['foo.md'], 'working_dir': str(tmp_path)}
    (tmp_path / 'foo.md').write_text('# Markdown File')
    prompt = prepare_task_prompt(task)
    assert '__JANUSMASK_PATCHES__' not in prompt

def test_pre_existing_activation_preserved(tmp_path):
    task_pe = {'task_id': 'test_pe', 'meta_task_type': 'validation', 'files_touched': ['foo.py'], 'working_dir': str(tmp_path), 'partial_edit': True}
    (tmp_path / 'foo.py').write_text('x = 1')
    prompt_pe = prepare_task_prompt(task_pe)
    assert '__JANUSMASK_PATCHES__' in prompt_pe
    assert 'config_schema' in BYPASS_FUZZER_TYPES
    task_bypass = {'task_id': 'test_bypass', 'meta_task_type': 'config_schema', 'files_touched': ['foo.py'], 'working_dir': str(tmp_path)}
    prompt_bypass = prepare_task_prompt(task_bypass)
    assert '__JANUSMASK_PATCHES__' in prompt_bypass

def test_determinism_and_purity(tmp_path):
    task = {'task_id': 'test_det', 'meta_task_type': 'harness_self_fix', 'files_touched': ['foo.py'], 'working_dir': str(tmp_path), 'partial_edit': True}
    (tmp_path / 'foo.py').write_text('x = 1')
    prompt1 = prepare_task_prompt(task)
    prompt2 = prepare_task_prompt(task)
    assert prompt1 == prompt2