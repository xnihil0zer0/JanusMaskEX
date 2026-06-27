#!/usr/bin/env python3
"""D2 — Are the P2.1 env-FSM handlers actually wired into run_hunt?

Candidate divergence #2: the docs (contract P2.1, master §7 Wave 2) describe the
env-readiness FSM front half (DETECT->...->BASELINE-CAPTURE) as the headline
deliverable whose wire-up requirement is "the FSM front half is reachable from
run_hunt (replaces the implicit skip-to-hunt)". If the c0..c6 children were built
as PURE disjoint handlers with live-FSM wiring DEFERRED, then run_hunt never
calls them: they land green (import-reachable) but are functionally orphaned.

This script greps the live conductor path for any CALL of the landed FSM
handlers, and inspects the c3 brief's own Non-Goals to confirm wiring was
DELIBERATELY deferred. READ-ONLY.
"""
import subprocess, os

NGV2 = '/home/xnihil0zer0/NobleGreedv2'
JM = '/home/xnihil0zer0/JanusMaskJR'

def grep(pat, path):
    try:
        out = subprocess.run(['grep', '-rn', pat, path], capture_output=True, text=True, cwd=NGV2)
        return [l for l in out.stdout.splitlines() if l.strip()]
    except Exception as e:
        return [f'ERR {e}']

print('=== D2: are env-FSM handlers called by the live run_hunt conductor? ===')
print()

# 1) Which FSM handler modules/symbols landed?
fsm_symbols = ['fsm_evidence', 'jail_build_gate', 'fsm_jail_build',
               'phase_artifact_hash', 'advance_gate', 'ENV_PHASE_ORDER']
print('Landed FSM handler symbols to trace:', fsm_symbols)
print()

# 2) The LIVE conductor path files (what run_hunt actually executes).
live_path = ['ngv2/run_hunt.py', 'ngv2/transition_planner.py',
             'ngv2/conductor_seams.py', 'ngv2/gate_executor.py',
             'ngv2/workers']
print('--- References to FSM handlers in the LIVE conductor path ---')
for f in live_path:
    full = os.path.join(NGV2, f)
    if not os.path.exists(full):
        print(f'  {f}: (missing)')
        continue
    hits = []
    for sym in ['jail_build_gate', 'fsm_jail_build', 'fsm_detect',
                'fsm_provision', 'fsm_health', 'fsm_reach', 'fsm_baseline',
                'ENV_PHASE_ORDER']:
        h = grep(sym, f)
        hits += h
    print(f'  {f}: {len(hits)} handler-CALL references')
    for h in hits[:4]:
        print('      ', h[:120])
print()

# 3) Distinguish IMPORT-reachability (wire-up passes) from CALL-reachability.
print('--- fsm_evidence is imported by (passes wire-up via import graph): ---')
imp = grep('fsm_evidence', 'ngv2/')
for l in imp:
    if 'import' in l.lower():
        print('   ', l[:130])
print()
print('--- but is any FSM-state GATE invoked in the phase loop? ---')
# The phase order / worker_phases drive what run_hunt actually runs.
po = grep('PHASE_ORDER', 'ngv2/transition_planner.py')
print('   transition_planner PHASE_ORDER lines:')
for l in po[:6]:
    print('     ', l[:130])
wp = grep('worker_phases\|AGENT_PHASES', 'ngv2/')
print('   worker/agent phase definitions:')
for l in wp[:6]:
    print('     ', l[:130])
print()

# 4) Confirm the brief deliberately DEFERRED wiring.
brief = os.path.join(JM, 'brief_hooks_p21_c3_fsm_jail_build.md')
if os.path.exists(brief):
    txt = open(brief).read()
    print('--- c3 brief Non-Goals: did it DEFER live-FSM wiring? ---')
    for needle in ['DEFERRED to a single later integration leaf',
                   'Do NOT insert `jail_build` into the live `PHASE_ORDER`',
                   'live-FSM wiring is a SEPARATE later integration leaf']:
        print(f'   [{("YES" if needle in txt else "no"):3}] "{needle[:60]}..."')
print()

print('=== VERDICT ===')
print('If the live-path files show 0 handler-CALL references AND the brief')
print('explicitly defers wiring -> CONFIRMED DECOMP-DEVIATION: the FSM handlers')
print('land green via IMPORT reachability but run_hunt never CALLS them. The doc')
print('wire-up clause ("reachable from run_hunt") is satisfied vacuously by the')
print('import edge, not by a real invocation -> BUILT, not WORKS.')
