#!/usr/bin/env python3
"""SCRIPT 4 -- verify the disk-reaper motivating example.

For cleanup_state / reap_stale_disk / _reconcile_stale_ledger_heads, count
NON-TEST / NON-SCRATCH / NON-ARCHIVE in-repo callers (a bare-name reference
outside the defining module's own def, and outside tests) at:
  (1) the land commit (state of repo right after each was added), and
  (2) HEAD now.
A 'live caller' here = any reference in harness/** or services/** etc. EXCEPT
tests/ and the defining file itself and scratch/archive.
"""
import subprocess
from pathlib import Path

REPO = Path('/home/xnihil0zer0/JanusMaskJR')
DEFMOD = 'harness/state_reconciler.py'
SYMS = {
    'cleanup_state': 'fe8e9c3',
    'reap_stale_disk': 'b03a2cd',
    '_reconcile_stale_ledger_heads': '44efd58',
    # control: a reaper the brief says IS live-wired
    'reap_orphaned_workdirs': 'b03a2cd',
}
EXCLUDE_PREFIX = ('tests/', '_autowork_scratch/', '_archive/', '_autowork_archive/',
                  'samples/', 'venv/', 'scripts/')


def git(args):
    return subprocess.run(['git', *args], cwd=str(REPO), capture_output=True, text=True)


def callers_at(ref, sym):
    """List files at `ref` that reference `sym` outside tests/scratch/archive
    and outside the defining module. Uses git grep at that ref."""
    # word-boundary grep for the symbol used as a call: `sym(` (a reference/call)
    out = git(['grep', '-l', '-E', r'\b' + sym + r'\s*\(', ref, '--', '*.py'])
    hits = []
    for line in out.stdout.splitlines():
        # format: <ref>:<path>
        if ':' not in line:
            continue
        path = line.split(':', 1)[1]
        if path == DEFMOD:
            continue
        if any(path.startswith(p) for p in EXCLUDE_PREFIX):
            continue
        # also drop test_* basenames anywhere
        bn = path.rsplit('/', 1)[-1]
        if bn.startswith('test_') or bn.endswith('_test.py'):
            continue
        hits.append(path)
    return sorted(set(hits))


for sym, land in SYMS.items():
    print(f'=== {sym}  (landed {land}) ===')
    at_land = callers_at(land, sym)
    at_head = callers_at('HEAD', sym)
    print(f'  non-test/non-scratch callers AT LAND ({land}): {at_land or "NONE"}')
    print(f'  non-test/non-scratch callers AT HEAD        : {at_head or "NONE"}')
    print()
