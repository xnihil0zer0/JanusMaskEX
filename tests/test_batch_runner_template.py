import ast
import json
import os
import py_compile
import subprocess
import sys
import tempfile
import textwrap

import pytest
from hypothesis import given, settings, strategies as st

from harness.sandbox import _BATCH_RUNNER_TEMPLATE

def test_template_is_compilable_python():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(_BATCH_RUNNER_TEMPLATE)
        tmp_path = f.name
    try:
        py_compile.compile(tmp_path, doraise=True)
    finally:
        os.unlink(tmp_path)

def run_template(payload):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f_script:
        f_script.write(_BATCH_RUNNER_TEMPLATE)
        script_path = f_script.name

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f_payload:
        json.dump(payload, f_payload)
        payload_path = f_payload.name

    try:
        result = subprocess.run(
            [sys.executable, script_path, payload_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        return result
    finally:
        os.unlink(script_path)
        os.unlink(payload_path)

def test_template_compile_once_semantic():
    code = textwrap.dedent("""
    counter = 0
    def inc():
        global counter
        counter += 1
        return counter
    """)
    payload = {
        "code": code,
        "func_name": "inc",
        "inputs": [{"args": [], "kwargs": {}} for _ in range(5)]
    }
    result = run_template(payload)
    assert result.returncode == 0
    lines = [line for line in result.stdout.strip().split("\n") if line]
    assert len(lines) == 5
    for line in lines:
        record = json.loads(line)
        assert record["success"] is True
        assert record["return_value"] == 1

def test_compile_failure_emits_one_error_per_input():
    code = "def f(x)  # Syntax Error"
    payload = {
        "code": code,
        "func_name": "f",
        "inputs": [{"args": [i], "kwargs": {}} for i in range(3)]
    }
    result = run_template(payload)
    assert result.returncode == 0
    lines = [line for line in result.stdout.strip().split("\n") if line]
    assert len(lines) == 3
    for record in [json.loads(line) for line in lines]:
        assert record["success"] is False
        assert record["exception_type"] == "SyntaxError"

def test_missing_func_name_emits_one_error_per_input():
    code = "def wrong_name(): pass"
    payload = {
        "code": code,
        "func_name": "f",
        "inputs": [{"args": [i], "kwargs": {}} for i in range(2)]
    }
    result = run_template(payload)
    assert result.returncode == 0
    lines = [line for line in result.stdout.strip().split("\n") if line]
    assert len(lines) == 2
    for record in [json.loads(line) for line in lines]:
        assert record["success"] is False
        assert record["exception_type"] == "NameError"

def test_return_value_json_nonserializable_falls_back_to_repr():
    code = textwrap.dedent("""
    class Obj:
        def __repr__(self):
            return "<Obj instance>"
    def f():
        return Obj()
    """)
    payload = {
        "code": code,
        "func_name": "f",
        "inputs": [{"args": [], "kwargs": {}}]
    }
    result = run_template(payload)
    assert result.returncode == 0
    lines = [line for line in result.stdout.strip().split("\n") if line]
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["success"] is True
    assert record["return_value"] is None
    assert record["return_repr"].startswith("<")

def test_empty_inputs_exits_cleanly():
    payload = {
        "code": "def f(): pass",
        "func_name": "f",
        "inputs": []
    }
    result = run_template(payload)
    assert result.returncode == 0
    assert not result.stdout.strip()

def test_recursion_limit_applied_in_child():
    code = textwrap.dedent("""
    import sys
    def get_limit():
        return sys.getrecursionlimit()
    """)
    payload = {
        "code": code,
        "func_name": "get_limit",
        "recursion_limit": 1234,
        "inputs": [{"args": [], "kwargs": {}}]
    }
    result = run_template(payload)
    assert result.returncode == 0
    lines = [line for line in result.stdout.strip().split("\n") if line]
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["success"] is True
    assert record["return_value"] == 1234

def test_end_to_end_simple_function():
    code = "def f(x): return x + 1"
    payload = {
        "code": code,
        "func_name": "f",
        "inputs": [{"args": [i], "kwargs": {}} for i in range(100)]
    }
    result = run_template(payload)
    assert result.returncode == 0
    lines = [line for line in result.stdout.strip().split("\n") if line]
    assert len(lines) == 100
    for i, line in enumerate(lines):
        record = json.loads(line)
        assert record["index"] == i
        assert record["return_value"] == i + 1

@settings(deadline=None)
@given(st.lists(st.integers(), max_size=200))
def test_jsonl_roundtrip_all_int_inputs(input_list):
    code = "def f(x): return x * 2"
    payload = {
        "code": code,
        "func_name": "f",
        "inputs": [{"args": [x], "kwargs": {}} for x in input_list]
    }
    result = run_template(payload)
    assert result.returncode == 0
    lines = [line for line in result.stdout.strip().split("\n") if line]
    assert len(lines) == len(input_list)
    for i, (line, expected_inp) in enumerate(zip(lines, input_list)):
        record = json.loads(line)
        assert record["index"] == i
        assert record["return_value"] == expected_inp * 2

def test_child_exit_without_pipe_write_becomes_sandbox_error():
    code = textwrap.dedent("""
    import os
    def f():
        os._exit(0)
    """)
    payload = {
        "code": code,
        "func_name": "f",
        "inputs": [{"args": [], "kwargs": {}}]
    }
    result = run_template(payload)
    assert result.returncode == 0
    lines = [line for line in result.stdout.strip().split("\n") if line]
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["success"] is False
    assert record["exception_type"] == "SandboxError"
    assert "without writing result" in record.get("exception_message", "")
def test_int64_overflow_boundary_input_round_trip():
    # 2**63 and 2**63+1
    boundary_vals = [2**63, 2**63 + 1, -2**63, -2**63 - 1]
    code = "def f(x): return x"
    payload = {
        "code": code,
        "func_name": "f",
        "inputs": [{"args": [x], "kwargs": {}} for x in boundary_vals]
    }
    result = run_template(payload)
    assert result.returncode == 0
    lines = [line for line in result.stdout.strip().split("\n") if line]
    assert len(lines) == len(boundary_vals)
    for i, (line, expected_val) in enumerate(zip(lines, boundary_vals)):
        record = json.loads(line)
        assert record["return_value"] == expected_val

def test_numpy_not_imported_at_module_level():
    tree = ast.parse(_BATCH_RUNNER_TEMPLATE)
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "numpy", "numpy must not be imported at module level"
        elif isinstance(node, ast.ImportFrom):
            assert node.module != "numpy", "numpy must not be imported at module level"
