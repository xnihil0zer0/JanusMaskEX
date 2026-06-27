"""Drive the multi-file poc_writer + conductor_seams src-layout/sink fix via .files.json injection."""
import json, glob, os
from pathlib import Path
from harness.planner.staging import stage_task
from harness import orchestrator as orch

PLAN = Path('state/plans/plan_hooks_ngv2-poc-srclayout.json')
TID = 'ngv2-poc-srclayout-impl'
STATE = Path('state')
WORKING_DIR = '/home/xnihil0zer0/NobleGreedv2'

for pat in (f'state/tasks/{TID}.json', f'state/output/{TID}.*'):
    for q in glob.glob(pat):
        os.remove(q)
for q in glob.glob(f'state/sessions/*_{TID}_*'):
    os.remove(q)

stage_task(PLAN, TID, STATE, working_dir=WORKING_DIR)
task = json.load(open(f'state/tasks/{TID}.json'))
files = {
    'ngv2/poc_writer.py': Path('_autowork_scratch/ngv2_fsm/poc_writer.py').read_text(),
    'ngv2/conductor_seams.py': Path('_autowork_scratch/ngv2_fsm/conductor_seams.py').read_text(),
}
(STATE / 'output' / f'{TID}.files.json').write_text(json.dumps(files))
sc = STATE / 'output' / f'{TID}.py'
if sc.exists():
    sc.unlink()
print('injected files:', list(files), '; working_dir =', task.get('working_dir'))
ok = orch._auto_commit_accepted(STATE, task, TID)
print('AUTO_COMMIT_OK =', ok)
