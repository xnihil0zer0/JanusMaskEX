"""Manual-drive the NGv2 sourcing 2-file land via .files.json injection (external target)."""
import json, glob, os
from pathlib import Path
from harness.planner.staging import stage_task
from harness import orchestrator as orch

G = Path('_autowork_scratch/gapfix/E_campaign')
PLAN = G / 'plan_hooks_ngv2-sourcing.json'
TID = 'ngv2-sourcing-impl'
STATE = Path('state')
NGV2 = '/home/xnihil0zer0/NobleGreedv2'

# Purge stale sidecars/sessions/tasks/processed for a clean retry budget.
for pat in (f'state/tasks/{TID}.json', f'state/output/{TID}.*',
            f'state/tasks/processed/{TID}.json', f'state/tasks/blocked/{TID}.*'):
    for q in glob.glob(pat):
        os.remove(q)
for q in glob.glob(f'state/sessions/*_{TID}_*'):
    os.remove(q)

stage_task(PLAN, TID, STATE, working_dir=NGV2)
task = json.load(open(f'state/tasks/{TID}.json'))

files = {
    'ngv2/campaign.py': (G / 'campaign.py').read_text(),
    'ngv2/hunt_lead_client.py': (Path('_autowork_scratch/gapfix/F_fallback') / 'hunt_lead_client.py').read_text(),
}
(STATE / 'output' / f'{TID}.files.json').write_text(json.dumps(files))
sc = STATE / 'output' / f'{TID}.py'
if sc.exists():
    sc.unlink()
print('injected files:', list(files), '; working_dir =', task.get('working_dir'))
print('vcmd =', task.get('verification_command'))
ok = orch._auto_commit_accepted(STATE, task, TID)
print('AUTO_COMMIT_OK =', ok)
