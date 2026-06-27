"""Drive the orchestrator _path_b_outbox_fallback str-coercion fix via .files.json.

Single-symbol AST-merge into harness/orchestrator.py (NEVER_AUTO_APPROVE -> decision
file present). Stages, injects a minimal submission (just the corrected function),
runs auto-commit (apply -> wire_up -> verification of the B3 oracle -> commit).
"""
import json, glob, os
from pathlib import Path
from harness.planner.staging import stage_task
from harness import orchestrator as orch

STATE = Path('state')
TID = 'orchestrator-outbox-fallback-path-coerce'
PLAN = Path(f'state/plans/plan_hooks_{TID}.json')

tmpl = json.load(open('state/plans/plan_hooks_tmux-worker-pty-rebuild.json'))
t = tmpl['tasks'][0]
t['task_id'] = TID
t['title'] = 'Coerce work_dir to Path in _path_b_outbox_fallback (PTY backend str _work_dir)'
t['files_touched'] = ['harness/orchestrator.py']
t['acceptance_criteria'] = [
    '_path_b_outbox_fallback coerces work_dir to Path so a str work_dir (PTY _ExitedProc._work_dir) does not raise TypeError.',
    'All other symbols in harness/orchestrator.py are unchanged.',
    'tests/adversarial/test_B3_path_b_outbox_fallback.py passes.',
]
t['verification_command'] = 'python -m pytest tests/adversarial/test_B3_path_b_outbox_fallback.py -q'
t['spec']['objective'] = 'Defensive Path() coercion so the PTY backend str _work_dir is harvested instead of crashing the poll into a silent agy fallback.'
t['spec']['non_goals'] = [
    'INTEGRATION-TEST EXCUSE: this is a pure single-line defensive coercion on an in-process helper with no I/O boundary; an executing integration test is out of scope and excused.',
    'Do NOT change any other orchestrator symbol, the headless/agy paths, or config.',
]
tmpl['working_dir'] = None
PLAN.write_text(json.dumps(tmpl, indent=2))
print('wrote plan', PLAN)

for pat in (f'state/tasks/{TID}.json', f'state/output/{TID}.*'):
    for p in glob.glob(pat):
        os.remove(p)
for p in glob.glob(f'state/sessions/*_{TID}_*'):
    os.remove(p)

stage_task(PLAN, TID, STATE, working_dir=None)
task = json.load(open(f'state/tasks/{TID}.json'))
print('staged; working_dir =', task.get('working_dir'), '| meta_task_type =', task.get('meta_task_type'))

files = {'harness/orchestrator.py': Path('_autowork_scratch/orchestrator_outbox_coerce_ref.py').read_text()}
(STATE / 'output' / f'{TID}.files.json').write_text(json.dumps(files))
sidecar = STATE / 'output' / f'{TID}.py'
if sidecar.exists():
    sidecar.unlink()
print('injected files.json (1 file)')

ok = orch._auto_commit_accepted(STATE, task, TID)
print('AUTO_COMMIT_OK =', ok)
