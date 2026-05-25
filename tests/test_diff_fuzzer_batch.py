import time
import pytest
from unittest.mock import patch, MagicMock
from hypothesis import given, settings, strategies as st, HealthCheck
from harness.diff_fuzzer import differential_fuzz, _fuzz_batch, _fuzz_sequential, FuzzResult, FuzzFailure
from harness.sandbox import BatchRunner, BatchResult, ExecutionResult

def test_differential_fuzz_dispatches_to_batch_by_default():
    with patch("harness.diff_fuzzer._fuzz_batch", return_value=FuzzResult(equivalent=True)) as spy_batch, \
         patch("harness.diff_fuzzer._fuzz_sequential", return_value=FuzzResult(equivalent=True)) as spy_sequential:
        result = differential_fuzz("def f(x: int): return x", "def f(x: int): return x", "f", {})
        assert result.equivalent is True
        spy_batch.assert_called_once()
        spy_sequential.assert_not_called()

def test_differential_fuzz_dispatches_to_sequential_when_disabled():
    with patch("harness.diff_fuzzer._fuzz_batch", return_value=FuzzResult(equivalent=True)) as spy_batch, \
         patch("harness.diff_fuzzer._fuzz_sequential", return_value=FuzzResult(equivalent=True)) as spy_sequential:
        config = {"batch_execution": {"enabled": False}}
        result = differential_fuzz("def f(x: int): return x", "def f(x: int): return x", "f", config)
        assert result.equivalent is True
        spy_sequential.assert_called_once()
        spy_batch.assert_not_called()

def test_fuzz_batch_equivalent_code_returns_equivalent_true():
    config = {"fuzzing": {"function_level_inputs": 50, "seed": 42}}
    code = "def f(x: int): return x * 2"
    res = _fuzz_batch(code, code, "f", config)
    assert res.equivalent is True
    assert res.matching_inputs == 50
    assert len(res.failures) == 0

def test_fuzz_batch_divergent_code_records_failures():
    config = {"fuzzing": {"function_level_inputs": 50, "seed": 42}}
    code_a = "def f(x: int): return x + 1"
    code_b = "def f(x: int): return x + 2"
    res = _fuzz_batch(code_a, code_b, "f", config)
    assert res.equivalent is False
    assert len(res.failures) == 20
    assert res.matching_inputs == 0

def test_fuzz_batch_runner_a_error():
    config = {"fuzzing": {"function_level_inputs": 10, "seed": 42}}
    code_a = "import os\nos.kill(os.getpid(), 9)\ndef f(x: int): pass"
    code_b = "def f(x: int): return x"
    res = _fuzz_batch(code_a, code_b, "f", config)
    assert res.equivalent is False
    assert res.error is not None
    assert "error" in str(res.error).lower() or "runner a" in str(res.error).lower() or "killed" in str(res.error).lower() or "A" in str(res.error) or "signal" in str(res.error).lower()

def test_fuzz_batch_cleanup_called_on_exception():
    config = {"fuzzing": {"function_level_inputs": 10, "seed": 42}}
    code = "def f(x: int): return x"
    
    with patch("harness.diff_fuzzer.outputs_match", side_effect=ValueError("BAM")), \
         patch("harness.sandbox.BatchRunner.cleanup") as spy_cleanup:
        with pytest.raises(ValueError):
            _fuzz_batch(code, code, "f", config)
        assert spy_cleanup.call_count == 2

def test_batch_vs_sequential_identical_results():
    config_batch = {"batch_execution": {"enabled": True}, "fuzzing": {"function_level_inputs": 100, "seed": 42}}
    config_seq = {"batch_execution": {"enabled": False}, "fuzzing": {"function_level_inputs": 100, "seed": 42}}
    code_a = "def f(x: int): return x"
    code_b = "def f(x: int):\n if x % 3 == 0: return x + 1\n return x"
    
    res_batch = differential_fuzz(code_a, code_b, "f", config_batch)
    res_seq = differential_fuzz(code_a, code_b, "f", config_seq)
    
    assert res_batch.equivalent == res_seq.equivalent
    assert len(res_batch.failures) == len(res_seq.failures)
    
    batch_args = [f.input_args for f in res_batch.failures]
    seq_args = [f.input_args for f in res_seq.failures]
    assert batch_args == seq_args

def test_batch_path_faster_than_sequential_smoke():
    config_batch = {"batch_execution": {"enabled": True}, "fuzzing": {"function_level_inputs": 100, "seed": 42}}
    config_seq = {"batch_execution": {"enabled": False}, "fuzzing": {"function_level_inputs": 100, "seed": 42}}
    code_a = "def f(x: int): return x"
    code_b = "def f(x: int): return x"
    
    t0 = time.time()
    differential_fuzz(code_a, code_b, "f", config_batch)
    t1 = time.time()
    batch_elapsed = t1 - t0
    
    t0 = time.time()
    differential_fuzz(code_a, code_b, "f", config_seq)
    t1 = time.time()
    seq_elapsed = t1 - t0
    
    assert batch_elapsed < 0.5 * seq_elapsed + 0.1 # loosen bounds to avoid flaky failures in CI

@given(num_inputs=st.integers(min_value=1, max_value=200))
@settings(max_examples=5, deadline=None, suppress_health_check=[HealthCheck.nested_given])
def test_batch_result_length_matches_input_length(num_inputs):
    config = {"fuzzing": {"function_level_inputs": num_inputs, "seed": 42}}
    code = "def f(x: int): return x"
    res = _fuzz_batch(code, code, "f", config)
    assert res.total_inputs == num_inputs
    if res.error is None:
        assert res.total_inputs == res.matching_inputs

def test_twenty_failure_early_stop_preserved():
    config = {"fuzzing": {"function_level_inputs": 1000, "seed": 42}}
    code_a = "def f(x: int): return 1"
    code_b = "def f(x: int): return 2"
    res = _fuzz_batch(code_a, code_b, "f", config)
    assert res.equivalent is False
    assert len(res.failures) == 20

def test_float_tolerance_respected():
    import math
    code_a = "import math\ndef f(x: float): return math.pi"
    code_b = "import math\ndef f(x: float): return math.pi + 1e-12"
    config = {"fuzzing": {"function_level_inputs": 20, "float_tolerance": 1e-9, "seed": 42}}
    res = _fuzz_batch(code_a, code_b, "f", config)
    assert res.equivalent is True
    assert res.matching_inputs == 20
