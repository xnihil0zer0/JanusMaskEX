#!/usr/bin/env python3
"""Analytic reproduction of the p11-gate-table-typed-terminals auto_commit_failed.

Runs the EXACT harness commit-apply path against:
  - the candidate's __JANUSMASK_MANIFEST__ entry for ngv2/gate_executor.py
    (extracted from state/output/<task>.py / the submission sidecar), and
  - the LIVE on-disk ngv2/gate_executor.py at NobleGreedv2 HEAD (c9eb4e1).

Goal: prove WHAT specifically fails. The ledger shows the commit SUCCEEDED
(commit_sha=743a2ff) but the verification_command then died with
  NameError: name '_STRUCTURAL_TRANSITIONS' is not defined
i.e. the auto_commit_failed label is a MISLABEL — the real failure is that the
AST merge produced an IMPORT-BROKEN module (a Frankenstein of old + new symbols).

We reproduce _apply_file_to_target -> _ast_merge for the gate_executor entry,
then ast-parse the merged result, list its top-level symbols, and try to
import-compile it to surface the NameError.

Run: PYTHONPATH=/home/xnihil0zer0/JanusMaskJR python3 \
        /home/xnihil0zer0/JanusMaskJR/_autowork_scratch/diag_p11_gatetable.py
"""
import ast
import pathlib
import sys

JM = pathlib.Path("/home/xnihil0zer0/JanusMaskJR")
NGV2 = pathlib.Path("/home/xnihil0zer0/NobleGreedv2")
sys.path.insert(0, str(JM))

from harness.git_integration import _ast_merge  # noqa: E402
from harness.orchestrator import _parse_manifest  # noqa: E402


def top_level_symbols(code: str) -> set[str]:
    syms: set[str] = set()
    for n in ast.parse(code).body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            syms.add(n.name)
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            syms.add(n.target.id)
        elif isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    syms.add(t.id)
    return syms


def free_names_referenced(code: str) -> set[str]:
    """Module-level Names that are LOADED at module-exec time but never bound
    at the top level (a proxy for the import-time NameError)."""
    tree = ast.parse(code)
    bound = top_level_symbols(code)
    # also count imports as bound
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                bound.add((a.asname or a.name).split(".")[0])
        elif isinstance(n, ast.ImportFrom):
            for a in n.names:
                bound.add(a.asname or a.name)
    # collect Names loaded at module level inside module-level Assign values and
    # function-call args at module scope (the _build_transition_gates() call site)
    referenced: set[str] = set()
    for n in tree.body:
        for sub in ast.walk(n):
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
                referenced.add(sub.id)
    return referenced - bound


def main() -> None:
    out_sidecar = JM / "state" / "output" / "p11-gate-table-typed-terminals.py"
    candidate_full = out_sidecar.read_text(encoding="utf-8")

    manifest = _parse_manifest(candidate_full)
    print("=" * 70)
    print("STEP 1 — submission channel")
    print("=" * 70)
    print(f"_parse_manifest recognised it as a manifest: {manifest is not None}")
    if manifest is None:
        print("NOT a manifest — would have gone through patches/singular path")
        return
    print(f"manifest keys: {list(manifest.keys())}")

    gate_key = "ngv2/gate_executor.py"
    out_code = manifest[gate_key]
    live = NGV2 / "ngv2" / "gate_executor.py"
    tgt_code = live.read_text(encoding="utf-8")

    print()
    print("=" * 70)
    print("STEP 2 — symbol inventories BEFORE merge")
    print("=" * 70)
    cand_syms = top_level_symbols(out_code)
    live_syms = top_level_symbols(tgt_code)
    print(f"CANDIDATE top-level symbols ({len(cand_syms)}): {sorted(cand_syms)}")
    print(f"LIVE      top-level symbols ({len(live_syms)}): {sorted(live_syms)}")

    print()
    print("=" * 70)
    print("STEP 3 — reproduce _ast_merge (the multi-file _apply_file_to_target path)")
    print("=" * 70)
    try:
        merged = _ast_merge(out_code, tgt_code)
    except Exception as exc:
        print(f"_ast_merge RAISED: {type(exc).__name__}: {exc}")
        return
    merged_syms = top_level_symbols(merged)
    print(f"MERGED top-level symbols ({len(merged_syms)}): {sorted(merged_syms)}")

    cand_only = cand_syms - live_syms
    print()
    print(f"Symbols the CANDIDATE introduces (cand - live): {sorted(cand_only)}")
    dropped = cand_only - merged_syms
    print(f"  ... of those, DROPPED by the merge (not in result): {sorted(dropped)}")
    kept_old = live_syms - cand_syms
    print(f"Symbols only in LIVE that the merge KEPT: "
          f"{sorted(kept_old & merged_syms)}")

    print()
    print("=" * 70)
    print("STEP 4 — does the merged module import/compile? (the REAL failure)")
    print("=" * 70)
    unbound = free_names_referenced(merged)
    # filter to names that look like the gate helpers / structural table
    interesting = {n for n in unbound if n.startswith("_") or n[0:1].isupper()}
    print(f"Module-level LOADED names NOT bound at top level: {sorted(unbound)}")

    # Try the actual import the verification_command did.
    tmp = JM / "_autowork_scratch" / "_merged_gate_executor_repro.py"
    tmp.write_text(merged, encoding="utf-8")
    print(f"\nMerged module written to: {tmp}")
    print("Attempting exec() at module scope (mimics import) ...")
    g: dict = {}
    # Stub the four ngv2 gate imports so the import line itself doesn't mask the
    # real NameError we are hunting.
    import types
    for mod in ("ngv2", "ngv2.poc_authenticity_gate", "ngv2.detonation_evidence_gate",
                "ngv2.sink_presence_gate", "ngv2.sink_reachability_gate"):
        m = types.ModuleType(mod)
        for fn in ("classify_poc_authenticity", "classify_detonation_evidence",
                   "verify_sink_present", "assess_sink_reachability"):
            setattr(m, fn, lambda *a, **k: {"may_confirm": True})
        sys.modules[mod] = m
    try:
        exec(compile(merged, str(tmp), "exec"), g)
        print("  -> exec SUCCEEDED (no import-time error)")
    except Exception as exc:
        print(f"  -> exec FAILED: {type(exc).__name__}: {exc}")
        print("\n  *** THIS is the verification_failed root cause "
              "(mislabeled auto_commit_failed). ***")


if __name__ == "__main__":
    main()
