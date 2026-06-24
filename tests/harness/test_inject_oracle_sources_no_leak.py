import os
from pathlib import Path
from typing import Any, Dict
import pytest
from harness.planner.plan_normalizer import _inject_oracle_sources

def run_injection(tmp_path: Path, test_file_content: str, verification_command: str='pytest test_file.py') -> str:
    test_file_path = tmp_path / 'test_file.py'
    test_file_path.write_text(test_file_content, encoding='utf-8')
    plan = {'tasks': [{'task_id': 'impl_task', 'meta_task_type': 'impl', 'spec': {'implementation_notes': 'Existing notes.'}, 'verification_command': f'python -m {verification_command}'}]}
    normalized = _inject_oracle_sources(plan, tmp_path)
    notes = normalized['tasks'][0]['spec']['implementation_notes']
    return notes

def test_normalizer_decorator_literal_redaction(tmp_path):
    source = '\n@decorator_name("secret_string", 42, b"secret_bytes")\ndef target_function():\n    pass\n'
    notes = run_injection(tmp_path, source)
    assert 'secret_string' not in notes
    assert '42' not in notes
    assert 'secret_bytes' not in notes
    assert "@decorator_name('...', '...', '...')" in notes

def test_normalizer_decorator_signature_preserved(tmp_path):
    source = '\n@decorator_name("secret")\ndef target_function(a: int, b: str = "default") -> bool:\n    pass\n'
    notes = run_injection(tmp_path, source)
    assert 'target_function' in notes
    assert 'decorator_name' in notes
    assert 'def target_function(a: int, b: str = ...)' in notes
    assert '-> bool' in notes

def test_normalizer_class_keyword_literal_redaction(tmp_path):
    source = '\nclass MyClass(metaclass=SomeMeta, secret_str="key", secret_num=123, secret_bytes=b"bytes"):\n    pass\n'
    notes = run_injection(tmp_path, source)
    assert 'key' not in notes
    assert '123' not in notes
    assert 'bytes' not in notes
    assert "class MyClass(metaclass=SomeMeta, secret_str='...', secret_num='...', secret_bytes='...'):" in notes

def test_normalizer_class_name_preserved(tmp_path):
    source = '\nclass MyClass(BaseClass):\n    def method(self):\n        pass\n'
    notes = run_injection(tmp_path, source)
    assert 'class MyClass(BaseClass):' in notes
    assert 'def method(self):' in notes

def test_normalizer_control_assert_absent(tmp_path):
    source = '\ndef func():\n    assert "secret_body" == "other"\n'
    notes = run_injection(tmp_path, source)
    assert 'assert' not in notes
    assert 'secret_body' not in notes

def test_normalizer_default_arg_absent(tmp_path):
    source = '\ndef func(a="sentinel_default", b=10):\n    pass\n'
    notes = run_injection(tmp_path, source)
    assert 'sentinel_default' not in notes
    assert '10' not in notes
    assert 'def func(a = ..., b = ...):' in notes

def test_normalizer_committed_oracle_contract_block_injected(tmp_path):
    source = 'def test_foo(): pass'
    test_file_path = tmp_path / 'test_file.py'
    test_file_path.write_text(source, encoding='utf-8')
    plan = {'tasks': [{'task_id': 'impl_task', 'meta_task_type': 'impl', 'spec': {'implementation_notes': 'Initial implementation notes.'}, 'verification_command': 'python -m pytest test_file.py'}]}
    normalized = _inject_oracle_sources(plan, tmp_path)
    notes = normalized['tasks'][0]['spec']['implementation_notes']
    assert 'COMMITTED ORACLE CONTRACT' in notes
    assert 'Initial implementation notes.' in notes

def test_normalizer_idempotency(tmp_path):
    source = 'def test_foo(): pass'
    test_file_path = tmp_path / 'test_file.py'
    test_file_path.write_text(source, encoding='utf-8')
    plan = {'tasks': [{'task_id': 'impl_task', 'meta_task_type': 'impl', 'spec': {'implementation_notes': 'Initial implementation notes.'}, 'verification_command': 'python -m pytest test_file.py'}]}
    normalized1 = _inject_oracle_sources(plan, tmp_path)
    notes1 = normalized1['tasks'][0]['spec']['implementation_notes']
    normalized2 = _inject_oracle_sources(normalized1, tmp_path)
    notes2 = normalized2['tasks'][0]['spec']['implementation_notes']
    assert notes1 == notes2
    assert notes2.count('COMMITTED ORACLE CONTRACT') == 1

def test_normalizer_multiple_decorators_and_classes(tmp_path):
    source = '\n@dec1("s1")\n@dec2(9.9)\nclass Outer:\n    @dec3(b"s3")\n    def inner_func(self):\n        pass\n\n    class Inner:\n        pass\n'
    notes = run_injection(tmp_path, source)
    assert "@dec1('...')" in notes
    assert "@dec2('...')" in notes
    assert "@dec3('...')" in notes
    assert 'class Outer:' in notes
    assert 'class Inner:' in notes
    assert 'def inner_func(self):' in notes

def test_normalizer_decorator_complex_expressions(tmp_path):
    source = '\n@dec(nested_call("secret_nested", x=123), "outer_secret", a + b, some_var)\ndef func():\n    pass\n'
    notes = run_injection(tmp_path, source)
    assert 'secret_nested' not in notes
    assert 'outer_secret' not in notes
    assert '123' not in notes
    assert "@dec(nested_call('...', x='...'), '...', a + b, some_var)" in notes

def test_normalizer_decorator_binop_with_literal(tmp_path):
    source = '\n@dec(a + 1, "secret" + b)\ndef func():\n    pass\n'
    notes = run_injection(tmp_path, source)
    assert 'secret' not in notes
    assert '1' not in notes
    assert "@dec(a + '...', '...' + b)" in notes

def test_normalizer_decorator_string_redaction_variants(tmp_path):
    source = '\n@dec(r"secret_raw", \'\'\'secret_triple\'\'\')\ndef func():\n    pass\n'
    notes = run_injection(tmp_path, source)
    assert 'secret_raw' not in notes
    assert 'secret_triple' not in notes
    assert "@dec('...', '...')" in notes

def test_normalizer_no_op_for_empty_verification_command(tmp_path):
    plan = {'tasks': [{'task_id': 'impl_task', 'meta_task_type': 'impl', 'spec': {'implementation_notes': 'Notes'}, 'verification_command': ''}]}
    normalized = _inject_oracle_sources(plan, tmp_path)
    assert normalized == plan

def test_normalizer_no_op_for_test_authoring_tasks(tmp_path):
    source = 'def test_foo(): pass'
    test_file_path = tmp_path / 'test_file.py'
    test_file_path.write_text(source, encoding='utf-8')
    plan = {'tasks': [{'task_id': 'oracle_task', 'meta_task_type': 'test_authoring', 'spec': {'implementation_notes': 'Notes'}, 'verification_command': 'python -m pytest test_file.py'}]}
    normalized = _inject_oracle_sources(plan, tmp_path)
    assert normalized['tasks'][0]['spec']['implementation_notes'] == 'Notes'

def test_normalizer_no_op_when_repo_root_none():
    plan = {'tasks': [{'task_id': 'impl_task', 'meta_task_type': 'impl', 'spec': {'implementation_notes': 'Notes'}, 'verification_command': 'python -m pytest test_file.py'}]}
    normalized = _inject_oracle_sources(plan, None)
    assert normalized == plan

def test_normalizer_missing_oracle_file_ignored(tmp_path):
    plan = {'tasks': [{'task_id': 'impl_task', 'meta_task_type': 'impl', 'spec': {'implementation_notes': 'Notes'}, 'verification_command': 'python -m pytest non_existent_file.py'}]}
    normalized = _inject_oracle_sources(plan, tmp_path)
    assert normalized['tasks'][0]['spec']['implementation_notes'] == 'Notes'

def test_normalizer_non_string_numeric_bytes_preserved(tmp_path):
    source = '\n@dec(True, False, None)\nclass C(flag=True, other=None):\n    pass\n'
    notes = run_injection(tmp_path, source)
    assert '@dec(True, False, None)' in notes
    assert 'class C(flag=True, other=None):' in notes