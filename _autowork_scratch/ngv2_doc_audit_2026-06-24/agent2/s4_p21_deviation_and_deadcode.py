#!/usr/bin/env python3
"""
AGENT-2 / s4 — P2.1 DECOMPOSITION DEVIATION + still-valid dead-code bars.

(A) DEVIATION-UNACCOUNTED: the contract's P2.1 lists 6 child contracts c1..c6,
    each a "state_machine brief with a pure decision fn + oracle", and an EPIC
    wire-up bar: "the FSM front half is reachable from run_hunt (replaces the
    implicit 'skip to hunt')". Actual development (MEMORY) split the children into
    DISJOINT PURE HANDLERS with live-FSM wiring DEFERRED to a later integration
    leaf — and that integration leaf is NOT in the doc's task list. Demonstrate the
    env-FSM scaffold (ENV_PHASE_ORDER, advance_gate) is ORPHANED and run_hunt still
    skips to 'hunt'.

(B) Still-valid: P3.1 auth_bootstrap + sink_instrument remain 0-importer dead code
    (those acceptance preconditions still hold) — confirm so the report can mark
    them verified-still-valid.
"""
import subprocess
NGV2 = "/home/xnihil0zer0/NobleGreedv2"

def importers(name):
    out = subprocess.run(
        ["grep", "-rln", name, f"{NGV2}/ngv2/", "--include=*.py"],
        capture_output=True, text=True).stdout.strip().splitlines()
    return [p for p in out if "test" not in p]

print("=" * 72)
print("s4 (A): P2.1 env-FSM decomposition DEVIATION — scaffold orphaned, run_hunt")
print("        still skips to 'hunt' (the EPIC wire-up bar is NOT met)")
print("=" * 72)
env_consumers = importers("ENV_PHASE_ORDER")
ag_consumers = importers("advance_gate")
print(f"  ENV_PHASE_ORDER consumers (non-test, non-self): "
      f"{[c for c in env_consumers if not c.endswith('fsm_evidence.py')]}")
print(f"  advance_gate (env-FSM gate) consumers (non-self): "
      f"{[c for c in ag_consumers if not c.endswith('fsm_evidence.py')]}")
rh = open(f"{NGV2}/ngv2/run_hunt.py").read()
init = [l.strip() for l in rh.splitlines() if "_INITIAL_PHASE" in l and "=" in l]
print(f"  run_hunt _INITIAL_PHASE: {init}")
print(f"  run_hunt mentions detect/provision/env-FSM: "
      f"{any(w in rh for w in ('detect', 'provision', 'ENV_PHASE', 'env_readiness'))}")

# which P2.1 children actually landed?
print("\n  P2.1 child commits landed (git):")
out = subprocess.run(["git", "-C", NGV2, "log", "--oneline", "--all", "--grep", "p21"],
                     capture_output=True, text=True).stdout.strip()
print("    " + (out.replace("\n", "\n    ") if out else "(none)"))
print("  => only c0 scaffold + c3 oracle present; c1/c2/c4/c5/c6 NOT landed;")
print("     env-FSM gate code exists but is wired to NOTHING; run_hunt skips to hunt.")
print("  => doc's P2.1 'EPIC ☐' is dir-correct, but it omits (i) the deviation that")
print("     children are pure handlers w/ wiring deferred and (ii) a REQUIRED")
print("     integration leaf to actually reach the EPIC wire-up acceptance bar.")

print("\n" + "=" * 72)
print("s4 (B): P3.1 dead-code preconditions — STILL VALID")
print("=" * 72)
for sym in ("auth_bootstrap", "sink_instrument"):
    imp = [c for c in importers(sym) if not c.endswith(f"{sym}.py")]
    print(f"  {sym}: non-test/non-self importers = {imp or '(NONE — dead code, claim holds)'}")
