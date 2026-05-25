import pytest
import shutil
import random
from pathlib import Path
from dataclasses import fields
from hypothesis import given, settings, strategies as st

from harness.sandbox import (
    SandboxConfig,
    Sandbox,
    ExecutionResult,
    BatchResult,
    BatchRunner,
    batch_runner_from_config,
)

# Unit Tests

def test_batch_result_dataclass_fields():
    res = BatchResult(results=[], total_inputs=0, completed_inputs=0)
    assert res.batch_error is None
    
    field_names = {f.name for f in fields(BatchResult)}
    assert field_names == {"results", "total_inputs", "completed_inputs", "batch_error"}

def test_batch_runner_sandbox_dir_lazy():
    runner = BatchRunner(session_id="test_lazy")
    assert runner._sandbox_dir is None
    
    dir_path = runner.sandbox_dir
    assert dir_path.exists()
    assert runner._sandbox_dir is not None
    assert runner.sandbox_dir == dir_path
    runner.cleanup()

def test_batch_runner_cleanup_idempotent():
    runner = BatchRunner(session_id="test_cleanup")
    dir_path = runner.sandbox_dir
    assert dir_path.exists()
    
    runner.cleanup()
    assert not dir_path.exists()
    
    # Second call should not raise anything
    runner.cleanup()

def test_execute_batch_preserves_order():
    runner = BatchRunner(session_id="test_ordering")
    inputs = [{"args": [i]} for i in range(10)]
    
    res = runner.execute_batch(
        code="def f(x): return x * 10",
        func_name="f",
        inputs=inputs
    )
    
    assert res.total_inputs == 10
    assert res.completed_inputs == 10
    for i in range(10):
        assert res.results[i].return_value == i * 10
    
    runner.cleanup()

def test_execute_batch_empty_inputs():
    runner = BatchRunner(session_id="test_empty")
    res = runner.execute_batch(
        code="def f(x): return x",
        func_name="f",
        inputs=[]
    )
    assert res.results == []
    assert res.total_inputs == 0
    assert res.completed_inputs == 0
    assert res.batch_error is None
    
    runner.cleanup()

def test_batch_runner_from_config():
    config = {
        "sandbox": {
            "memory_limit_mb": 128,
            "filesystem_root": "/tmp/test_janusmask_batch"
        }
    }
    runner = batch_runner_from_config(config, session_id="abc")
    assert runner.config.memory_limit_mb == 128
    assert runner.session_id == "abc"
    runner.cleanup()


# Integration Tests

def test_execute_batch_matches_sandbox_execute():
    config = SandboxConfig(memory_limit_mb=128)
    sandbox = Sandbox(config=config, session_id="test_int_sandbox")
    runner = BatchRunner(config=config, session_id="test_int_runner")
    
    code = "def f(x): return x * 2"
    inputs = [{"args": [1]}, {"args": [2]}, {"args": [3]}, {"args": ["a"]}, {"args": [5]}]
    
    batch_res = runner.execute_batch(code, "f", inputs)
    
    sandbox_res = []
    for inp in inputs:
        res = sandbox.execute(code, "f", args=inp.get("args"), kwargs=inp.get("kwargs"))
        sandbox_res.append(res)
        
    for i in range(len(inputs)):
        assert batch_res.results[i].return_value == sandbox_res[i].return_value
        assert batch_res.results[i].exception_type == sandbox_res[i].exception_type
        
    sandbox.cleanup()
    runner.cleanup()


# Property Tests

@settings(max_examples=10, deadline=None)
@given(st.lists(st.integers(min_value=-100, max_value=100), min_size=1, max_size=10))
def test_ordering_preserved_under_shuffle(int_list):
    # Copy to avoid mutating hypothesis data
    shuffled_list = list(int_list)
    random.shuffle(shuffled_list)
    
    from harness.sandbox import SandboxConfig
    runner = BatchRunner(session_id="test_prop_ordering", config=SandboxConfig(timeout_per_input_ms=15000))
    inputs = [{"args": [x]} for x in shuffled_list]
    
    res = runner.execute_batch(
        code="def f(x): return x ** 2",
        func_name="f",
        inputs=inputs
    )
    
    for i, x in enumerate(shuffled_list):
        assert res.results[i].return_value == x ** 2
        
    runner.cleanup()


# Regression Tests

def test_missing_args_kwargs_default_empty():
    runner = BatchRunner(session_id="test_missing_args_kwargs")
    inputs = [
        {"args": [10]},       # missing kwargs
        {"kwargs": {"y": 20}}, # missing args
        {}                    # missing both
    ]
    
    code = "def f(*args, **kwargs): return sum(args) + sum(kwargs.values())"
    res = runner.execute_batch(code, "f", inputs)
    
    assert res.completed_inputs == 3
    assert res.results[0].return_value == 10
    assert res.results[1].return_value == 20
    assert res.results[2].return_value == 0
    
    runner.cleanup()

def test_cleanup_after_exception_in_execute_batch(monkeypatch):
    runner = BatchRunner(session_id="test_exception_cleanup")

    # Access to ensure directory is created
    dir_path = runner.sandbox_dir

    # Monkeypatch subprocess.Popen to raise an exception
    def mock_popen(*args, **kwargs):
        raise OSError("simulated Popen failure")

    monkeypatch.setattr("subprocess.Popen", mock_popen)

    batch = runner.execute_batch(
        code="def f(): pass",
        func_name="f",
        inputs=[{"args": []}]
    )

    assert "simulated Popen failure" in str(batch.batch_error)

    runner.cleanup()
    assert not dir_path.exists()
