#!/usr/bin/env python3
"""D4 — Trust-of-landed (diff-fuzz dormancy) + operational drift the docs miss.

Candidate #3 (second half): is differential fuzzing DORMANT (bypassed) so some
'landed' deliverables passed without a real equivalence check?
Candidate #4: operational drift — backend tmux->headless flip; targets relocated.

READ-ONLY: only reads the ledger, config, README, and the answer-key-fix commit ts.
"""
import json, subprocess, os
from datetime import datetime, timezone

JM = '/home/xnihil0zer0/JanusMaskJR'
LEDGER = f'{JM}/state/impl_progress.jsonl'

print('=== D4a: differential-fuzz dormancy check (refute or confirm) ===')
# Count fuzz events + fuzz_results in the last N rows, and look at recent accepts.
fuzz_events = {}
accept_rows = []
fuzz_result_files = 0
with open(LEDGER, 'rb') as f:
    try:
        f.seek(-6_000_000, 2)
    except OSError:
        f.seek(0)
    tail = f.read().decode('utf-8', 'ignore').splitlines()
for line in tail:
    try:
        row = json.loads(line)
    except Exception:
        continue
    ev = row.get('event', '')
    if 'fuzz' in ev:
        fuzz_events[ev] = fuzz_events.get(ev, 0) + 1
    if ev == 'auto_commit' and row.get('phase') == 'accepted':
        accept_rows.append(row.get('task_id', '?'))
print('Fuzz-related ledger events (last ~tail window):')
for k, v in sorted(fuzz_events.items()):
    print(f'   {k}: {v}')
print('Recent accepts (last window):', len(accept_rows))

# Read the fuzz_results dir: real fuzz runs write per-task round files.
frdir = f'{JM}/logs/fuzz_results'
files = sorted(os.listdir(frdir)) if os.path.isdir(frdir) else []
print(f'fuzz_results files on disk: {len(files)}')
# Show how many recent ones report a REAL run (total_inputs > 0) vs skipped.
real_runs = skipped = 0
recent = sorted(files, key=lambda x: os.path.getmtime(os.path.join(frdir, x)), reverse=True)[:20]
for fn in recent:
    try:
        d = json.load(open(os.path.join(frdir, fn)))
    except Exception:
        continue
    if d.get('skipped_reason'):
        skipped += 1
    elif (d.get('total_inputs') or 0) > 0:
        real_runs += 1
print(f'Of last {len(recent)} fuzz_results: {real_runs} REAL runs (total_inputs>0), {skipped} skipped/bypassed.')
print()

print('=== D4b: answer-key-fix landing time vs which deliverables landed ===')
def commit_ts(sha):
    out = subprocess.run(['git', '-C', JM, 'show', '-s', '--format=%ct', sha],
                         capture_output=True, text=True)
    return int(out.stdout.strip()) if out.stdout.strip().isdigit() else None
fix_ts = commit_ts('3f9af36')  # answer-key value-leak close
print('answer-key value-leak fix (3f9af36) committed:',
      datetime.fromtimestamp(fix_ts, timezone.utc).isoformat() if fix_ts else '?')
# How many NGv2 closure commits landed BEFORE the fix (built under the leak)?
ng = '/home/xnihil0zer0/NobleGreedv2'
log = subprocess.run(['git', '-C', ng, 'log', '--format=%ct %h %s', '-60'],
                     capture_output=True, text=True).stdout.splitlines()
before = after = 0
for l in log:
    parts = l.split(' ', 2)
    if len(parts) < 3 or not parts[0].isdigit():
        continue
    ts = int(parts[0])
    if any(k in parts[2].lower() for k in ('p11', 'p12', 'p21', 'loopback', 'fsm', 'detonation', 'authenticity')):
        if fix_ts and ts < fix_ts:
            before += 1
        else:
            after += 1
print(f'NGv2 closure-related commits BEFORE the value-leak fix: {before}')
print(f'NGv2 closure-related commits AFTER  the value-leak fix: {after}')
print('-> deliverables landed BEFORE were built while the VERBATIM-VALUE leak was live.')
print()

print('=== D4c: operational drift — backend config vs README ===')
cfg = open(f'{JM}/harness/config.yaml').read()
import re
m = re.search(r'claude_backend:\s*(\w+)', cfg)
print('config.yaml LIVE claude_backend:', m.group(1) if m else '?')
readme = open(f'{JM}/README.md').read()
print('README says backend "currently **`tmux`**":', "currently **`tmux`**" in readme)
print('README config block shows "claude_backend: tmux":', 'claude_backend: tmux' in readme)
print('-> DRIFT:', (m.group(1) if m else '?'), 'live, but README documents tmux.')
print()

print('=== D4d: operational drift — hunt targets relocated ===')
tdir = f'{ng}/targets'
print('targets/ dir exists at NGv2:', os.path.isdir(tdir))
if os.path.isdir(tdir):
    entries = [e for e in os.listdir(tdir) if not e.startswith('.')]
    print('  target corpus dirs:', len(entries), '->', entries[:8])
# Does either planning doc reference a targets/ HUNT convention (vs only pollution)?
for doc in ['NobleGreedv2-end2end-gap-analysis.md',
            'NGv2-closure-deliverables-and-acceptance-contract.md']:
    p = f'/home/xnihil0zer0/AI-Data/Research-JanusMask/{doc}'
    txt = open(p).read()
    hunt_conv = 'targets/' in txt and ('clone' in txt.lower() or 'corpus' in txt.lower())
    print(f'  {doc}: mentions targets/ as a hunt-corpus location? {"targets/" in txt} '
          f'(only-as-pollution: {"pollution" in txt or "_SKIP_DIRS" in txt})')
