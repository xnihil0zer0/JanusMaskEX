"""Q1: What keys does the LIVE build_evidence emit, and does it feed run_gates directly?

We load the LIVE ngv2.conductor_seams module via importlib spec.loader.exec_module
(no exec/eval/compile/__import__), call build_default_seams with a fake db so we can
reach the nested build_evidence closure, then print the evidence keys for a
representative state. We also print the build-evidence CANDIDATE's emitted keys
(the staged Task-3 candidate) by exec_module-loading the candidate's symbol code.
"""
import importlib.util
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


# Minimal fake db so build_default_seams' closures are constructible.
class FakeDB:
    def __init__(self, row):
        self._row = row

    def get_session(self, sid):
        return dict(self._row)

    def save_session(self, sid, state):
        self._row = dict(state)


cs = load_module("ngv2_conductor_seams_live", os.path.join(NGV2, "ngv2", "conductor_seams.py"))

# Representative state: a hunt that produced findings, carried forward.
rep_state = {
    "phase": "hunt",
    "repo": None,
    "prior_findings": [
        {"id": "f1", "title": "SQLi", "sink_name": "execute", "call_sites": ["execute(q)"]}
    ],
    "artifacts": [],
    "evidence": {},
    "approval": None,
}

seams = cs.build_default_seams("sid", FakeDB(rep_state), None, {})
print("=== seam dict keys ===")
print(sorted(seams.keys()))

build_evidence = seams["build_evidence"]
ev = build_evidence(rep_state)
print("\n=== LIVE build_evidence(rep_state) KEYS ===")
print(sorted(ev.keys()))
print("\n=== LIVE build_evidence(rep_state) full ===")
import json
print(json.dumps({k: (v if not isinstance(v, str) or len(v) < 60 else v[:60]) for k, v in ev.items()}, default=str, indent=2))

# Confirm the run_gates seam is gate_executor.run_gates directly (no translation layer)
print("\n=== run_gates seam identity ===")
import ngv2.gate_executor as ge
print("seams['run_gates'] is gate_executor.run_gates:", seams["run_gates"] is ge.run_gates)
print("seams['build_evidence'] is the nested closure (not gate_executor):", build_evidence.__qualname__)

# Now show what the STAGED Task-3 build_evidence CANDIDATE would emit (per-phase keys)
print("\n=== STAGED build_evidence CANDIDATE keys (Task 3) ===")
cand_src = None
patches_path = "/home/xnihil0zer0/JanusMaskJR/state/output/p11-build-evidence-structural-keys.py"
cand_mod = load_module("p11_be_candidate", patches_path)
patches = cand_mod.__JANUSMASK_PATCHES__
code = patches[0]["code"]
# exec_module the candidate's build_evidence by writing to a temp module file.
tmp = "/home/xnihil0zer0/JanusMaskJR/_autowork_scratch/_cand_be_tmp.py"
with open(tmp, "w") as fh:
    fh.write(code)
cand_be = load_module("_cand_be_tmp_mod", tmp)
cand_ev = cand_be.build_evidence(rep_state)
print(sorted(cand_ev.keys()))
print(json.dumps(cand_ev, default=str, indent=2))
