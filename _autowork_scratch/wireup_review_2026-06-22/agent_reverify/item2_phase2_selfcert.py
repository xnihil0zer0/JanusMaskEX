"""ITEM 2 -- PHASE-2 SELF-CERT NOW FAILS against the REVISED coverage rule.

Re-runs agent3/q3 (and demo3) self-cert attacks against the REVISED
compute_uncovered (per-symbol + entrypoints must be in LIVE_ROOTS + a
runtime_oracle declared). A new callable `brand_new` is added to an
already-tracked module. We assert which contracts SUPPRESS the report
(uncovered empty) vs leave it REPORTED (uncovered contains 'brand_new')."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, "/home/xnihil0zer0/JanusMaskJR")

from revised_gate import compute_uncovered
from harness.wire_up import LIVE_ROOTS

PARENT = "def already():\n    return 0\n"
CHILD = "def already():\n    return 0\ndef brand_new():\n    return 1\n"

REAL_LR = LIVE_ROOTS[0]  # derive, never hardcode

cases = [
    # (label, task, expect_reported)  -- expect_reported True == 'brand_new' STILL reported
    ("agent3/q3 (a): entrypoints=['xyzzy'] (garbage)",
     {'constraints': {'integration_contract': {'entrypoints': ['xyzzy']}}}, True),
    ("agent3/q3 (b): bogus non-LIVE_ROOT path",
     {'constraints': {'integration_contract': {'entrypoints': ['totally/made/up.py']}}}, True),
    ("non-LIVE_ROOT module (harness/wire_up.py)",
     {'constraints': {'integration_contract': {'entrypoints': ['harness/wire_up.py']}}}, True),
    ("(c) real LIVE_ROOT but NO symbols + NO oracle (old blanket rule passed this)",
     {'constraints': {'integration_contract': {'entrypoints': [REAL_LR]}}}, True),
    ("(d) valid LIVE_ROOT+oracle but symbol NOT named (per-symbol miss)",
     {'constraints': {'integration_contract': {'entrypoints': [REAL_LR], 'symbols': ['some_other'], 'runtime_oracle': 'tests/harness/test_x.py'}}}, True),
    ("VALID per-symbol contract (entrypoint in LIVE_ROOTS, symbol named, oracle declared)",
     {'constraints': {'integration_contract': {'entrypoints': [REAL_LR], 'symbols': ['brand_new'], 'runtime_oracle': 'tests/harness/test_x.py'}}}, False),
    ("wire_exempt brand_new",
     {'constraints': {'wire_exempt': ['brand_new']}}, False),
    ("no contract at all (baseline -- must be reported)",
     {}, True),
    ("real LIVE_ROOT + symbol named but NO runtime_oracle (oracle required)",
     {'constraints': {'integration_contract': {'entrypoints': [REAL_LR], 'symbols': ['brand_new']}}}, True),
]

print("=== ITEM 2: Phase-2 self-cert now fails (revised per-symbol LIVE_ROOT rule) ===")
print(f"LIVE_ROOTS = {LIVE_ROOTS}")
print(f"child adds top-level orphan 'brand_new' to already-tracked module\n")

allok = True
for label, task, expect_reported in cases:
    new_syms, uncovered, valid = compute_uncovered(task, PARENT, CHILD)
    reported = 'brand_new' in uncovered
    ok = (reported == expect_reported)
    allok = allok and ok
    verdict = "REPORTED unwired" if reported else "SUPPRESSED (covered)"
    print(f"[{'PASS' if ok else 'FAIL'}] {label}")
    print(f"        contract_valid={valid} uncovered={uncovered} -> {verdict} (expected reported={expect_reported})")

print()
print(f"ITEM 2 OVERALL: {'PASS -- self-cert defeated; only valid per-symbol LIVE_ROOT contract or exempt suppresses' if allok else 'FAIL'}")
sys.exit(0 if allok else 1)
