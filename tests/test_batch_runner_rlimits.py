import json
import os
import subprocess
import sys
import tempfile
import textwrap
from hypothesis import given, settings, strategies as st

from harness.sandbox import _BATCH_RUNNER_TEMPLATE

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
        lines = [line for line in result.stdout.strip().split("\n") if line]
        records = [json.loads(line) for line in lines]
        return records, result.stderr
    finally:
        os.unlink(script_path)
        os.unlink(payload_path)

def test_rlimit_as_triggers_memory_error():
    code = "def f():\n    x = bytearray(128 * 1024 * 1024)\n    return 0"
    payload = {
        "code": code,
        "func_name": "f",
        "memory_limit_mb": 64,
        "inputs": [{"args": [], "kwargs": {}}]
    }
    records, stderr = run_template(payload)
    assert len(records) == 1
    assert records[0]["success"] is False
    assert records[0]["exception_type"] == "MemoryError"

def test_rlimit_cpu_triggers_sigxcpu():
    code = "def f():\n    while True:\n        pass"
    payload = {
        "code": code,
        "func_name": "f",
        "cpu_time_limit_seconds": 1,
        "inputs": [{"args": [], "kwargs": {}}]
    }
    records, stderr = run_template(payload)
    assert len(records) == 1
    assert records[0]["success"] is False
    assert records[0]["exception_type"] in ("TimeoutError", "SandboxError", "OSError", "KeyboardInterrupt")

def test_rlimit_fsize_triggers_file_too_large():
    code = "def f():\n    with open('test_fsize.bin', 'wb') as f:\n        f.write(bytearray(20 * 1024 * 1024))\n    return 0"
    payload = {
        "code": code,
        "func_name": "f",
        "child_fsize_limit_mb": 10,
        "inputs": [{"args": [], "kwargs": {}}]
    }
    records, stderr = run_template(payload)
    assert len(records) == 1
    assert records[0]["success"] is False
    assert records[0]["exception_type"] in ("OSError", "SandboxError", "TimeoutError")
    try:
        os.unlink("test_fsize.bin")
    except OSError:
        pass

def test_rlimit_nproc_not_set_by_default():
    code = textwrap.dedent("""
    import resource
    def f():
        return resource.getrlimit(resource.RLIMIT_NPROC)
    """)
    payload = {
        "code": code,
        "func_name": "f",
        "inputs": [{"args": [], "kwargs": {}}]
    }
    records, stderr = run_template(payload)
    import resource
    parent_limit = resource.getrlimit(resource.RLIMIT_NPROC)
    assert len(records) == 1
    assert records[0]["success"] is True
    assert tuple(records[0]["return_value"]) == parent_limit

def test_numpy_works_under_rlimit_nproc_zero():
    import pytest
    pytest.importorskip("numpy")
    code = textwrap.dedent("""
    import numpy as np
    def f():
        return int(np.sort(np.arange(1000)[::-1])[0])
    """)
    payload = {
        "code": code,
        "func_name": "f",
        "rlimit_nproc": 0,
        "inputs": [{"args": [], "kwargs": {}}]
    }
    records, stderr = run_template(payload)
    assert len(records) == 1
    assert records[0]["success"] is True
    assert records[0]["return_value"] == 0

@settings(deadline=None, max_examples=10)
@given(st.integers(min_value=128, max_value=256))
def test_rlimit_as_boundary_around_limit(limit_mb):
    code = "def f(alloc_mb):\n    x = bytearray(alloc_mb * 1024 * 1024)\n    return 1"
    payload = {
        "code": code,
        "func_name": "f",
        "memory_limit_mb": limit_mb,
        "inputs": [
            {"args": [int((limit_mb - 30) * 0.8)], "kwargs": {}},
            {"args": [int((limit_mb - 30) * 1.2)], "kwargs": {}}
        ]
    }
    records, stderr = run_template(payload)
    if len(records) == 2:
        assert records[0]["success"] is True
        assert records[1]["success"] is False
        assert records[1]["exception_type"] in ("MemoryError", "SandboxError")

def test_sibling_inputs_survive_oom_sibling():
    code = textwrap.dedent("""
    def f(alloc_mb):
        if alloc_mb > 0:
            x = bytearray(alloc_mb * 1024 * 1024)
        return 1
    """)
    payload = {
        "code": code,
        "func_name": "f",
        "memory_limit_mb": 64,
        "inputs": [
            {"args": [0]}, {"args": [0]}, {"args": [0]},
            {"args": [128]},
            {"args": [0]}, {"args": [0]}, {"args": [0]}
        ]
    }
    records, stderr = run_template(payload)
    assert len(records) == 7
    for i in [0, 1, 2, 4, 5, 6]:
        assert records[i]["success"] is True
    assert records[3]["success"] is False
    assert records[3]["exception_type"] in ("MemoryError", "SandboxError")

def test_rlimit_nproc_zero_documented_rejected():
    code = textwrap.dedent("""
    import threading
    def dummy(): pass
    def f():
        t = threading.Thread(target=dummy)
        t.start()
        t.join()
        return 1
    """)
    payload = {
        "code": code,
        "func_name": "f",
        "rlimit_nproc": 0,
        "inputs": [{"args": []}]
    }
    records, stderr = run_template(payload)
    assert len(records) == 1
    assert records[0]["success"] is False
    err_msg = records[0].get("exception_message", "").lower()
    assert "thread" in err_msg or "runtimeerror" in records[0]["exception_type"].lower() or "oserror" in records[0]["exception_type"].lower()
