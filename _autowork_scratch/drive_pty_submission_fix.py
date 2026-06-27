"""Drive the harness/tmux_worker.py PTY-submission fix via .files.json injection.

Single-symbol change (spawn_claude_tmux) to a JM-self harness file. Builds a plan
from the retained PTY-rebuild template, stages, injects the corrected whole-file
(AST-merged by top-level name -> only spawn_claude_tmux changes + the new
_PTY_SUBMISSION_DIRECTIVE constant added), then runs the harness auto-commit
(apply -> wire_up gate -> verification of the committed oracle -> commit to master).
"""
import json, glob, os
from pathlib import Path
from harness.planner.staging import stage_task
from harness import orchestrator as orch

STATE = Path('state')
TID = 'tmux-worker-pty-submission-fix'
PLAN = Path(f'state/plans/plan_hooks_{TID}.json')

# Build the plan from the retained template, patched for this fix.
tmpl = json.load(open('state/plans/plan_hooks_tmux-worker-pty-rebuild.json'))
t = tmpl['tasks'][0]
t['task_id'] = TID
t['title'] = 'Fix harness/tmux_worker.py: PTY claude must write outbox/submission.py (no submit channel)'
t['files_touched'] = ['harness/tmux_worker.py']
t['acceptance_criteria'] = [
    'spawn_claude_tmux appends a mandatory submission directive naming outbox/submission.py and the Write tool to the prompt file.',
    'spawn_claude_tmux passes deliverable=<work_dir>/outbox/submission.py to run_pty_worker and persists its TmuxWorkerResult/snapshot under state_dir/sessions.',
    'The headless/agy paths and all other symbols are unchanged.',
    'All tests in tests/harness/test_tmux_worker.py pass.',
]
t['verification_command'] = 'python -m pytest tests/harness/test_tmux_worker.py -q'
t['spec']['objective'] = (
    'Append a load-bearing submission directive to the interactive-claude prompt so it writes '
    'outbox/submission.py (its only delivery channel), and persist the worker snapshot for diagnosis.'
)
tmpl['working_dir'] = None
PLAN.write_text(json.dumps(tmpl, indent=2))
print('wrote plan', PLAN)

# fresh state for this TID
for pat in (f'state/tasks/{TID}.json', f'state/output/{TID}.*'):
    for p in glob.glob(pat):
        os.remove(p)
for p in glob.glob(f'state/sessions/*_{TID}_*'):
    os.remove(p)

stage_task(PLAN, TID, STATE, working_dir=None)
task = json.load(open(f'state/tasks/{TID}.json'))
print('staged; working_dir =', task.get('working_dir'), '| meta_task_type =', task.get('meta_task_type'))

files = {'harness/tmux_worker.py': Path('_autowork_scratch/tmux_worker_fix_ref.py').read_text()}
(STATE / 'output' / f'{TID}.files.json').write_text(json.dumps(files))
sidecar = STATE / 'output' / f'{TID}.py'
if sidecar.exists():
    sidecar.unlink()
print('injected files.json (1 file); .py sidecar removed:', not sidecar.exists())

ok = orch._auto_commit_accepted(STATE, task, TID)
print('AUTO_COMMIT_OK =', ok)
