import sys, importlib.util, subprocess
import harness.git_integration as gi
head = subprocess.run(['git','show','HEAD:harness/tmux_worker.py'],capture_output=True,text=True).stdout
ref = open('_autowork_scratch/tmux_worker_ref.py').read()
merged = gi._ast_merge(ref, head)
open('_autowork_scratch/_merged_probe.py','w').write(merged)
# does merged define run_pty_worker / agent_jail / re ?
for name in ['run_pty_worker','agent_jail','re ','tmux_seams','READY_MARKER','def jail_command','def run_tmux_worker']:
    print(f'  has {name!r}:', name in merged)
spec=importlib.util.spec_from_file_location('harness.tmux_worker','_autowork_scratch/_merged_probe.py')
m=importlib.util.module_from_spec(spec); sys.modules['harness.tmux_worker']=m
try:
    spec.loader.exec_module(m); print('  import: OK')
except Exception as e: print('  import FAILED:', repr(e))
import pytest
print('--- oracle vs MERGED ---')
pytest.main(['-q','-p','no:cacheprovider','tests/harness/test_tmux_worker.py'])
