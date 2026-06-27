"""DEMO 3 — Phase 2 accept gate: the integration_contract is a SELF-CERTIFIED
declaration. Declaring a non-empty `entrypoints` list (with ANY string in it)
suppresses the orphan report for a genuine orphan -- the gate never verifies the
symbol is actually reachable from that entrypoint.

We feed the EXACT same orphan addition with three task dicts:
  (A) no contract, no exempt            -> reported (correct)
  (B) wire_exempt: ['orphan_symbol']    -> suppressed
  (C) integration_contract.entrypoints  -> suppressed, with a BOGUS/UNRELATED
       entrypoint string and an observable_effect that is pure fiction.
The gate cannot tell (C) from a real contract.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from wire_up_phase2_gate import run_phase2_symbol_branch

PARENT = "def already():\n    return 0\n"
CHILD = (
    "def already():\n    return 0\n\n"
    "def orphan_symbol():\n    return 1\n"   # brand-new orphan, zero callers
)

cases = {
    "A: no contract, no exempt": {},
    "B: wire_exempt orphan_symbol": {"constraints": {"wire_exempt": ["orphan_symbol"]}},
    "C: BOGUS integration_contract": {"constraints": {"integration_contract": {
        "entrypoints": ["harness/orchestrator.py"],   # never actually wired
        "observable_effect": "totally made up; nothing real calls orphan_symbol",
        "runtime_oracle": "tests/harness/test_anything.py",
    }}},
    "C': contract entrypoints=['x']": {"constraints": {"integration_contract": {
        "entrypoints": ["literally_anything"],
    }}},
}

print("=== DEMO 3: Phase 2 accept gate -- integration_contract is self-certified ===")
print(f"CHILD adds genuine orphan `orphan_symbol` (zero callers in any source).\n")
for label, task in cases.items():
    new_syms, uncovered = run_phase2_symbol_branch(task, PARENT, CHILD)
    row = bool(uncovered)
    verdict = "REPORTED orphan_symbol_unwired" if row else "NO ROW -> gate accepts as 'wired'"
    print(f"[{label}]")
    print(f"   new_top_level_callables = {new_syms}")
    print(f"   uncovered (would-report) = {uncovered}")
    print(f"   => {verdict}")
    print()

print("VERDICT: Adding constraints.integration_contract.entrypoints=[<any string>]")
print("         (case C / C') SUPPRESSES the orphan report for a genuine orphan.")
print("         The gate verifies only that a NON-EMPTY entrypoints list was DECLARED;")
print("         it never confirms orphan_symbol is reachable from that entrypoint.")
print("         The contract is planner/brief-authored prose -- a self-attestation,")
print("         not a proof. This is the answer-key-leak shape one layer up: the same")
print("         actor that must satisfy the gate also writes the field that satisfies it.")
