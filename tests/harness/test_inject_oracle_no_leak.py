from __future__ import annotations
import pathlib
import pytest
from typing import Any, Dict
from harness.planner.plan_normalizer import _inject_oracle_sources

def _write_fixture_oracle_1(root_path: pathlib.Path, rel_path: str) -> None:
    p = root_path / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    content = '# Complex multi-line oracle file\nimport os\nimport sys\nfrom functools import wraps\n\ndef my_decorator(func):\n    @wraps(func)\n    def wrapper(*args, **kwargs):\n        return func(*args, **kwargs)\n    return wrapper\n\n@my_decorator\nclass TargetClassHelper:\n    def method_one(\n        self,\n        x: int,\n        y: int,\n    ) -> int:\n        return x + y\n\n@my_decorator\ndef target_helper_func(\n    a: int,\n    b: int,\n) -> int:\n    result_value = "SECRET_EXPECTED_VALUE_XYZ"\n    assert (\n        result_value\n        == "SECRET_EXPECTED_VALUE_XYZ"\n    )\n    return a + b\n'
    p.write_text(content, encoding='utf-8')

def _write_fixture_oracle_2(root_path: pathlib.Path, rel_path: str) -> None:
    p = root_path / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    content = '# Simple oracle file\nimport pytest\n\nclass AnotherClass:\n    pass\n\ndef another_func():\n    secret = "OTHER_EXPECTED_VALUE"\n    assert secret == "OTHER_EXPECTED_VALUE"\n'
    p.write_text(content, encoding='utf-8')

def test_no_verbatim_assert_leaks(tmp_path: pathlib.Path) -> None:
    rel_path_1 = 'tests/harness/fixture_oracle_1.py'
    rel_path_2 = 'tests/harness/fixture_oracle_2.py'
    _write_fixture_oracle_1(tmp_path, rel_path_1)
    _write_fixture_oracle_2(tmp_path, rel_path_2)
    plan = {'tasks': [{'task_id': 'task_1', 'meta_task_type': 'data_model', 'verification_command': f'python -m pytest {rel_path_1} {rel_path_2} -q', 'spec': {'implementation_notes': 'Initial implementation notes.'}}]}
    res = _inject_oracle_sources(plan, tmp_path)
    notes = res['tasks'][0]['spec']['implementation_notes']
    assert 'result_value' not in notes or '== "SECRET_EXPECTED_VALUE_XYZ"' not in notes
    assert 'assert secret == "OTHER_EXPECTED_VALUE"' not in notes
    assert 'SECRET_EXPECTED_VALUE_XYZ' not in notes
    assert 'OTHER_EXPECTED_VALUE' not in notes

def test_summary_references_names_and_path(tmp_path: pathlib.Path) -> None:
    rel_path_1 = 'tests/harness/fixture_oracle_1.py'
    rel_path_2 = 'tests/harness/fixture_oracle_2.py'
    _write_fixture_oracle_1(tmp_path, rel_path_1)
    _write_fixture_oracle_2(tmp_path, rel_path_2)
    plan = {'tasks': [{'task_id': 'task_1', 'meta_task_type': 'data_model', 'verification_command': f'python -m pytest {rel_path_1} {rel_path_2} -q', 'spec': {'implementation_notes': 'Initial implementation notes.'}}]}
    res = _inject_oracle_sources(plan, tmp_path)
    notes = res['tasks'][0]['spec']['implementation_notes']
    assert rel_path_1 in notes
    assert rel_path_2 in notes
    assert 'TargetClassHelper' in notes
    assert 'target_helper_func' in notes
    assert 'AnotherClass' in notes
    assert 'another_func' in notes

def test_inject_oracle_idempotent(tmp_path: pathlib.Path) -> None:
    rel_path_1 = 'tests/harness/fixture_oracle_1.py'
    _write_fixture_oracle_1(tmp_path, rel_path_1)
    plan = {'tasks': [{'task_id': 'task_1', 'meta_task_type': 'data_model', 'verification_command': f'python -m pytest {rel_path_1} -q', 'spec': {'implementation_notes': 'Initial implementation notes.'}}]}
    first = _inject_oracle_sources(plan, tmp_path)
    second = _inject_oracle_sources(first, tmp_path)
    assert first == second

def test_inject_oracle_pre_existing_notes(tmp_path: pathlib.Path) -> None:
    rel_path_1 = 'tests/harness/fixture_oracle_1.py'
    _write_fixture_oracle_1(tmp_path, rel_path_1)
    plan = {'tasks': [{'task_id': 'task_1', 'meta_task_type': 'data_model', 'verification_command': f'python -m pytest {rel_path_1} -q', 'spec': {'implementation_notes': 'Initial implementation notes.'}}]}
    res = _inject_oracle_sources(plan, tmp_path)
    notes = res['tasks'][0]['spec']['implementation_notes']
    assert notes.startswith('Initial implementation notes.')
    assert rel_path_1 in notes
if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-x', '-q']))