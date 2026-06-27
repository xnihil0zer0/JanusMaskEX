"""Real-path validation: PTY backend in PLANNING mode must produce + harvest
outbox/plan_draft.json (the bug: hardcoded submission.py -> claude draft hung)."""
import os, time, json
from pathlib import Path
from harness import orchestrator as orch

cfg = orch.load_config()
assert orch._use_tmux_claude('claude', cfg)
os.environ['JANUSMASK_TASK_ID'] = 'pty-planning-validate'
os.environ['JANUSMASK_MODE'] = 'planning'
os.environ.pop('JANUSMASK_WORKING_DIR', None)

prompt = (
    'You are a planning agent. Produce a minimal plan as a JSON object with a top-level '
    '"tasks" array containing one object with keys "task_id" (string) and "title" (string). '
    'Output only the JSON plan.'
)
print('[pp] spawning claude (PTY, planning mode)...')
t0 = time.time()
proc = orch.spawn_agent('claude', prompt, cfg, round_number=1)
art = orch.poll_for_submission('claude', Path(cfg.get('state_dir', 'state')), 1, proc, timeout=300)
dt = time.time() - t0
print(f'[pp] poll returned {("<%d chars>" % len(art)) if art else None} in {dt:.0f}s')
if art:
    try:
        d = json.loads(art); ok = isinstance(d.get('tasks'), list)
    except Exception:
        ok = False
    print('[pp] valid plan_draft JSON:', ok)
    print('[pp]', 'PASS' if ok else 'PARTIAL (harvested but not the expected JSON)')
else:
    print('[pp] FAIL: no plan_draft.json harvested (PTY planning still broken)')
