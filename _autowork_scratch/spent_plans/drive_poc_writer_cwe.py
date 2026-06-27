"""Drive the single-file poc_writer CWE-94/CWE-22 template extension via .files.json injection."""
import json, glob, os, shutil
from pathlib import Path
from harness.planner.staging import stage_task
from harness import orchestrator as orch

PLAN = Path('state/plans/plan_hooks_ngv2-poc-writer-cwe.json')
TID = 'ngv2-poc-writer-cwe-impl'
STATE = Path('state')
WORKING_DIR = '/home/xnihil0zer0/NobleGreedv2'
REF = Path('_autowork_scratch/ngv2_fsm/poc_writer.py')

for pat in (f'state/tasks/{TID}.json', f'state/output/{TID}.*'):
    for q in glob.glob(pat):
        os.remove(q)
for q in glob.glob(f'state/sessions/*_{TID}_*'):
    os.remove(q)

stage_task(PLAN, TID, STATE, working_dir=WORKING_DIR)
task = json.load(open(f'state/tasks/{TID}.json'))
files = {'ngv2/poc_writer.py': REF.read_text()}
(STATE / 'output' / f'{TID}.files.json').write_text(json.dumps(files))
sc = STATE / 'output' / f'{TID}.py'
if sc.exists():
    sc.unlink()
print('injected; working_dir =', task.get('working_dir'))
ok = orch._auto_commit_accepted(STATE, task, TID)
print('AUTO_COMMIT_OK =', ok)
