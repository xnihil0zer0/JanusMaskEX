import time
import os
import pytest
import threading
import concurrent.futures
from hypothesis import given, settings
import hypothesis.strategies as st
from harness.sandbox import BatchWorkerPool, SandboxConfig

def test_pool_worker_crash_respawn():
    config = SandboxConfig(timeout_per_input_ms=5000)
    with BatchWorkerPool(1, config=config, session_id="crash_test") as pool:
        code = """
import sys
sys.exit(1)
def target(x):
    return x
"""
        result = pool.submit(code, "target", [{"args": [1]}])
        assert result.batch_error is not None, "Expected batch_error when worker crashes"

def test_pool_amortizes_startup_vs_one_shot():
    config = SandboxConfig()
    with BatchWorkerPool(1, config=config, session_id="amortize_test") as pool:
        code = """
def target(x):
    return x
"""
        start = time.monotonic()
        for i in range(5):
            res = pool.submit(code, "target", [{"args": [i]}])
            assert res.completed_inputs == 1
        elapsed = time.monotonic() - start
        assert elapsed < 1.0, f"Pool execution too slow: {elapsed}s"

def test_shutdown_during_in_flight_submit():
    config = SandboxConfig()
    pool = BatchWorkerPool(1, config=config, session_id="shutdown_test")
    code = """
import time
def target(x):
    time.sleep(2)
    return x
"""
    def submitter():
        return pool.submit(code, "target", [{"args": [1]}])
        
    with concurrent.futures.ThreadPoolExecutor() as ex:
        future = ex.submit(submitter)
        time.sleep(0.5)
        pool.shutdown()
        result = future.result()
        
    assert result.batch_error is not None, "Expected batch_error on shutdown during submit"

def test_pool_construction_spawns_workers():
    config = SandboxConfig()
    with BatchWorkerPool(3, config=config, session_id="test_construction") as pool:
        assert len(pool._workers) == 3
        for w in pool._workers:
            proc = w['proc']
            assert proc.pid > 0
            assert proc.poll() is None, "Worker process should be alive"

def test_pool_submit_single_batch():
    config = SandboxConfig()
    with BatchWorkerPool(1, config=config, session_id="test_single_batch") as pool:
        code = "def target(x): return x"
        inputs = [{"args": [i]} for i in range(10)]
        result = pool.submit(code, "target", inputs)
        
        assert result.completed_inputs == 10
        assert result.batch_error is None
        assert len(result.results) == 10
        for i, res in enumerate(result.results):
            assert res.success is True
            assert res.return_value == i

def test_pool_submit_multiple_batches_reuses_worker():
    config = SandboxConfig()
    with BatchWorkerPool(1, config=config, session_id="test_reuse") as pool:
        code = "def target(x): return x"
        
        res1 = pool.submit(code, "target", [{"args": [1]}])
        assert res1.completed_inputs == 1
        assert res1.batch_error is None
        pid1 = pool._workers[0]['proc'].pid
        
        for i in range(2, 6):
            res = pool.submit(code, "target", [{"args": [i]}])
            assert res.completed_inputs == 1
            assert res.batch_error is None
            assert pool._workers[0]['proc'].pid == pid1, "Worker PID should stay constant"

def test_pool_shutdown_terminates_workers():
    config = SandboxConfig()
    pool = BatchWorkerPool(2, config=config, session_id="test_shutdown_term")
    
    assert len(pool._workers) == 2
    pids = [w['proc'].pid for w in pool._workers]
    
    pool.shutdown()
    
    assert len(pool._workers) == 0
    for pid in pids:
        try:
            os.waitpid(pid, os.WNOHANG)
            pytest.fail(f"Worker {pid} was not reaped")
        except ChildProcessError:
            pass

def test_pool_context_manager_shuts_down():
    config = SandboxConfig()
    pids = []
    with BatchWorkerPool(2, config=config, session_id="test_ctx") as pool:
        pids = [w['proc'].pid for w in pool._workers]
        
    assert len(pool._workers) == 0
    for pid in pids:
        try:
            os.waitpid(pid, os.WNOHANG)
            pytest.fail(f"Worker {pid} was not reaped after with block")
        except ChildProcessError:
            pass

@settings(deadline=None, max_examples=5)
@given(batch_size=st.integers(10, 50))
def test_concurrent_submits_scale_with_pool_size(batch_size):
    config = SandboxConfig()
    with BatchWorkerPool(4, config=config, session_id="test_concurrent") as pool:
        code = """
import time
def target(x):
    time.sleep(0.01)
    return x
"""
        def submit_batch():
            inputs = [{"args": [i]} for i in range(batch_size)]
            return pool.submit(code, "target", inputs)
            
        start = time.monotonic()
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
            futures = [ex.submit(submit_batch) for _ in range(4)]
            results = [f.result() for f in futures]
            
        elapsed = time.monotonic() - start
        
        for res in results:
            assert res.completed_inputs == batch_size
            assert res.batch_error is None
            
        max_expected = batch_size * 0.01 * 3 + 1.0 
        assert elapsed < max_expected, f"Execution was too slow (serialized?): {elapsed}s"

def test_framing_corruption_recovered():
    config = SandboxConfig()
    with BatchWorkerPool(1, config=config, session_id="test_framing") as pool:
        code_normal = "def target(x): return x"
        res1 = pool.submit(code_normal, "target", [{"args": [1]}])
        assert res1.completed_inputs == 1
        assert res1.batch_error is None
        
        pid_before = pool._workers[0]['proc'].pid
        
        code_corrupt = """
import sys
def target(x):
    sys.stdout.buffer.write(b'\\xff\\xff\\xff\\xffbad')
    sys.stdout.buffer.flush()
    return x
"""
        res2 = pool.submit(code_corrupt, "target", [{"args": [1]}])
        assert res2.batch_error is not None
        
        res3 = pool.submit(code_normal, "target", [{"args": [2]}])
        assert res3.completed_inputs == 1
        assert res3.batch_error is None
        assert res3.results[0].return_value == 2
        
        pid_after = pool._workers[0]['proc'].pid
        assert pid_before != pid_after, "Worker should have been killed and respawned"
