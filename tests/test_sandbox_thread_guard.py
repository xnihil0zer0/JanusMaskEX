import sys
import os
import importlib
import pytest
import subprocess
import json
import time
from pathlib import Path
from hypothesis import given, strategies as st

def test_module_level_env_set_on_import():
    # Remove sandbox if already imported
    if "harness.sandbox" in sys.modules:
        del sys.modules["harness.sandbox"]
        
    # Clear the env vars
    os.environ.pop("OPENBLAS_NUM_THREADS", None)
    os.environ.pop("MKL_NUM_THREADS", None)
    
    import harness.sandbox
    
    assert os.environ.get("OPENBLAS_NUM_THREADS") == "1"
    assert os.environ.get("MKL_NUM_THREADS") == "1"

def test_child_env_contains_thread_guards():
    import harness.sandbox
    env = harness.sandbox.sandbox_child_env()
    assert env["OPENBLAS_NUM_THREADS"] == "1"
    assert env["MKL_NUM_THREADS"] == "1"

def test_child_env_overrides_polluted_env():
    import harness.sandbox
    os.environ["OPENBLAS_NUM_THREADS"] = "bad"
    os.environ["MKL_NUM_THREADS"] = "also_bad"
    
    env = harness.sandbox.sandbox_child_env()
    assert env["OPENBLAS_NUM_THREADS"] == "1"
    assert env["MKL_NUM_THREADS"] == "1"
    
    # Test extra dict
    env2 = harness.sandbox.sandbox_child_env({"EXTRA_VAR": "xyz"})
    assert env2["OPENBLAS_NUM_THREADS"] == "1"
    assert env2["EXTRA_VAR"] == "xyz"

def test_numpy_single_thread_in_child_subprocess():
    pytest.importorskip("numpy")
    from harness.sandbox import sandbox_child_env
    
    script = (
        "import json\n"
        "import numpy as np\n"
        "try:\n"
        "    import threadpoolctl\n"
        "    info = threadpoolctl.threadpool_info()\n"
        "    print(json.dumps(info))\n"
        "except ImportError:\n"
        "    print(json.dumps([]))\n"
    )
    env = sandbox_child_env()
    proc = subprocess.run(
        [sys.executable, "-c", script], 
        env=env, 
        capture_output=True, 
        text=True
    )
    assert proc.returncode == 0
    
    info = json.loads(proc.stdout)
    for item in info:
        if item.get("user_api") in ("blas", "openblas", "mkl"):
            assert item.get("num_threads") == 1

@given(st.integers(min_value=1, max_value=8))
def test_setdefault_does_not_clobber_operator_override(num):
    os.environ["OPENBLAS_NUM_THREADS"] = str(num)
    os.environ["MKL_NUM_THREADS"] = str(num)
    
    import harness.sandbox
    importlib.reload(harness.sandbox)
    
    assert os.environ["OPENBLAS_NUM_THREADS"] == str(num)
    assert os.environ["MKL_NUM_THREADS"] == str(num)

def test_polluted_empty_env_coerced_to_one():
    import harness.sandbox
    
    os.environ["OPENBLAS_NUM_THREADS"] = ""
    os.environ["MKL_NUM_THREADS"] = ""
    
    env = harness.sandbox.sandbox_child_env()
    assert env["OPENBLAS_NUM_THREADS"] == "1"
    assert env["MKL_NUM_THREADS"] == "1"

def test_fork_after_numpy_no_deadlock():
    pytest.importorskip("numpy")
    import numpy as np
    
    def child_worker():
        import numpy as np
        arr = np.random.rand(1000)
        np.sort(arr)
        os._exit(0)

    start_time = time.time()
    processes = []
    
    for _ in range(10):
        pid = os.fork()
        if pid == 0:
            try:
                child_worker()
            except Exception:
                os._exit(1)
        else:
            processes.append(pid)
            
    for pid in processes:
        _, status = os.waitpid(pid, 0)
        assert os.WIFEXITED(status)
        assert os.WEXITSTATUS(status) == 0
        
    end_time = time.time()
    assert end_time - start_time < 5.0
