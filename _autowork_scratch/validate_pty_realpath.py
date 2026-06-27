"""Real-path validation of the PTY-submission fix.

Drives the LIVE committed harness.orchestrator.spawn_agent -> _use_tmux_claude ->
spawn_claude_tmux -> poll_for_submission with a GENERIC worker prompt that does
NOT mention outbox/submission.py. If the fix works, spawn_claude_tmux appends the
deliverable directive, the real jailed interactive claude writes the file, and
poll_for_submission harvests it as the CLAUDE submission (no agy fallback).

Run: PYTHONPATH=. python _autowork_scratch/validate_pty_realpath.py
"""
from __future__ import annotations
import os, time
from pathlib import Path
from harness import orchestrator as orch

cfg = orch.load_config()
assert orch._use_tmux_claude('claude', cfg), 'workers.claude_backend must be tmux for this test'

os.environ['JANUSMASK_TASK_ID'] = 'pty-realpath-validate'
os.environ['JANUSMASK_MODE'] = 'synthesis'
os.environ.pop('JANUSMASK_WORKING_DIR', None)  # self-target

# Generic worker prompt -- deliberately says NOTHING about outbox/submission.py.
# The pre-fix prompt-contract was exactly this kind of "produce the code" text with
# no file directive; the fix must supply the directive itself.
prompt = (
    'You are a build worker. Implement a trivial Python module that defines a single '
    'function `add(a, b)` returning their sum, with a one-line docstring. Output the '
    'complete module source.'
)

print('[rp] spawning claude via real spawn_agent (PTY backend)...')
t0 = time.time()
proc = orch.spawn_agent('claude', prompt, cfg, round_number=1)
print(f'[rp] spawn_agent returned {type(proc).__name__} _work_dir={getattr(proc, "_work_dir", None)}')

code = orch.poll_for_submission('claude', Path(cfg.get('state_dir', 'state')), 1, proc, timeout=600)
dt = time.time() - t0
print(f'[rp] poll_for_submission returned {"<{} chars>".format(len(code)) if code else None} in {dt:.0f}s')
if code:
    print('[rp] --- submitted code (first 300 chars) ---')
    print(code[:300])
    print('[rp]', 'PASS' if 'def add' in code else 'PARTIAL (got code, no def add)')
else:
    print('[rp] FAIL: claude (PTY) produced no submission -> would fall back to agy')
