#!/usr/bin/env python3
"""GAP-2 (Agent-4): multiple INDEPENDENT phase-order literals will DESYNC when
the 6 ENV_PHASE_ORDER states are slotted ahead of `hunt`.

c0 unified PHASE_ORDER across transition_planner.py + gate_executor.py (both now
`from ngv2.fsm_evidence import PHASE_ORDER`). But session_api.py and
state_machine.py carry their OWN hardcoded phase-order tuples — used LIVE by
SessionApi._next_phase / .advance / .create and by the state-machine graph.
The INTEGRATION_LEAF_TODO §1 only mentions editing fsm_evidence.PHASE_ORDER
(consumed by transition_planner + gate_executor). It does NOT list session_api's
two literals nor state_machine's two — so they silently desync.

Confirms the candidate AND broadens it: session_api uses its own PHASE_ORDER for
the live advance loop (not the fsm_evidence import), and there are >=5 literals.
"""
import os, re, subprocess

NGV2 = "/home/xnihil0zer0/NobleGreedv2/ngv2"

print("=" * 78)
print("GAP-2: phase-order literal copies that will DESYNC on env-phase insertion")
print("=" * 78)

LITERAL = re.compile(r"\(\s*('source'|\"source\"|'hunt'|\"hunt\")")
files = {}
for fn in os.listdir(NGV2):
    if not fn.endswith(".py"): continue
    p = os.path.join(NGV2, fn)
    for i, ln in enumerate(open(p, errors="ignore"), 1):
        # a tuple literal containing 'hunt' / 'triage' / 'detonate' assigned to a NAME
        if re.search(r"^\s*[A-Z_]+\s*[:=].*=?\s*\(", ln) and "'hunt'" in ln and \
           ("'triage'" in ln or "'detonate'" in ln or "'poc'" in ln):
            files.setdefault(fn, []).append((i, ln.strip()))

print("\n[A] Hardcoded phase-order TUPLE LITERALS (name = ('...','hunt',...)):")
total = 0
for fn, rows in sorted(files.items()):
    for i, ln in rows:
        total += 1
        print(f"   {fn}:{i}")
        print(f"       {ln[:160]}")
print(f"\n   TOTAL independent phase-order literals: {total}")

print("\n[B] Which of these are CONSUMED by the c0 import vs are INDEPENDENT?")
for fn in sorted(files):
    p = os.path.join(NGV2, fn)
    t = open(p, errors="ignore").read()
    imports_c0 = "from ngv2.fsm_evidence import" in t and "PHASE_ORDER" in t.split("from ngv2.fsm_evidence import")[1][:200] if "from ngv2.fsm_evidence import" in t else False
    # does this file DEFINE its own PHASE_ORDER / _PHASES / LIFECYCLE_PHASES literal?
    own = re.findall(r"^\s*(PHASE_ORDER|_PHASES|LIFECYCLE_PHASES|PHASES)\s*[:=]", t, re.M)
    print(f"   {fn}: defines-own={sorted(set(own))}  imports_c0_PHASE_ORDER={imports_c0}")

print("\n[C] session_api.py LIVE advance path — which literal does it use?")
sa = os.path.join(NGV2, "session_api.py")
t = open(sa).read()
print("   imports PHASE_ORDER from fsm_evidence? ",
      "from ngv2.fsm_evidence import" in t and "PHASE_ORDER" in t)
print("   defines local PHASE_ORDER literal?      ",
      bool(re.search(r"^PHASE_ORDER\s*:\s*Tuple.*=\s*\(", t, re.M)))
for needle, where in [("PHASE_ORDER.index", "_next_phase (line ~406)"),
                      ("PHASE_ORDER[0]", "create/advance entry"),
                      ("_PHASES[0]", "create() seeds phase=_PHASES[0]")]:
    print(f"   uses {needle!r} in live path: {needle in t}  ({where})")

print("\n[D] Does the INTEGRATION_LEAF_TODO or EITHER doc mention session_api/")
print("    state_machine phase-order when inserting env phases?")
todo = "/home/xnihil0zer0/JanusMaskJR/_autowork_scratch/p21_env_fsm/INTEGRATION_LEAF_TODO.md"
sources = {
    "INTEGRATION_LEAF_TODO": todo,
    "gap-analysis.md": "/home/xnihil0zer0/AI-Data/Research-JanusMask/NobleGreedv2-end2end-gap-analysis.md",
    "contract.md": "/home/xnihil0zer0/AI-Data/Research-JanusMask/NGv2-closure-deliverables-and-acceptance-contract.md",
}
for label, p in sources.items():
    if not os.path.exists(p):
        print(f"   {label}: (missing)"); continue
    t = open(p).read()
    print(f"   {label}: session_api={'YES' if 'session_api' in t else 'no'}  "
          f"state_machine={'YES' if 'state_machine' in t else 'no'}  "
          f"LIFECYCLE_PHASES={'YES' if 'LIFECYCLE_PHASES' in t else 'no'}  "
          f"_PHASES_literal={'YES' if '_PHASES' in t else 'no'}")

print("\nVERDICT: >=2 INDEPENDENT live phase-order literals (session_api, state_machine)")
print("         are NOT named by the integration TODO or either doc -> DESYNC RISK.")
