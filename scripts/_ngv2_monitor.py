#!/usr/bin/env python3
"""Stream NGv2 Epic-1 child outcomes from the ledger; exit when all 3 land or on hard failure."""
import json, os, sys, time

LEDGER = 'state/impl_progress.jsonl'
TASKS = {'ngv2_contracts_impl', 'ngv2-state-machine', 'ngv2-detonation-chamber'}
GOOD = {'auto_commit'}
BAD = {'reject', 'reject_rollback', 'blocked', 'spawn_failed', 'worker_exit_nonzero', 'escalation'}
NOTE = {'dispatch', 'task_claim', 'worker_exit', 'reject_rollback'}
WATCH = GOOD | BAD | NOTE

seen = set()
accepted = set()
deadline = time.time() + 3300  # ~55 min
# prime: skip rows already present at start so we only see NEW events
start_len = 0
if os.path.exists(LEDGER):
    with open(LEDGER) as f:
        for _ in f:
            start_len += 1

while time.time() < deadline:
    try:
        with open(LEDGER) as f:
            rows = f.readlines()
    except OSError:
        time.sleep(5); continue
    for i, line in enumerate(rows[start_len:], start=start_len):
        try:
            d = json.loads(line)
        except Exception:
            continue
        tid = d.get('task_id'); ev = d.get('event')
        if tid in TASKS and ev in WATCH:
            key = f'{i}'
            if key in seen:
                continue
            seen.add(key)
            phase = d.get('phase', '')
            detail = str(d.get('detail', ''))[:80]
            print(f'{ev.upper():16} {tid:24} phase={phase} {detail}', flush=True)
            if ev in GOOD:
                accepted.add(tid)
            if ev in BAD:
                print(f'!!! HARD FAILURE on {tid} ({ev}) — daemon needs attention', flush=True)
    if accepted >= TASKS:
        print(f'ALL 3 CHILDREN ACCEPTED: {sorted(accepted)}', flush=True)
        sys.exit(0)
    time.sleep(20)

print(f'MONITOR TIMEOUT — accepted so far: {sorted(accepted)}', flush=True)
sys.exit(0)
