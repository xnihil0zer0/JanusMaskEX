#!/usr/bin/env python3
"""
AGENT-2 / s2 — Test the doc's RELIES-ON-NOOP risk: §5 gate #5 (wire-up /
reachability from a live root, inherited by EVERY contract) and the X13/X14
portability bars.

The contract leans on the wire-up gate to *guarantee* NGv2 wiring (§5.5,
P1.3/P3.1 wire-up clauses: "assert a non-test importer"). But:
  - the MODULE gate (check_wired) self-reconciles via discover_live_roots → portable;
  - the per-SYMBOL static floor (symbol_reachable_from_live_root) is hardcoded to
    JM LIVE_ROOTS and the orchestrator passes NO roots= → on an external NGv2 tree
    with no JM roots present, EVERY symbol looks orphaned (the doc's own X13).

This script empirically demonstrates the floor's behavior on:
  (1) a clean external fixture whose helper IS reached from a __main__ entry,
      with DEFAULT JM roots  → expect floor==False (FALSE POSITIVE = the no-op);
  (2) the same fixture with the fixture's own root passed as roots= → expect True;
  (3) a true zero-caller orphan → expect False either way.

Also checks the live runtime-gate flag and the orchestrator's floor call site.
"""
import os
import subprocess
import sys
import tempfile

JM = "/home/xnihil0zer0/JanusMaskJR"
sys.path.insert(0, JM)
from harness.wire_up import symbol_reachable_from_live_root, LIVE_ROOTS  # noqa

print("=" * 72)
print("s2: wire-up per-symbol static floor portability (X13 / §5.5 RELIES-ON-NOOP)")
print("=" * 72)
print(f"JM LIVE_ROOTS (hardcoded default): {LIVE_ROOTS}")

# Build a clean external fixture tree (mimics an external NGv2-style target:
# NO harness/orchestrator.py etc. present).
fix = tempfile.mkdtemp(prefix="s2_extfix_")
os.makedirs(os.path.join(fix, "pkg"))
open(os.path.join(fix, "pkg", "__init__.py"), "w").close()
# helper IS reached from a __main__-guarded entry
with open(os.path.join(fix, "pkg", "util.py"), "w") as f:
    f.write("def helper():\n    return 42\n")
with open(os.path.join(fix, "entry.py"), "w") as f:
    f.write(
        "from pkg.util import helper\n"
        "def main():\n    return helper()\n"
        "if __name__ == '__main__':\n    main()\n"
    )
# a genuine zero-caller orphan
with open(os.path.join(fix, "pkg", "dead.py"), "w") as f:
    f.write("def orphan_never_called():\n    return 0\n")

print(f"\nExternal fixture root: {fix}")
print("  pkg/util.py::helper  -- reached from entry.py __main__")
print("  pkg/dead.py::orphan_never_called -- zero callers")

# (1) DEFAULT JM roots (what the orchestrator actually passes: no roots=)
try:
    r1 = symbol_reachable_from_live_root(fix, "pkg/util.py", "helper")
except Exception as e:
    r1 = f"EXC:{type(e).__name__}:{e}"
print(f"\n(1) helper, DEFAULT JM roots (orchestrator behavior): floor={r1}")
print("    expected for a CORRECT portable gate: True (it IS wired).")
print(f"    >>> {'FALSE POSITIVE (the no-op the doc warns of)' if r1 is False else 'OK/other'}")

# (2) fixture's own root passed explicitly
try:
    r2 = symbol_reachable_from_live_root(fix, "pkg/util.py", "helper", roots=["entry.py"])
except Exception as e:
    r2 = f"EXC:{type(e).__name__}:{e}"
print(f"\n(2) helper, roots=['entry.py'] (target-derived root): floor={r2}")

# (3) true orphan, both ways
try:
    r3a = symbol_reachable_from_live_root(fix, "pkg/dead.py", "orphan_never_called")
    r3b = symbol_reachable_from_live_root(fix, "pkg/dead.py", "orphan_never_called", roots=["entry.py"])
except Exception as e:
    r3a = r3b = f"EXC:{type(e).__name__}:{e}"
print(f"\n(3) orphan, DEFAULT roots: floor={r3a}   roots=['entry.py']: floor={r3b}")

# Live config + orchestrator call-site facts
print("\n--- live config / call-site facts ---")
cfg = open(f"{JM}/harness/config.yaml").read()
for line in cfg.splitlines():
    s = line.strip()
    if s.startswith(("wire_up_gate:", "wire_up_runtime_gate:", "wire_up_runtime_gate_enforce:")):
        print("  config:", s)
# does the orchestrator pass roots= into the floor?
orch = open(f"{JM}/harness/orchestrator.py").read()
calls = [l.strip() for l in orch.splitlines() if "symbol_reachable_from_live_root(" in l and "import" not in l]
print("  orchestrator floor call sites:")
for c in calls:
    print("    ", c)
    print("       passes roots=:", "roots=" in c)

print("\n=== VERDICT ===")
if r1 is False and r2 is True:
    print(">>> X13 is STILL RED: with default JM roots the floor false-positives a")
    print(">>> genuinely-wired external symbol as orphan; only an explicit target-")
    print(">>> derived root fixes it, and the orchestrator passes NO roots=.")
    print(">>> => §5 gate #5 / P1.3 / P3.1 'assert a non-test importer' acceptance")
    print(">>>    CANNOT be enforced by the per-symbol floor on external NGv2.")
print(f"\n(fixture left at {fix} for inspection)")
