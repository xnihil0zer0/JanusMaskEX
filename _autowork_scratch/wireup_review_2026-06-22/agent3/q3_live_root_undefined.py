#!/usr/bin/env python3
"""Q3: Is 'LIVE_ROOT' (as the gate would drive it) DEFINED?

Two distinct notions of LIVE_ROOT exist:
  (A) harness/wire_up.py:LIVE_ROOTS -- a FIXED 4-entry list, used by check_wired
      for MODULE import-reachability. WELL-DEFINED but module-level only.
  (B) the briefs' per-symbol integration_contract.entrypoints -- a PLANNER-
      AUTHORED free-text list the Phase-2 gate reads. The brief's coverage rule
      (Impl Note 2) is: a callable is 'contract-covered' iff exempt OR
      `_entrypoints is non-empty`. It does NOT validate the named entrypoint is a
      real LIVE_ROOT, nor that the symbol is reachable-by-call from it.

This script proves notion (B) is effectively UNDEFINED/UNVALIDATED: any
non-empty list -- even a bogus path, even garbage -- suppresses the report.
The 'observable_effect' and 'runtime_oracle' fields are read by NOTHING.
"""
import sys
from pathlib import Path
REPO = Path('/home/xnihil0zer0/JanusMaskJR')
sys.path.insert(0, str(REPO))
from harness.wire_up import LIVE_ROOTS

def coverage_decision(task, new_syms):
    """The EXACT 'contract-covered' rule from the Phase-2 brief (Impl Note 2)."""
    _c = task.get('constraints') if isinstance(task.get('constraints'), dict) else {}
    _contract = _c.get('integration_contract') if isinstance(_c.get('integration_contract'), dict) else {}
    _entrypoints = _contract.get('entrypoints') if isinstance(_contract.get('entrypoints'), list) else []
    _exempt_raw = task.get('wire_exempt') or _c.get('wire_exempt') or []
    _exempt = set(_exempt_raw) if isinstance(_exempt_raw, (list, tuple, set)) else set()
    uncovered = sorted(s for s in new_syms if s not in _exempt and not _entrypoints)
    return uncovered, _entrypoints

new_syms = ['brand_new']
print('Well-defined notion (A): harness/wire_up.py:LIVE_ROOTS =')
for r in LIVE_ROOTS:
    print(f'    {r}  (exists in repo? {(REPO / r).is_file()})')
print()
print('Notion (B): the per-symbol integration_contract.entrypoints the gate reads.')
print('Testing the brief\'s coverage rule against various entrypoint declarations:\n')

cases = [
    ('real LIVE_ROOT', {'constraints': {'integration_contract': {'entrypoints': ['harness/orchestrator.py']}}}),
    ('BOGUS path (does not exist)', {'constraints': {'integration_contract': {'entrypoints': ['totally/made/up.py']}}}),
    ('GARBAGE string', {'constraints': {'integration_contract': {'entrypoints': ['xyzzy']}}}),
    ('non-LIVE_ROOT module', {'constraints': {'integration_contract': {'entrypoints': ['harness/wire_up.py']}}}),
    ('empty entrypoints (no contract)', {'constraints': {'integration_contract': {'entrypoints': []}}}),
    ('no contract at all', {}),
]
for label, task in cases:
    uncovered, eps = coverage_decision(task, new_syms)
    covered = (uncovered == [])
    flagged = bool(uncovered)
    print(f'  entrypoints={eps!r:45}  -> covered(suppresses report)={covered}  flagged={flagged}   [{label}]')

print()
print('CONCLUSION: any NON-EMPTY entrypoints list suppresses the report regardless')
print('of whether it names a real LIVE_ROOT. The brief (Non-Goals) explicitly says')
print('per-symbol contract mapping and validating the entrypoint are OUT OF SCOPE.')
print('There is NO production reader that checks entrypoints against LIVE_ROOTS,')
print('checks the symbol is reachable-by-call, or checks runtime_oracle exists.')
