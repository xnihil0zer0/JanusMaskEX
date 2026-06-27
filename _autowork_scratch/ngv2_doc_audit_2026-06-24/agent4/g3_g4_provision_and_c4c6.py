#!/usr/bin/env python3
"""GAP-3 + GAP-4 (Agent-4):

GAP-3: NGv2-side reactive/un-jailed pip installer is STILL reactive. The contract
(P0.2) only landed the JM side (target_bootstrap); the NGv2 counterpart
poc_runner_live._default_pip_installer (MAX_DEP_INSTALL_ROUNDS reactive loop,
HOST-SIDE network install) is unbuilt. P2.1-c2 PROVISION "depends on P0.2" but
c2 is a PURE adjudicator — it cannot itself run a jailed lockfile install. So the
*runner-side* jailed-install rewrite is a distinct missing prerequisite.

GAP-4: c4/c5/c6 briefs + the FSM INTEGRATION/WIRING leaf are unplanned. Confirm
no JM brief exists for fsm_health_probe / fsm_reachability_probe /
fsm_baseline_capture, nor for the integration leaf; and that neither doc lists the
integration/wiring step as a required deliverable (only c1-c6 pure handlers).
"""
import os, re, subprocess, glob

NGV2 = "/home/xnihil0zer0/NobleGreedv2/ngv2"
JM = "/home/xnihil0zer0/JanusMaskJR"
DOCS = {
    "gap-analysis": "/home/xnihil0zer0/AI-Data/Research-JanusMask/NobleGreedv2-end2end-gap-analysis.md",
    "contract": "/home/xnihil0zer0/AI-Data/Research-JanusMask/NGv2-closure-deliverables-and-acceptance-contract.md",
}

print("=" * 78)
print("GAP-3: NGv2-side poc_runner_live._default_pip_installer — still reactive/un-jailed?")
print("=" * 78)
prl = os.path.join(NGV2, "poc_runner_live.py")
t = open(prl).read()
# reactive loop present?
print("\n[A] reactive stderr-driven dep loop:")
for i, ln in enumerate(t.splitlines(), 1):
    if re.search(r"MAX_DEP_INSTALL_ROUNDS|for _round in range|_default_pip_installer|HOST-SIDE|Network available", ln):
        print(f"   :{i}: {ln.strip()[:120]}")
# is the install jailed (bwrap)? check the installer fn body specifically
m = re.search(r"def _default_pip_installer\(.*?\n(.*?)(?=\ndef |\Z)", t, re.S)
body = m.group(1) if m else ""
print("\n[B] _default_pip_installer body uses bwrap / --unshare-net / lockfile?")
print("   subprocess pip install present:", bool(re.search(r"pip['\"].*install|'install'", body)))
print("   bwrap in installer body:       ", "bwrap" in body)
print("   --unshare-net in installer:    ", "unshare-net" in body)
print("   lockfile/-r requirements:      ", bool(re.search(r"requirements|lockfile|-r ", body)))
print("   single attacker-named pkg arg: ", bool(re.search(r"install['\"].*name|--target.*name|, name\b", body)))
print("\n   -> STILL host-side reactive single-pkg install:",
      ("install" in body and "bwrap" not in body and "unshare-net" not in body))

print("\n[C] Does P0.2 / P2.1-c2 in the contract plan the poc_runner_live REWRITE")
print("    as its OWN task, or only reference it as a follow-on?")
ct = open(DOCS["contract"]).read()
for ln in ct.splitlines():
    if "poc_runner_live" in ln and ("_default_pip_installer" in ln or "MAX_DEP_INSTALL_ROUNDS" in ln or "follow-on" in ln or "separate" in ln):
        print("   contract:", ln.strip()[:160])
# Is there a JM brief for the NGv2 installer rewrite?
briefs = glob.glob(os.path.join(JM, "brief_hooks_*.md"))
inst_briefs = [b for b in briefs if re.search(r"pip|installer|provision|dep_install|lockfile", os.path.basename(b))]
print("\n[D] JM briefs for the NGv2 installer rewrite (poc_runner_live):",
      [os.path.basename(b) for b in inst_briefs] or "NONE")

print("\n" + "=" * 78)
print("GAP-4: c4/c5/c6 + FSM INTEGRATION leaf — any brief/plan? docs enumerate?")
print("=" * 78)
print("\n[E] JM briefs for c4/c5/c6 + integration:")
for slug in ("c4", "health_probe", "c5", "reachability", "c6", "baseline",
             "integration", "fsm_wire", "env_fsm_integrat"):
    hits = [os.path.basename(b) for b in briefs
            if re.search(slug, os.path.basename(b), re.I)]
    print(f"   brief matching '{slug}': {hits or 'NONE'}")
# also any plan_hooks for them
plans = glob.glob(os.path.join(JM, "plan_hooks_*.json"))
print("   plan_hooks matching health/reach/baseline/integration:",
      [os.path.basename(p) for p in plans if re.search(r"health|reach|baseline|integrat|c4|c5|c6", os.path.basename(p), re.I)] or "NONE")

print("\n[F] Allowlist — are c4/c5/c6/integration slugs admitted?")
allow = os.path.join(JM, "state/control/autowork/auto_promote.allowlist")
if os.path.exists(allow):
    at = open(allow).read()
    for slug in ("c1", "c2", "c3", "c4", "c5", "c6", "health", "reach", "baseline", "integrat"):
        ls = [l for l in at.splitlines() if slug in l and not l.strip().startswith("#")]
        if ls: print(f"   '{slug}' allowlisted:", ls)
    has45 = any(s in at for s in ("c4", "c5", "c6", "health_probe", "reachability_probe", "baseline_capture", "integrat"))
    print("   -> c4/c5/c6/integration in allowlist:", "YES" if has45 else "NO")
else:
    print("   (allowlist not found)")

print("\n[G] Do the docs enumerate the FSM INTEGRATION/WIRING leaf as a DELIVERABLE")
print("    (the step that inserts the 6 states into PHASE_ORDER/planner/gates/seams)?")
wire_terms = re.compile(r"integration leaf|wiring leaf|wire[- ]up leaf|insert.*PHASE_ORDER|"
                        r"_INITIAL_PHASE|thread.*into the.*conductor|integration epic|"
                        r"a (single |later )?integration", re.I)
for label, p in DOCS.items():
    tt = open(p).read()
    hits = [ln for ln in tt.splitlines() if wire_terms.search(ln)]
    print(f"   {label}: integration-leaf-as-deliverable lines = {len(hits)}")
    for h in hits[:3]: print("       >", h.strip()[:130])
# The contract's P2.1 only lists c1-c6 as children + a generic "Wire-up: reachable from run_hunt"
print("\n   contract P2.1 child contracts listed:",
      re.findall(r"P2\.1-c\d", ct))
print("   contract P2.1 lists a 7th INTEGRATION child? ",
      "YES" if re.search(r"P2\.1-c7|integration child|fsm_integration", ct) else "NO")
