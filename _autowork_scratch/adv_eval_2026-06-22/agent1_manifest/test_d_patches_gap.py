"""(d) GAP HUNT: does the stray-key drop cover the PATCHES sidecar path?

Two probes:
  d1: _validate_submission on a __JANUSMASK_PATCHES__ submission whose entries
      target an UNDECLARED file. Validator never checks patch entry 'file' against
      files_touched (only manifest path has the drop). So validation does NOT catch it.
  d2: commit-apply: _commit_accepted_output_patches enforces membership via
      _enforce_apply_scope and HARD-FAILS (committed=False, scope violation) on a
      stray patch file -- with NO _restrict_sidecar_to_declared equivalent. We prove
      this by calling _enforce_apply_scope directly (the exact gate the patches path
      uses at git_integration.py:1579) with the same allowed_files the orchestrator
      passes (set(files_touched)).
"""
import sys, os, json, tempfile, pathlib
sys.path.insert(0, "/home/xnihil0zer0/JanusMaskJR")
from harness.orchestrator import _validate_submission, _restrict_sidecar_to_declared
from harness.git_integration import _enforce_apply_scope

PATCH_BODY = "def f(x):\n    return x + 1\n"

def patches_code(entries):
    return "__JANUSMASK_PATCHES__ = " + repr(entries) + "\n"

# ---- d1: validator passes a patches submission with an undeclared file entry ----
task = {
    "files_touched": ["harness/target_bootstrap.py"],
    "partial_edit": True,
    "meta_task_type": "harness_self_fix",
    "constraints": {"deterministic": False},
}
code = patches_code([
    {"file": "harness/target_bootstrap.py", "kind": "symbol", "name": "f", "code": PATCH_BODY},
    {"file": "config/target_bootstrap.yaml", "kind": "region", "marker": "X", "code": "k: v\n"},  # STRAY, non-py region
])
ok, viol = _validate_submission(code, "claude", task)
rules = sorted({getattr(v, "rule", None) for v in viol})
print("=== d1: validator on patches w/ stray undeclared file ===")
print("ok:", ok, "rules:", rules)
print("D1_validator_ignores_stray_patch_file:", ok is True)  # no manifest_undeclared_key style check

# ---- d2: the commit-time scope gate hard-fails the stray patch file ----
# This is exactly what _commit_accepted_output_patches calls per-entry at line 1579,
# with allowed_files = set(files_touched).
allowed = {"harness/target_bootstrap.py"}
err_declared = _enforce_apply_scope(["harness/target_bootstrap.py"], allowed_files=allowed,
                                    meta_task_type="harness_self_fix", approval_ok=True,
                                    sensitive_globs=(), widened_auto_approve=True)
err_stray = _enforce_apply_scope(["config/target_bootstrap.yaml"], allowed_files=allowed,
                                 meta_task_type="harness_self_fix", approval_ok=True,
                                 sensitive_globs=(), widened_auto_approve=True)
print("=== d2: commit-time apply-scope gate (patches path uses this) ===")
print("err_declared (should be None):", err_declared)
print("err_stray (should be a scope violation):", err_stray)
print("D2_stray_patch_HARD_FAILS_at_commit:", err_declared is None and err_stray is not None)

# ---- d3: prove _restrict_sidecar_to_declared is NEVER applied to a .patches.json ----
# It only no-ops/[] on a JSON list (the patches sidecar format), AND grep proves the
# call site is files.json only. Here: feed it a patches-shaped sidecar (a JSON list).
tmp = pathlib.Path(tempfile.mkdtemp(prefix="adv_d_"))
pj = tmp / "task.patches.json"
pj.write_text(json.dumps([
    {"file": "harness/target_bootstrap.py", "kind": "symbol", "name": "f", "code": PATCH_BODY},
    {"file": "config/target_bootstrap.yaml", "kind": "region", "marker": "X", "code": "k: v\n"},
]))
before = pj.read_bytes()
dropped = _restrict_sidecar_to_declared(pj, ["harness/target_bootstrap.py"])
after = pj.read_bytes()
print("=== d3: restrict helper on a patches-shaped (list) sidecar ===")
print("dropped:", dropped, "bytes_unchanged:", before == after)
print("D3_helper_cannot_restrict_patches:", dropped == [] and before == after)
