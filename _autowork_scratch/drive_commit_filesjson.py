"""Inject a whole-file .files.json sidecar from the proven reference and drive
the harness auto-commit (apply -> staging verification of the oracle -> commit)."""
import json, sys
from pathlib import Path
from harness import orchestrator as orch

state = Path('state')
tid = 'tmux-worker-pty-rebuild'
task = json.load(open(f'state/tasks/{tid}.json'))

ref = Path('_autowork_scratch/tmux_worker_ref.py').read_text()
# whole-file map -> forces _commit_accepted_output_multi (true overwrite, no AST-merge)
(state / 'output' / f'{tid}.files.json').write_text(json.dumps({'harness/tmux_worker.py': ref}))
# remove the .py sidecar (contains manifest-wrapper text) so files.json is authoritative
p = state / 'output' / f'{tid}.py'
if p.exists():
    p.unlink()
print('injected files.json; .py sidecar removed:', not p.exists())

ok = orch._auto_commit_accepted(state, task, tid)
print('AUTO_COMMIT_OK =', ok)
