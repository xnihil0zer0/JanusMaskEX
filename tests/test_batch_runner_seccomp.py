import json
import os
import subprocess
import sys
import tempfile
import textwrap
import ctypes.util

import pytest
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

libseccomp_present = ctypes.util.find_library("seccomp") is not None
pytestmark = pytest.mark.skipif(not libseccomp_present, reason="libseccomp not available")

def test_seccomp_blocks_socket_connect():
    code = textwrap.dedent("""
    import socket
    def f():
        s = socket.socket()
        s.connect(('127.0.0.1', 80))
        return 1
    """)
    payload = {
        "code": code,
        "func_name": "f",
        "inputs": [{"args": []}]
    }
    records, stderr = run_template(payload)
    assert len(records) == 1
    assert records[0]["success"] is False
    assert records[0]["exception_type"] in ("PermissionError", "OSError", "SandboxError", "ConnectionRefusedError")

def test_seccomp_disabled_toggle():
    code = textwrap.dedent("""
    import socket
    def f():
        try:
            s = socket.socket()
        except OSError as e:
            if e.errno == 1: # EPERM
                return "EPERM"
            return "OTHER_ERROR"
        return "SUCCESS"
    """)
    payload = {
        "code": code,
        "func_name": "f",
        "seccomp": False,
        "inputs": [{"args": []}]
    }
    records, stderr = run_template(payload)
    assert len(records) == 1
    assert records[0]["success"] is True
    assert records[0]["return_value"] == "SUCCESS"

def test_seccomp_blocks_fork_cleanly():
    code = textwrap.dedent("""
    import os
    def f():
        os.fork()
        return 1
    """)
    payload = {
        "code": code,
        "func_name": "f",
        "inputs": [{"args": []}]
    }
    records, stderr = run_template(payload)
    assert len(records) == 1
    assert records[0]["success"] is False
    assert records[0]["exception_type"] in ("PermissionError", "OSError", "SandboxError", "BlockingIOError")

def test_python_threading_works_in_child_default_config():
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
        "inputs": [{"args": []}]
    }
    records, stderr = run_template(payload)
    assert len(records) == 1
    assert records[0]["success"] is True
    assert records[0]["return_value"] == 1

def test_seccomp_denied_syscall_does_not_hang():
    code = textwrap.dedent("""
    import os
    import sys
    def f():
        os.execvp(sys.executable, [sys.executable, "-c", "print(1)"])
        return 1
    """)
    payload = {
        "code": code,
        "func_name": "f",
        "inputs": [{"args": []}]
    }
    records, stderr = run_template(payload)
    assert len(records) == 1
    assert records[0]["success"] is False
    assert records[0]["exception_type"] in ("PermissionError", "OSError", "SandboxError")

def test_seccomp_missing_library_fallback():
    code = textwrap.dedent("""
    import socket
    def f():
        return 1
    """)
    payload = {
        "code": code,
        "func_name": "f",
        "inputs": [{"args": []}]
    }
    
    template = _BATCH_RUNNER_TEMPLATE.replace(
        'lib_path = ctypes.util.find_library("seccomp")',
        'lib_path = None'
    )
    
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f_script:
        f_script.write(template)
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
    finally:
        os.unlink(script_path)
        os.unlink(payload_path)
        
    assert len(records) == 1
    assert records[0]["success"] is True

def test_seccomp_clone_thread_allowed():
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
        "inputs": [{"args": []}]
    }
    records, stderr = run_template(payload)
    assert len(records) == 1
    assert records[0]["success"] is True
    assert records[0]["return_value"] == 1
