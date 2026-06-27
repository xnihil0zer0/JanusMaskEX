#!/usr/bin/env python3
"""D1 — Does the external wire_up gate (check_wired) protect NGv2 modules?

Candidate divergence #1: the docs (master G13, contract P-WIREUP, contract §5
gate 5 "Wire-up / reachability ... no orphaned modules") rely on the wire-up
gate to guarantee NGv2 modules are reachable from a live root at accept. If the
gate no-ops (wired=True) on NGv2 targets regardless of reachability, an orphaned
NGv2 module lands green and the doc reliance is invalid.

This script runs the REAL harness check_wired() against the REAL NGv2 tree, both
for a genuinely-orphaned module and against the default JM LIVE_ROOTS, and
inspects discover_live_roots / the external_reconciled latch.
READ-ONLY: no edits anywhere.
"""
import sys, json
sys.path.insert(0, '/home/xnihil0zer0/JanusMaskJR')

from harness.wire_up import check_wired, discover_live_roots, LIVE_ROOTS
from harness.rebuild.discover import discover_modules

NGV2 = '/home/xnihil0zer0/NobleGreedv2'

print('=== D1: wire_up gate behavior on NGv2 ===')
print('JM default LIVE_ROOTS:', LIVE_ROOTS)
print()

# 1) Do any JM LIVE_ROOTS exist inside the NGv2 tree?
modules, tests, seeds = discover_modules(NGV2)
module_set = set(modules)
print('NGv2 discovered non-test modules:', len(module_set))
jm_roots_present = [r for r in LIVE_ROOTS if r in module_set]
print('JM LIVE_ROOTS present in NGv2 tree:', jm_roots_present)
print('-> seeded_roots from JM LIVE_ROOTS would be EMPTY:', len(jm_roots_present) == 0)
print()

# 2) What does discover_live_roots reconcile for NGv2?
recon = discover_live_roots(NGV2)
print('discover_live_roots(NGv2) count:', len(recon))
print('  sample:', recon[:12])
recon_in_set = [r for r in recon if r in module_set]
print('  reconciled roots actually in module_set:', len(recon_in_set))
print()

# 3) Pick a real NGv2 FSM handler module the brief left intentionally uncalled.
candidate = 'ngv2/fsm_evidence.py'
print(f'Test module (the c0 FSM scaffold, no run_hunt caller): {candidate}')
print('  in module_set:', candidate in module_set)

# 4) Run the REAL gate with the DEFAULT roots the orchestrator passes (no roots=).
res = check_wired(NGV2, candidate)
print()
print('check_wired(NGv2, fsm_evidence.py) default-roots result:')
print('  wired =', res.wired)
print('  reason=', res.reason[:240])
print()

# 5) Inspect the external_reconciled latch explicitly by re-deriving it.
seeded_default = {r for r in LIVE_ROOTS if r in module_set}
external_reconciled = not seeded_default
print('external_reconciled latch (no JM root in tree):', external_reconciled)
if external_reconciled:
    seeded_recon = {r for r in discover_live_roots(NGV2) if r in module_set}
    print('  -> reconciled seeded_roots count:', len(seeded_recon))
    print('  -> if reconciled set is EMPTY, gate no-ops wired=True (toolkit branch).')
    print('  -> if reconciled set is NON-empty, gate does a REAL BFS over those roots.')
print()

# 6) Now drive a GUARANTEED orphan: a synthetic module name that is in the set
#    but verify what happens for a truly zero-importer module. Use a module that
#    discover sees but has no inbound importer & is not a root.
importers = {}
from harness.wire_up import _resolved_graph
graph = _resolved_graph(NGV2, list(module_set))
from collections import defaultdict
imap = defaultdict(set)
for m, deps in graph.items():
    for d in deps:
        imap[d].add(m)
zero_importer_mods = [m for m in sorted(module_set)
                      if m not in imap and m not in recon_in_set][:5]
print('Sample NGv2 modules with ZERO inbound importers and not a root:')
for m in zero_importer_mods:
    r = check_wired(NGV2, m)
    print(f'  {m}: wired={r.wired}  ({r.reason[:90]})')
print()

print('=== VERDICT ===')
if external_reconciled and not {r for r in discover_live_roots(NGV2) if r in module_set}:
    print('CONFIRMED no-op: NGv2 has no reconcilable root -> gate returns wired=True blindly.')
else:
    print('Gate does a REAL BFS on reconciled roots; no-op branch NOT taken for NGv2.')
    print('BUT note: wire-up checks IMPORT reachability, NOT call/invocation reachability.')
    print('A module imported transitively (e.g. fsm_jail_build imports fsm_evidence which')
    print('transition_planner imports) passes wire-up even if NO run_hunt code path CALLS')
    print('its handler -> the deliverable lands green while being functionally orphaned.')
