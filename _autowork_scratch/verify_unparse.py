import ast, importlib.util, sys, harness
ref = open('_autowork_scratch/tmux_worker_ref.py').read()
unparsed = ast.unparse(ast.parse(ref))
open('_autowork_scratch/_unparsed_probe.py','w').write(unparsed)
spec = importlib.util.spec_from_file_location("harness.tmux_worker","_autowork_scratch/_unparsed_probe.py")
m = importlib.util.module_from_spec(spec); sys.modules["harness.tmux_worker"]=m; spec.loader.exec_module(m)
import pytest; sys.exit(pytest.main(["-q","-p","no:cacheprovider","tests/harness/test_tmux_worker.py"]))
