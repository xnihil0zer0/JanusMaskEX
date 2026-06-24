from __future__ import annotations
import pytest
from harness.diff_fuzzer import fuzz_from_task, _patched_symbol_candidates, FuzzResult

def test_divergent_patched_bodies_are_fuzzed_and_caught():
    manifest_a = "\n__JANUSMASK_PATCHES__ = [\n    {\n        'file': 'harness/diff_fuzzer.py',\n        'kind': 'symbol',\n        'name': 'add_offsets',\n        'code': 'def add_offsets(x: int, y: int) -> int:\\n    return x + y\\n'\n    }\n]\n"
    manifest_b = "\n__JANUSMASK_PATCHES__ = [\n    {\n        'file': 'harness/diff_fuzzer.py',\n        'kind': 'symbol',\n        'name': 'add_offsets',\n        'code': 'def add_offsets(x: int, y: int) -> int:\\n    return x - y\\n'\n    }\n]\n"
    cfg = {'fuzzing': {'function_level_inputs': 32, 'float_tolerance': 1e-09, 'seed': 42}, 'batch_execution': {'enabled': False}}
    task = {'task_id': 't_divergent', 'meta_task_type': 'harness_self_fix', 'constraints': {}}
    res = fuzz_from_task(manifest_a, manifest_b, task, cfg)
    assert isinstance(res, FuzzResult)
    assert res.equivalent is False
    assert res.total_inputs > 0
    assert res.error is None

def test_equivalent_patched_bodies_pass():
    manifest_a = "\n__JANUSMASK_PATCHES__ = [\n    {\n        'file': 'harness/diff_fuzzer.py',\n        'kind': 'symbol',\n        'name': 'add_offsets',\n        'code': 'def add_offsets(x: int, y: int) -> int:\\n    return x + y\\n'\n    }\n]\n"
    manifest_b = "\n__JANUSMASK_PATCHES__ = [\n    {\n        'file': 'harness/diff_fuzzer.py',\n        'kind': 'symbol',\n        'name': 'add_offsets',\n        'code': 'def add_offsets(x: int, y: int) -> int:\\n    return y + x\\n'\n    }\n]\n"
    cfg = {'fuzzing': {'function_level_inputs': 32, 'float_tolerance': 1e-09, 'seed': 42}, 'batch_execution': {'enabled': False}}
    task = {'task_id': 't_equivalent', 'meta_task_type': 'harness_self_fix', 'constraints': {}}
    res = fuzz_from_task(manifest_a, manifest_b, task, cfg)
    assert isinstance(res, FuzzResult)
    assert res.equivalent is True
    assert res.total_inputs > 0
    assert res.error is None

def test_identical_patched_bodies_skip_not_self_clone():
    manifest_a = "\n__JANUSMASK_PATCHES__ = [\n    {\n        'file': 'harness/diff_fuzzer.py',\n        'kind': 'symbol',\n        'name': 'add_offsets',\n        'code': 'def add_offsets(x: int, y: int) -> int:\\n    return x + y\\n'\n    }\n]\n"
    manifest_b_ast_equal = "\n__JANUSMASK_PATCHES__ = [\n    {\n        'file': 'harness/diff_fuzzer.py',\n        'kind': 'symbol',\n        'name': 'add_offsets',\n        'code': 'def add_offsets(x: int, y: int) -> int:\\n    # some comment\\n    return x + y\\n'\n    }\n]\n"
    assert _patched_symbol_candidates(manifest_a, manifest_a) is None
    assert _patched_symbol_candidates(manifest_a, manifest_b_ast_equal) is None
    cfg = {'fuzzing': {'function_level_inputs': 32, 'float_tolerance': 1e-09, 'seed': 42}, 'batch_execution': {'enabled': False}}
    task = {'task_id': 't_identical', 'meta_task_type': 'harness_self_fix', 'constraints': {}}
    res1 = fuzz_from_task(manifest_a, manifest_a, task, cfg)
    assert isinstance(res1, FuzzResult)
    assert res1.equivalent is True
    assert res1.skipped_reason is not None
    assert res1.error is None
    res2 = fuzz_from_task(manifest_a, manifest_b_ast_equal, task, cfg)
    assert isinstance(res2, FuzzResult)
    assert res2.equivalent is True
    assert res2.skipped_reason is not None
    assert res2.error is None

def test_non_patch_submission_unchanged():
    code_a = '\ndef solution(x: int) -> int:\n    return x + 1\n'
    code_b = '\ndef solution(x: int) -> int:\n    return x + 2\n'
    assert _patched_symbol_candidates(code_a, code_b) is None
    assert _patched_symbol_candidates(None, None) is None
    assert _patched_symbol_candidates('not python', 'def f(): pass') is None
    assert _patched_symbol_candidates('def f(): pass', None) is None
    assert _patched_symbol_candidates(None, 'def f(): pass') is None
    manifest_a = "\n__JANUSMASK_PATCHES__ = [\n    {\n        'file': 'harness/diff_fuzzer.py',\n        'kind': 'symbol',\n        'name': 'add_offsets',\n        'code': 'def add_offsets(x: int, y: int) -> int:\\n    return x + y\\n'\n    }\n]\n"
    manifest_b_one_sided = "\n__JANUSMASK_PATCHES__ = [\n    {\n        'file': 'harness/diff_fuzzer.py',\n        'kind': 'symbol',\n        'name': 'other_func',\n        'code': 'def other_func(x: int) -> int:\\n    return x\\n'\n    }\n]\n"
    assert _patched_symbol_candidates(manifest_a, manifest_b_one_sided) is None
    assert _patched_symbol_candidates(manifest_a, code_a) is None
    assert _patched_symbol_candidates(code_a, manifest_a) is None
    cfg = {'fuzzing': {'function_level_inputs': 32, 'float_tolerance': 1e-09, 'seed': 42}, 'batch_execution': {'enabled': False}}
    task = {'task_id': 't_non_patch', 'meta_task_type': 'harness_self_fix', 'constraints': {}}
    res = fuzz_from_task(code_a, code_b, task, cfg)
    assert isinstance(res, FuzzResult)
    assert res.equivalent is False
    assert res.total_inputs > 0
    assert res.error is None

def test_degenerate_guards():
    assert _patched_symbol_candidates(None, None) is None
    assert _patched_symbol_candidates('not python', 'def f(): pass') is None
    assert _patched_symbol_candidates('def f(): pass', None) is None
    assert _patched_symbol_candidates(None, 'def f(): pass') is None