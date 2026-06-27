import importlib.util, sys
import harness  # ensure package is importable
spec = importlib.util.spec_from_file_location("harness.tmux_worker",
        "/home/xnihil0zer0/JanusMaskJR/_autowork_scratch/tmux_worker_ref.py")
mod = importlib.util.module_from_spec(spec)
sys.modules["harness.tmux_worker"] = mod
spec.loader.exec_module(mod)
import pytest
sys.exit(pytest.main(["-q", "-p", "no:cacheprovider", "tests/harness/test_tmux_worker.py"]))
