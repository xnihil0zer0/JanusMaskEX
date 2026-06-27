"""Manual-drive the drive-backup repo-resolution fix via .files.json injection.
Self-target (JM-internal tools/), multi-file whole-file map -> _auto_commit_accepted
applies, commits files_touched, runs the committed pytest oracle (jailed), and
rolls back on any failure."""
import json, glob, os
from pathlib import Path
from harness.planner.staging import stage_task
from harness import orchestrator as orch

HERE = Path('_autowork_scratch/gapfix/backup_fix')
PLAN = HERE / 'plan_hooks_drive-backup-repo-fix.json'
TID = 'drive-backup-repo-fix'
STATE = Path('state')

# Purge any stale sidecars/sessions/tasks/processed for a clean retry budget.
for pat in (f'state/tasks/{TID}.json', f'state/output/{TID}.*',
            f'state/tasks/processed/{TID}.json'):
    for q in glob.glob(pat):
        os.remove(q)
for q in glob.glob(f'state/sessions/*_{TID}_*'):
    os.remove(q)

stage_task(PLAN, TID, STATE)  # self-target: working_dir defaults to JM
task = json.load(open(f'state/tasks/{TID}.json'))

files = {
    'tools/drive_backup/hook_runner.py': (HERE / 'hook_runner.py').read_text(),
    'tools/drive_backup/ledger.py': (HERE / 'ledger.py').read_text(),
    'tools/drive_backup/install_hooks.py': (HERE / 'install_hooks.py').read_text(),
}
(STATE / 'output' / f'{TID}.files.json').write_text(json.dumps(files))
sc = STATE / 'output' / f'{TID}.py'
if sc.exists():
    sc.unlink()
print('injected files:', list(files))
print('vcmd =', task.get('verification_command'))
ok = orch._auto_commit_accepted(STATE, task, TID)
print('AUTO_COMMIT_OK =', ok)
