#!/usr/bin/env python3
"""GAP-1 (Agent-4): the env-FSM PURE handlers have NO producer layer.

Thesis: c1/c2/c3 (and c4-c6) are PURE adjudicators over pre-staged input dicts
(detect_input / provision_input / jail_input / ...). The impure PRODUCER that
stages those dicts (real os.walk FS scan, jailed lockfile venv build, jail-argv
capture, service-start probe, reachability ping, baseline snapshot) is DEFERRED
to "the conductor seam" in EVERY brief but is planned NOWHERE. Neither doc carries
a producer-layer deliverable. Without producers the FSM is BUILT-not-WORKS: the
gate_executor can adjudicate, but nothing ever fills the evidence it adjudicates.

Empirical checks (all read-only):
 A. Is there any code in ngv2/ that PRODUCES an env-phase *_input dict or an
    env-phase content-hashed artifact (DetectArtifact / provision artifact / ...)?
 B. Does conductor_seams.build_evidence emit ANY env-phase evidence key?
 C. Do the docs enumerate a producer/conductor-seam deliverable for the env states?
"""
import os
import re
import subprocess
import sys

NGV2 = "/home/xnihil0zer0/NobleGreedv2/ngv2"
DOCS = [
    "/home/xnihil0zer0/AI-Data/Research-JanusMask/NobleGreedv2-end2end-gap-analysis.md",
    "/home/xnihil0zer0/AI-Data/Research-JanusMask/NGv2-closure-deliverables-and-acceptance-contract.md",
]

def grep(pattern, root, flags="-rnE"):
    try:
        out = subprocess.run(["grep", flags, pattern, root, "--include=*.py"],
                             capture_output=True, text=True)
        return [l for l in out.stdout.splitlines() if "/test" not in l and "_test" not in l]
    except Exception as e:
        return [f"ERR {e}"]

print("=" * 78)
print("GAP-1: env-FSM PRODUCER LAYER — does anything STAGE the env-phase inputs?")
print("=" * 78)

print("\n[A] Code producing an env-phase *_input dict (assignment, not param):")
# A producer would ASSIGN detect_input = {...} or return a DetectArtifact.
prod = grep(r"(detect_input|provision_input|jail_input|health_input|reachability_input|baseline_input)\s*=", NGV2)
prod += grep(r"def (stage_detect|stage_provision|build_detect_input|make_detect_input|produce_.*_artifact|capture_jail_argv|scan_target_fs)", NGV2)
if prod:
    for l in prod: print("   PRODUCER FOUND:", l)
else:
    print("   *** ZERO producers found *** — no code stages any env-phase input dict")

print("\n[B] env-phase handler MODULES in NGv2 master (fsm_detect/provision/jail_build/...):")
for name in ("fsm_detect", "fsm_provision", "fsm_jail_build",
             "fsm_health_probe", "fsm_reachability_probe", "fsm_baseline_capture"):
    p = os.path.join(NGV2, name + ".py")
    print(f"   {name}.py: {'EXISTS' if os.path.exists(p) else 'ABSENT (not in master)'}")

print("\n[C] conductor_seams.build_evidence — does it emit ANY env-phase evidence key?")
cs = os.path.join(NGV2, "conductor_seams.py")
txt = open(cs).read()
m = re.search(r"def build_evidence\(.*?\n(.*?)\n    def ", txt, re.S)
body = m.group(1) if m else txt
env_keys = ("detect", "provision", "jail_build", "health_probe",
            "reachability_probe", "baseline_capture", "detect_result",
            "provision_result", "env_artifact")
hits = [k for k in env_keys if re.search(r"['\"]" + k, body)]
print("   env-phase evidence keys emitted by build_evidence:", hits or "NONE")
mc = re.search(r"_PHASE_COUNT_KEY\s*=\s*(\{[^}]*\})", txt)
print("   _PHASE_COUNT_KEY =", mc.group(1) if mc else "?")
print("   -> env phases counted by persist:",
      [k for k in env_keys if mc and k in mc.group(1)] or "NONE")

print("\n[D] Do EITHER doc enumerate a PRODUCER / conductor-seam staging deliverable")
print("    for the env states (the impure scan/build/probe that fills the input dicts)?")
prod_terms = re.compile(r"produce[rd]?|conductor[- ]seam.*(scan|build|probe|stage)|"
                        r"stag(e|ing) the (input|evidence|artifact)|impure (scan|producer)|"
                        r"populate.*(detect_input|provision_input|jail_input)|"
                        r"who (fills|stages|produces)", re.I)
for d in DOCS:
    t = open(d).read()
    hit = [ln for ln in t.splitlines() if prod_terms.search(ln)]
    print(f"   {os.path.basename(d)}: producer-deliverable lines = {len(hit)}")
    for h in hit[:4]:
        print("       >", h.strip()[:140])

print("\n[E] Brief-level confirmation the producer is DEFERRED, not planned:")
c1 = "/home/xnihil0zer0/JanusMaskJR/brief_hooks_p21_c1_fsm_detect.md"
if os.path.exists(c1):
    t = open(c1).read()
    for needle in ("INJECTED seam", "NEVER walks the filesystem", "supplied as DATA",
                   "conductor seam that runs the impure scan", "DEFERRED"):
        print(f"   c1 brief says '{needle}': {'YES' if needle in t else 'no'}")

print("\nVERDICT: env-FSM producer layer is",
      "ABSENT and UNPLANNED" if not prod else "present")
