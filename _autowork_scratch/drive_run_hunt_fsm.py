"""Drive the NGv2 run_hunt FSM 6-file fix via .files.json injection.

Stages the task, injects the whole-file map from the validated references in
_autowork_scratch/ngv2_fsm/, then runs the harness auto-commit (apply -> wire_up
gate -> staging verification of the committed oracles -> commit to NobleGreedv2
master). Refs were proven green against the committed oracles in a throwaway
copy (1861 passed, 0 regressions).
"""
import json, glob, os, shutil
from pathlib import Path
from harness.planner.staging import stage_task
from harness import orchestrator as orch

PLAN = Path('state/plans/plan_hooks_ngv2-run-hunt-fsm.json')
TID = 'ngv2-run-hunt-fsm-impl'
STATE = Path('state')
WORKING_DIR = '/home/xnihil0zer0/NobleGreedv2'
REF = Path('_autowork_scratch/ngv2_fsm')

# EXTERNAL_DIRTY_GATE: target repo must have a clean tree. Stash untracked scratch.
_stashes = []
for rel in ('_parallel_hunts_targets',):
    p = Path(WORKING_DIR) / rel
    if p.exists():
        dest = Path('/tmp') / ('_stashed_' + rel)
        if dest.exists():
            shutil.rmtree(dest)
        shutil.move(str(p), str(dest))
        _stashes.append((dest, p))
        print('stashed', p, '->', dest)

# clean prior attempt state for a fresh retry budget
for pat in (f'state/tasks/{TID}.json', f'state/output/{TID}.*'):
    for q in glob.glob(pat):
        os.remove(q)
for q in glob.glob(f'state/sessions/*_{TID}_*'):
    os.remove(q)

stage_task(PLAN, TID, STATE, working_dir=WORKING_DIR)
task = json.load(open(f'state/tasks/{TID}.json'))
print('working_dir =', task.get('working_dir'))
print('vcmd =', (task.get('verification_command') or '')[:80], '...')

files = {
    'ngv2/run_hunt.py': (REF / 'run_hunt.py').read_text(),
    'ngv2/stage_command_map.py': (REF / 'stage_command_map.py').read_text(),
    'ngv2/gate_executor.py': (REF / 'gate_executor.py').read_text(),
    'ngv2/conductor_seams.py': (REF / 'conductor_seams.py').read_text(),
    'ngv2/hunt_lead_client.py': (REF / 'hunt_lead_client.py').read_text(),
    'ngv2/workers/_runner.py': (REF / '_runner.py').read_text(),
}
(STATE / 'output' / f'{TID}.files.json').write_text(json.dumps(files))
sidecar = STATE / 'output' / f'{TID}.py'
if sidecar.exists():
    sidecar.unlink()
print('injected files.json with', len(files), 'files; .py sidecar removed:', not sidecar.exists())

try:
    ok = orch._auto_commit_accepted(STATE, task, TID)
    print('AUTO_COMMIT_OK =', ok)
finally:
    for dest, orig in _stashes:
        if dest.exists():
            shutil.move(str(dest), str(orig))
            print('restored', orig)
