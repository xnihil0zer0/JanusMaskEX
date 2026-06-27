"""Manual-drive the NGv2 detonation-deps + sink-localization 4-file land via .files.json."""
import json, glob, os
from pathlib import Path
from harness.planner.staging import stage_task
from harness import orchestrator as orch

G = Path('_autowork_scratch/gapfix/G_detondeps')
H = Path('_autowork_scratch/gapfix/H_sinkloc')
PLAN = G / 'plan_hooks_ngv2-detonloc.json'
TID = 'ngv2-detonloc-impl'
STATE = Path('state')
NGV2 = '/home/xnihil0zer0/NobleGreedv2'

for pat in (f'state/tasks/{TID}.json', f'state/output/{TID}.*',
            f'state/tasks/processed/{TID}.json', f'state/tasks/blocked/{TID}.*'):
    for q in glob.glob(pat):
        os.remove(q)
for q in glob.glob(f'state/sessions/*_{TID}_*'):
    os.remove(q)

stage_task(PLAN, TID, STATE, working_dir=NGV2)
task = json.load(open(f'state/tasks/{TID}.json'))

files = {
    'ngv2/poc_runner_live.py': (G / 'poc_runner_live.py').read_text(),
    'ngv2/sink_localize.py': (H / 'sink_localize.py').read_text(),
    'ngv2/hunt_lead_client.py': (H / 'hunt_lead_client.py').read_text(),
    'ngv2/poc_writer.py': (H / 'poc_writer.py').read_text(),
}
(STATE / 'output' / f'{TID}.files.json').write_text(json.dumps(files))
sc = STATE / 'output' / f'{TID}.py'
if sc.exists():
    sc.unlink()
print('injected files:', list(files), '; working_dir =', task.get('working_dir'))
print('vcmd =', task.get('verification_command'))
ok = orch._auto_commit_accepted(STATE, task, TID)
print('AUTO_COMMIT_OK =', ok)
