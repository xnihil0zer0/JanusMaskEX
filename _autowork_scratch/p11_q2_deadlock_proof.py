"""Q2 DEADLOCK PROOF.

Build the MINIMAL run_gates that SATISFIES the committed abstract oracle
(gates named 'structural'/'pre_existing', FULL_EVIDENCE={'structural':True,'pre_existing':True}),
then drive it with the LIVE build_evidence output AND the Task-3 candidate output
and show whether `advance` is ever True on real evidence.

We synthesize the abstract run_gates from the oracle's literal contract:
  - PHASE_ORDER has 11 phases.
  - every consecutive transition is gated on the two keys structural+pre_existing.
  - run_gates(frm,to,{}) -> advance False ; missing key -> gate omitted from results.
  - advance True iff both keys present & truthy.
This is exactly what makes the 8-passing abstract candidate green.

No exec/eval/compile/__import__: we DEFINE the abstract run_gates in THIS file
(it is the trivial implementation the abstract oracle pins), then import the
LIVE/candidate build_evidence via importlib spec.loader.exec_module.
"""
import importlib.util
import json
import os
import sys

NGV2 = "/home/xnihil0zer0/NobleGreedv2"
sys.path.insert(0, NGV2)


def load_module(modname, path):
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


# ---- The ABSTRACT run_gates that passes the committed oracle 8/8 -------------
PHASE_ORDER = ("source", "hunt", "triage", "verify", "poc",
               "detonate", "novelty", "report", "awaiting_submission",
               "submitted", "done")
_CONSEC = {(PHASE_ORDER[i], PHASE_ORDER[i + 1]) for i in range(len(PHASE_ORDER) - 1)}
_ABSTRACT_GATES = ("structural", "pre_existing")


def abstract_run_gates(frm, to, evidence):
    """Minimal run_gates satisfying the abstract oracle."""
    if (frm, to) not in _CONSEC:
        return {"transition": f"{frm}->{to}", "advance": True, "results": {}}
    results = {}
    advance = True
    for g in _ABSTRACT_GATES:
        if g in evidence and bool(evidence[g]):
            results[g] = True
        else:
            advance = False
    return {"transition": f"{frm}->{to}", "advance": advance, "results": results}


# Sanity: this satisfies the key oracle assertions.
assert abstract_run_gates("source", "hunt", {})["advance"] is False
assert abstract_run_gates("source", "hunt", {"structural": True, "pre_existing": True})["advance"] is True
assert abstract_run_gates("source", "triage", {})["advance"] is True  # non-consecutive
print("abstract_run_gates satisfies oracle's core asserts: OK")

# ---- LIVE build_evidence ----------------------------------------------------
cs = load_module("ngv2_conductor_seams_live", os.path.join(NGV2, "ngv2", "conductor_seams.py"))


class FakeDB:
    def __init__(self, row):
        self._row = row
    def get_session(self, sid):
        return dict(self._row)
    def save_session(self, sid, state):
        self._row = dict(state)


def states_for_each_phase():
    """A realistic-as-possible carried-forward state per phase."""
    base_findings = [{"id": "f1", "title": "SQLi", "sink_name": "execute",
                      "call_sites": ["execute(q)"]}]
    out = {}
    for ph in PHASE_ORDER:
        out[ph] = {
            "phase": ph,
            "repo": None,
            "prior_findings": base_findings,
            "artifacts": [],
            "evidence": {},
            "approval": "approved" if ph == "awaiting_submission" else None,
            "submission_result": {"ok": True} if ph == "submitted" else None,
        }
    return out


seams = cs.build_default_seams("sid", FakeDB({}), None, {})
live_be = seams["build_evidence"]

# Task-3 candidate build_evidence
cand_mod = load_module("p11_be_candidate2",
                       "/home/xnihil0zer0/JanusMaskJR/state/output/p11-build-evidence-structural-keys.py")
tmp = "/home/xnihil0zer0/JanusMaskJR/_autowork_scratch/_cand_be_tmp2.py"
with open(tmp, "w") as fh:
    fh.write(cand_mod.__JANUSMASK_PATCHES__[0]["code"])
_cand_be_mod = load_module("_cand_be_tmp2_mod", tmp)
cand_be = _cand_be_mod.build_evidence


def next_phase(ph):
    i = PHASE_ORDER.index(ph)
    return PHASE_ORDER[i + 1] if i + 1 < len(PHASE_ORDER) else None


phase_states = states_for_each_phase()

print("\n=== DRIVE abstract run_gates with LIVE build_evidence (per consecutive transition) ===")
any_advance_live = False
for ph in PHASE_ORDER[:-1]:
    to = next_phase(ph)
    ev = live_be(phase_states[ph])
    g = abstract_run_gates(ph, to, ev)
    print(f"  {ph}->{to}: advance={g['advance']:<5}  ev_keys={sorted(ev.keys())}")
    any_advance_live = any_advance_live or g["advance"]
print("  ANY consecutive transition advanced with LIVE build_evidence:", any_advance_live)

print("\n=== DRIVE abstract run_gates with Task-3 CANDIDATE build_evidence ===")
any_advance_cand = False
for ph in PHASE_ORDER[:-1]:
    to = next_phase(ph)
    ev = cand_be(phase_states[ph])
    g = abstract_run_gates(ph, to, ev)
    print(f"  {ph}->{to}: advance={g['advance']:<5}  ev_keys={sorted(ev.keys())}")
    any_advance_cand = any_advance_cand or g["advance"]
print("  ANY consecutive transition advanced with CANDIDATE build_evidence:", any_advance_cand)

print("\n=== VERDICT Q2 ===")
print("structural/pre_existing keys emitted by LIVE build_evidence:",
      [k for k in ("structural", "pre_existing") if k in live_be(phase_states["hunt"])])
print("structural/pre_existing keys emitted by CANDIDATE build_evidence:",
      [k for k in ("structural", "pre_existing") if k in cand_be(phase_states["hunt"])])
print("=> If abstract run_gates is wired live, EVERY consecutive transition DEADLOCKS"
      " (advance never True) because no build_evidence emits structural/pre_existing.")
