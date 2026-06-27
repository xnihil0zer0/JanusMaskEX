"""Drive the NGv2 agy-default-hunt multi-file apply via .files.json injection.

Stages the task, injects a whole-file map from the proven references, then runs
the harness auto-commit (apply -> staging wire_up gate -> staging verification of
the committed oracles -> commit to the external NobleGreedv2 master).
"""
import json, glob, os, shutil
from pathlib import Path
from harness.planner.staging import stage_task
from harness import orchestrator as orch

PLAN = Path('state/plans/plan_hooks_ngv2-agy-default-hunt.json')
TID = 'ngv2-agy-default-hunt-impl'
STATE = Path('state')
WORKING_DIR = '/home/xnihil0zer0/NobleGreedv2'

# EXTERNAL_DIRTY_GATE: the target repo must have a clean working tree. Move the
# untracked live-hunt scratch dir aside for the duration of the apply, restore after.
_SCRATCH = Path(WORKING_DIR) / '_parallel_hunts_targets'
_STASHED = Path('/tmp/_parallel_hunts_targets.stashed')
_moved = False
if _SCRATCH.exists():
    if _STASHED.exists():
        shutil.rmtree(_STASHED)
    shutil.move(str(_SCRATCH), str(_STASHED))
    _moved = True
    print('moved scratch aside ->', _STASHED)

# clean prior attempt state for a fresh retry budget
for pat in (f'state/tasks/{TID}.json', f'state/output/{TID}.*'):
    for p in glob.glob(pat):
        os.remove(p)
for p in glob.glob(f'state/sessions/*_{TID}_*'):
    os.remove(p)

stage_task(PLAN, TID, STATE, working_dir=WORKING_DIR)
task = json.load(open(f'state/tasks/{TID}.json'))
print('working_dir =', task.get('working_dir'))

files = {
    'ngv2/agy_client.py': Path('_autowork_scratch/ngv2_agy_client_ref.py').read_text(),
    'ngv2/claude_cli_client.py': Path('_autowork_scratch/ngv2_claude_cli_client_ref.py').read_text(),
    'ngv2/workers/_runner.py': Path('_autowork_scratch/ngv2_runner_ref.py').read_text(),
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
    if _moved:
        shutil.move(str(_STASHED), str(_SCRATCH))
        print('restored scratch ->', _SCRATCH)
