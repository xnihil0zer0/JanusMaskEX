import json
import os
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings
import hypothesis.strategies as st

from harness.sandbox import BatchRunner, SandboxConfig, ExecutionResult, BatchResult, Sandbox, sandbox_child_env


@pytest.fixture
def batch_runner():
    config = SandboxConfig(timeout_per_input_ms=500, cpu_time_limit_seconds=1)
    runner = BatchRunner(config=config, session_id="test_batch")
    yield runner
    runner.cleanup()


def test_execute_batch_happy_path_100_inputs(batch_runner):
    code = "def f(x): return x * 2"
    inputs = [{"args": [i]} for i in range(100)]
    
    batch = batch_runner.execute_batch(code, "f", inputs)
    
    assert batch.completed_inputs == 100
    assert batch.batch_error is None
    for i, res in enumerate(batch.results):
        assert res.success is True
        assert res.return_value == i * 2


def test_execute_batch_partial_failure(batch_runner):
    code = """
def f(x):
    if x % 2 != 0:
        raise ValueError("Odd")
    return x
"""
    inputs = [{"args": [i]} for i in range(10)]
    batch = batch_runner.execute_batch(code, "f", inputs)
    
    assert batch.batch_error is None
    assert batch.completed_inputs == 10
    for i, res in enumerate(batch.results):
        if i % 2 == 0:
            assert res.success is True
            assert res.return_value == i
        else:
            assert res.success is False
            assert res.exception_type == "ValueError"


def test_execute_batch_runner_crash(batch_runner):
    # Instead of killing the child, kill the runner parent!
    code = """
import os
import signal
def f(x):
    os.kill(os.getppid(), signal.SIGKILL)
    return x
"""
    inputs = [{"args": [i]} for i in range(5)]
    batch = batch_runner.execute_batch(code, "f", inputs)
    
    assert batch.batch_error is not None
    assert batch.completed_inputs == 0
    assert all(r.exception_type == 'SandboxError' for r in batch.results)
    assert all("No result received" in r.exception_message for r in batch.results)


def test_execute_batch_out_of_range_index_dropped(batch_runner):
    class MockPopen:
        def __init__(self, *args, **kwargs):
            self.stdout = [
                json.dumps({"index": 999, "success": True}) + "\n",
                json.dumps({"index": 0, "success": True}) + "\n"
            ]
            self.stderr = None
            self.pid = 12345
            self.returncode = 0
        
        def wait(self, timeout=None):
            return 0
            
    with patch("subprocess.Popen", MockPopen):
        inputs = [{"args": [i]} for i in range(2)]
        batch = batch_runner.execute_batch("def f(x): return x", "f", inputs)
        
        assert batch.completed_inputs == 1
        assert batch.results[0].success is True
        assert batch.results[1].exception_type == "SandboxError"


def test_execute_batch_popen_failure(batch_runner):
    def mock_popen(*args, **kwargs):
        raise OSError("fork failed")
        
    with patch("subprocess.Popen", mock_popen):
        inputs = [{"args": [1]}]
        batch = batch_runner.execute_batch("def f(x): return x", "f", inputs)
        
        assert batch.batch_error is not None
        assert "fork failed" in batch.batch_error
        assert batch.completed_inputs == 0


def test_execute_batch_uses_sandbox_child_env(batch_runner):
    original_popen = subprocess.Popen
    
    captured_env = {}
    
    class MockPopen(original_popen):
        def __init__(self, *args, **kwargs):
            captured_env.update(kwargs.get("env", {}))
            super().__init__(*args, **kwargs)
            
    with patch("subprocess.Popen", MockPopen):
        batch_runner.execute_batch("def f(): pass", "f", [{"args": []}])
        
    assert captured_env.get("OPENBLAS_NUM_THREADS") == "1"
    assert captured_env.get("MKL_NUM_THREADS") == "1"


def test_execute_batch_placeholder_initialization(batch_runner):
    class MockPopen:
        def __init__(self, *args, **kwargs):
            self.stdout = [
                json.dumps({"index": 2, "success": True}) + "\n",
                json.dumps({"index": 5, "success": True}) + "\n"
            ]
            self.stderr = None
            self.pid = 12345
            self.returncode = 0
        
        def wait(self, timeout=None):
            return 0
            
    with patch("subprocess.Popen", MockPopen):
        inputs = [{"args": [i]} for i in range(10)]
        batch = batch_runner.execute_batch("def f(x): return x", "f", inputs)
        
        assert batch.completed_inputs == 2
        assert batch.results[0].exception_message.startswith("No result received")
        assert batch.results[2].success is True
        assert batch.results[5].success is True
        assert batch.results[9].exception_type == "SandboxError"


def test_execute_batch_no_fd_leak_on_timeout(batch_runner):
    code = "def f(x): return x"
    inputs = [{"args": [1]}]
    
    fd_dir = Path(f"/proc/{os.getpid()}/fd")
    if not fd_dir.exists():
        pytest.skip("No /proc self fd")
        
    fd_count_before = len(list(fd_dir.iterdir()))
    
    # Inject TimeoutExpired during json loading
    def mock_json_loads(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="mock", timeout=0.1)
        
    with patch("json.loads", side_effect=mock_json_loads):
        batch = batch_runner.execute_batch(code, "f", inputs)
    
    fd_count_after = len(list(fd_dir.iterdir()))
    
    assert batch.batch_error is not None
    assert "timed out after" in batch.batch_error
    assert fd_count_after - fd_count_before == 0


def test_execute_batch_equivalence_with_sandbox():
    config = SandboxConfig(timeout_per_input_ms=5000)
    batch_runner = BatchRunner(config=config, session_id="batch_equiv")
    sandbox = Sandbox(config=config, session_id="sandbox_equiv")
    
    code = "def f(x, y): return x + y"
    inputs = [{"args": [i, i+1]} for i in range(10)]
    
    batch_start = time.monotonic()
    batch_res = batch_runner.execute_batch(code, "f", inputs)
    batch_time = time.monotonic() - batch_start
    
    sandbox_results = []
    sandbox_start = time.monotonic()
    for inp in inputs:
        res = sandbox.execute(code, "f", args=inp["args"])
        sandbox_results.append(res)
    sandbox_time = time.monotonic() - sandbox_start
    
    for i in range(len(inputs)):
        assert batch_res.results[i].success == sandbox_results[i].success
        assert batch_res.results[i].return_value == sandbox_results[i].return_value
        
    assert batch_time < sandbox_time
    
    batch_runner.cleanup()
    sandbox.cleanup()


@settings(max_examples=20, deadline=None)
@given(st.lists(st.dictionaries(keys=st.sampled_from(["args"]), values=st.lists(st.integers())), min_size=0, max_size=50))
def test_results_list_length_always_equals_input_length(inputs):
    runner = BatchRunner(config=SandboxConfig(timeout_per_input_ms=100))
    batch = runner.execute_batch("def f(*args): return 0", "f", inputs)
    assert len(batch.results) == len(inputs)
    runner.cleanup()


def test_negative_integer_floor_division_preserved(batch_runner):
    code = "def f(a, b): return a // b"
    inputs = [{"args": [-7, 2]}]
    batch = batch_runner.execute_batch(code, "f", inputs)
    assert batch.results[0].success is True
    assert batch.results[0].return_value == -4


def test_int_accumulation_2_to_63_boundary(batch_runner):
    code = "def f(): return sum(range(2**30, 2**30 + 10))"
    inputs = [{"args": []}]
    batch = batch_runner.execute_batch(code, "f", inputs)
    assert batch.results[0].success is True
    val = sum(range(2**30, 2**30 + 10))
    assert batch.results[0].return_value == val
    assert batch.results[0].return_repr == repr(val)


def test_nan_sort_result_preserved_in_repr(batch_runner):
    code = """
def f():
    import math
    return sorted([1.0, float('nan'), 2.0], key=lambda x: str(x))
"""
    inputs = [{"args": []}]
    batch = batch_runner.execute_batch(code, "f", inputs)
    assert batch.results[0].success is True
    assert "nan" in batch.results[0].return_repr.lower()


def test_variable_length_output_unpadded(batch_runner):
    code = "def f(x): return [v for v in x if v > 0]"
    inputs = [{"args": [[-1, 1, 2]]}, {"args": [[-1, -2]]}]
    batch = batch_runner.execute_batch(code, "f", inputs)
    assert batch.results[0].success is True
    assert batch.results[0].return_value == [1, 2]
    assert batch.results[1].success is True
    assert batch.results[1].return_value == []
