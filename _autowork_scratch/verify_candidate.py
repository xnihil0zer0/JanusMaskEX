import importlib.util, sys, harness
spec = importlib.util.spec_from_file_location("harness.tmux_worker","/home/xnihil0zer0/JanusMaskJR/state/output/tmux-worker-pty-rebuild.py")
mod = importlib.util.module_from_spec(spec); sys.modules["harness.tmux_worker"]=mod; spec.loader.exec_module(mod)
import pytest; sys.exit(pytest.main(["-q","-p","no:cacheprovider","tests/harness/test_tmux_worker.py"]))
