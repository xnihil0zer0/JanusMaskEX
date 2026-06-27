#!/usr/bin/env python3
"""D3 — Is the planner answer-key leak (a trust-of-landed risk) still active?

Candidate divergence #3: the docs treat 'landed' deliverables as trustworthy
(contract §1: pre-committed RED->GREEN oracle = done). The MEMORY note records
that `_inject_oracle_sources` pasted the VERBATIM committed-oracle source
(literals included) into task spec implementation_notes, letting the synthesis
agent game the oracle. Commit 3f9af36 (today) claimed to fix this.

This script runs the REAL `_inject_oracle_sources` against a REAL NGv2 oracle
(the c3 fsm_jail_build oracle) and shows EXACTLY what is injected now, to decide:
 (a) is the verbatim-source leak CLOSED? (no test BODY / assertion values)
 (b) does ANY answer-key signal remain (imports, signatures, terminal strings)?
READ-ONLY.
"""
import sys
sys.path.insert(0, '/home/xnihil0zer0/JanusMaskJR')
from harness.planner.plan_normalizer import _inject_oracle_sources

NGV2 = '/home/xnihil0zer0/NobleGreedv2'
ORACLE_REL = 'tests/ngv2/test_fsm_jail_build.py'

# Build a minimal impl-task plan whose vcmd names the real oracle.
plan = {
    'tasks': [
        {
            'task_id': 'p21-c3-fsm-jail-build-impl',
            'meta_task_type': 'validation',
            'verification_command': f'python -m pytest {ORACLE_REL} -q',
            'spec': {'implementation_notes': 'Build fsm_jail_build.'},
        }
    ]
}

out = _inject_oracle_sources(plan, NGV2)
notes = out['tasks'][0]['spec']['implementation_notes']

print('=== D3: what _inject_oracle_sources injects today (post 3f9af36) ===')
print('Injected block present:', 'COMMITTED ORACLE CONTRACT' in notes)
print('Injected block length (chars):', len(notes))
print()

# Read the raw oracle to compare what is leaked vs withheld.
raw = open(f'{NGV2}/{ORACLE_REL}').read()

# 1) Does the injected block contain the verbatim assertion VALUES?
#    Pick load-bearing answer-key tokens from the raw oracle.
answer_key_tokens = [
    "'jail_unavailable'",      # the typed terminal value the impl must emit
    "--unshare-net",            # required isolation flag asserted
    "--unshare-ipc",
    "--unshare-pid",
    "'jail_build'",             # artifact['phase'] expected value
    "/home/user/repo",          # a fixture literal
]
print('--- Answer-key VALUE tokens: present in raw oracle vs in injected notes ---')
leaked = []
for tok in answer_key_tokens:
    in_raw = tok in raw
    in_notes = tok in notes
    flag = 'LEAKED' if in_notes else 'withheld'
    if in_notes:
        leaked.append(tok)
    print(f'  {tok!r:24} raw={in_raw}  injected={in_notes}  -> {flag}')
print()

# 2) Does the injected block contain any test-function BODY / assert statements?
print('--- Test BODY leakage check ---')
print('  injected contains the word "assert":', 'assert' in notes)
print('  injected contains "def test_":', 'def test_' in notes)
print('  injected contains "..." stub bodies:', '...' in notes)
print()

# 3) What DOES remain (structure)?
print('--- Sample of the injected block (first 1400 chars) ---')
start = notes.find('COMMITTED ORACLE CONTRACT')
print(notes[start:start+1400])
print()

print('=== VERDICT ===')
if leaked:
    print(f'PARTIAL LEAK REMAINS: {len(leaked)} answer-key VALUE token(s) still injected: {leaked}')
else:
    print('VALUE-LEAK CLOSED: no assertion values injected; only redacted structure (imports/signatures).')
print('Verbatim-source paste:', 'STILL PRESENT' if 'assert' in notes else 'REMOVED (bodies replaced by "...")')
