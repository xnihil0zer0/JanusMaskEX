"""Drive the single-file conductor_seams _count_real fix via .files.json injection."""
import json, glob, os, shutil
from pathlib import Path
from harness.planner.staging import stage_task
from harness import orchestrator as orch

PLAN = Path('state/plans/plan_hooks_ngv2-conductor-count.json')
TID = 'ngv2-conductor-count-impl'
STATE = Path('state')
WORKING_DIR = '/home/xnihil0zer0/NobleGreedv2'
REF = Path('_autowork_scratch/ngv2_fsm/conductor_seams.py')

_stashes = []
for rel in ('_parallel_hunts_targets',):
    p = Path(WORKING_DIR) / rel
    if p.exists():
        dest = Path('/tmp') / ('_stashed_' + rel)
        if dest.exists():
            shutil.rmtree(dest)
        shutil.move(str(p), str(dest))
        _stashes.append((dest, p))

for pat in (f'state/tasks/{TID}.json', f'state/output/{TID}.*'):
    for q in glob.glob(pat):
        os.remove(q)
for q in glob.glob(f'state/sessions/*_{TID}_*'):
    os.remove(q)

stage_task(PLAN, TID, STATE, working_dir=WORKING_DIR)
task = json.load(open(f'state/tasks/{TID}.json'))
files = {'ngv2/conductor_seams.py': REF.read_text()}
(STATE / 'output' / f'{TID}.files.json').write_text(json.dumps(files))
sc = STATE / 'output' / f'{TID}.py'
if sc.exists():
    sc.unlink()
print('injected; working_dir =', task.get('working_dir'))
try:
    ok = orch._auto_commit_accepted(STATE, task, TID)
    print('AUTO_COMMIT_OK =', ok)
finally:
    for dest, orig in _stashes:
        if dest.exists():
            shutil.move(str(dest), str(orig))
