"""ITEM 6 -- DISPATCH READINESS (mechanical, secondary).

Phase-3's impl task as written (brief frontmatter + Deliverables TASK 2) edits
BOTH harness/orchestrator.py (via __JANUSMASK_PATCHES__) AND harness/config.yaml
(via __JANUSMASK_MANIFEST__) in ONE task. Question: can a single pipeline task
legitimately emit both a .patches.json and a .files.json sidecar?

Empirically exercise the REAL submission-write path
(orchestrator._save_final_output) and the REAL apply-dispatch logic
(git_integration.commit_accepted_output, lines 864-872) to answer it."""
import inspect
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/home/xnihil0zer0/JanusMaskJR")
import harness.orchestrator as orch
import harness.git_integration as gi

print("=== ITEM 6: dispatch readiness for the Phase-3 two-channel impl task ===\n")

# ---------------------------------------------------------------------------
# FACT 1: a single submission `code` file has ONE top-level __JANUSMASK_*__
# block, and _save_final_output writes EITHER .files.json OR .patches.json --
# mutually exclusive (if manifest is not None: ... else: patches = ...).
# ---------------------------------------------------------------------------
src = inspect.getsource(orch._save_final_output)
print("--- harness/orchestrator.py:_save_final_output (the submission-write path) ---")
for ln in src.splitlines():
    s = ln.strip()
    if ('_parse_manifest' in s or 'files.json' in s or 'patches.json' in s
            or '_parse_patches' in s or s.startswith('if manifest') or s.startswith('else:')
            or 'patches = ' in s):
        print("   " + s)
print()

# Empirically drive it with a MANIFEST submission and a PATCHES submission and
# show exactly one sidecar lands each time.
def _drive(code, tid):
    tmp = tempfile.mkdtemp(prefix="item6_")
    sd = Path(tmp) / "state"
    (sd / "output").mkdir(parents=True)
    orch._save_final_output(sd, tid, code)
    out = sd / "output"
    files_json = (out / f"{tid}.files.json").exists()
    patches_json = (out / f"{tid}.patches.json").exists()
    import shutil; shutil.rmtree(tmp, ignore_errors=True)
    return files_json, patches_json

manifest_code = "__JANUSMASK_MANIFEST__ = {\n    'harness/config.yaml': r'''autowork:\\n  wire_up_gate: true\\n''',\n}\n"
patches_code = "__JANUSMASK_PATCHES__ = [\n    {'file': 'harness/orchestrator.py', 'kind': 'symbol', 'name': 'baz', 'code': r'''def baz():\\n    return 3\\n'''},\n]\n"

fj1, pj1 = _drive(manifest_code, "T_MANIFEST")
fj2, pj2 = _drive(patches_code, "T_PATCHES")
print(f"manifest-only submission -> files.json={fj1}  patches.json={pj1}")
print(f"patches-only  submission -> files.json={fj2}  patches.json={pj2}")
one_each = (fj1 and not pj1) and (pj2 and not fj2)
print(f"  => a single submission yields EXACTLY ONE sidecar (mutually exclusive): {one_each}")
print()

# A submission cannot even CONTAIN both a __JANUSMASK_MANIFEST__ and a
# __JANUSMASK_PATCHES__ top-level block validly: the submission file "MUST
# contain ONLY this assignment at top level". Show _parse_manifest wins and
# patches is never parsed when manifest is present.
both_code = manifest_code + patches_code
fj3, pj3 = _drive(both_code, "T_BOTH")
print(f"hypothetical both-blocks submission -> files.json={fj3}  patches.json={pj3}")
print(f"  => even if a worker emitted both blocks, only the MANIFEST sidecar is written")
print(f"     (_save_final_output: 'if manifest is not None: <files.json> else: <patches.json>')")
print()

# ---------------------------------------------------------------------------
# FACT 2: the APPLY/commit path also dispatches on a SINGLE channel -- it reads
# .patches.json FIRST and RETURNS, never reaching .files.json.
# ---------------------------------------------------------------------------
csrc = inspect.getsource(gi.commit_accepted_output)
print("--- harness/git_integration.py:commit_accepted_output (the apply dispatch) ---")
emit = False
for ln in csrc.splitlines():
    s = ln.strip()
    if 'patches_sidecar = ' in s or 'patches_sidecar.exists' in s or '_commit_accepted_output_patches' in s \
       or "sidecar_path = state_dir / 'output' / f'{task_id}.files.json'" in s \
       or 'sidecar_path.exists' in s or '_commit_accepted_output_multi' in s:
        print("   " + s)
print()
print("OBSERVATION: commit_accepted_output checks patches_sidecar.exists() FIRST and")
print("RETURNS _commit_accepted_output_patches(...) before it ever checks .files.json.")
print("So even two sidecars on disk would NOT both apply -- the patches channel wins,")
print("config.yaml manifest would be silently dropped.")
print()

# ---------------------------------------------------------------------------
# VERDICT
# ---------------------------------------------------------------------------
print("=" * 70)
print("ITEM 6 VERDICT: a single pipeline task CANNOT emit both a .patches.json and")
print("a .files.json that both apply. The submission carries ONE __JANUSMASK_*__")
print("block; _save_final_output writes ONE sidecar (manifest XOR patches); and")
print("commit_accepted_output applies ONE channel (patches first, returning).")
print("Therefore Phase-3 TASK 2 as written (orchestrator.py via __JANUSMASK_PATCHES__")
print("AND config.yaml via __JANUSMASK_MANIFEST__ in ONE task) is a DISPATCH HAZARD:")
print("the worker can only submit ONE of the two channels, so either the config.yaml")
print("change OR the orchestrator.py change is dropped -> the task fails at apply time")
print("(or lands incomplete). RECOMMEND splitting Phase-3 into two impl tasks:")
print("  (2a) orchestrator.py enforce arm via __JANUSMASK_PATCHES__")
print("  (2b) config.yaml two-knob add via __JANUSMASK_MANIFEST__")
print("Code path: orchestrator._save_final_output (XOR sidecar write) +")
print("git_integration.commit_accepted_output:~864-872 (patches-first dispatch).")
ok = one_each and fj3 and not pj3
sys.exit(0 if ok else 1)
