#!/usr/bin/env python3
"""Analytic reproduction of the 3 'auto_commit_failed' blockers.

READ-ONLY: imports harness.git_integration._apply_symbol_patch and replays the
exact worker-emitted patches against the real target source. Captures the
precise exception (or success) for each, proving which failure mode applies.

Run:  PYTHONPATH=/home/xnihil0zer0/JanusMaskJR python3 _autowork_scratch/diag_auto_commit_failed.py
"""
import ast
import sys
import pathlib

sys.path.insert(0, "/home/xnihil0zer0/JanusMaskJR")
from harness.git_integration import _apply_symbol_patch, _parse_patches  # noqa: E402

JM = pathlib.Path("/home/xnihil0zer0/JanusMaskJR")
NG = pathlib.Path("/home/xnihil0zer0/NobleGreedv2")
OUT = JM / "state" / "output"


def _toplevel_def_assign_names(src: str):
    """Names of TOP-LEVEL def/class/assign in src (what _apply_symbol_patch 1-part search sees)."""
    tree = ast.parse(src)
    names = set()
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(n.name)
        elif isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            names.add(n.target.id)
    return names


def _nested_def_names(src: str):
    """Names of nested (non-top-level) def/class — to prove a symbol exists but is nested."""
    tree = ast.parse(src)
    nested = set()
    for parent in ast.walk(tree):
        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for child in parent.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    nested.add(child.name)
    return nested


def replay_symbol_patch(label, target_file, emission_file):
    print(f"\n{'='*78}\n### {label}\n{'='*78}")
    src = pathlib.Path(target_file).read_text(encoding="utf-8")
    code = pathlib.Path(emission_file).read_text(encoding="utf-8")
    patches = _parse_patches(code)
    if patches is None:
        print("  emission did NOT parse as a recognized patch/manifest marker.")
        # Probe for manifest
        if "__JANUSMASK_MANIFEST__" in code:
            print("  -> emission uses __JANUSMASK_MANIFEST__ (whole-file replacement),"
                  " NOT a symbol patch. Patch-apply is N/A; failure is downstream"
                  " (import/verification).")
        return
    top = _toplevel_def_assign_names(src)
    nested = _nested_def_names(src)
    for p in patches:
        if p.get("kind") != "symbol":
            print(f"  patch kind={p.get('kind')} (not symbol) -> {p.get('marker', '')}")
            continue
        name = p["name"]
        present_top = name in top
        present_nested = name in nested
        print(f"  patch kind=symbol name={name!r}")
        print(f"    exists at TOP LEVEL of target? {present_top}")
        print(f"    exists NESTED (inside another def/class)? {present_nested}")
        try:
            _apply_symbol_patch(src, name, p["code"])
            print("    _apply_symbol_patch RESULT: APPLIED OK (no exception)")
        except Exception as exc:
            print(f"    _apply_symbol_patch RAISED: {type(exc).__name__}: {exc!r}")


def probe_manifest_forwardref(label, emission_file):
    print(f"\n{'='*78}\n### {label}\n{'='*78}")
    code = pathlib.Path(emission_file).read_text(encoding="utf-8")
    if "__JANUSMASK_MANIFEST__" not in code:
        print("  not a manifest emission")
        return
    # Extract the gate_executor.py whole-file body and try to import it standalone.
    ns = {}
    exec(compile(code, emission_file, "exec"), ns)  # define __JANUSMASK_MANIFEST__
    manifest = ns["__JANUSMASK_MANIFEST__"]
    print(f"  manifest keys: {list(manifest.keys())}")
    body = manifest["ngv2/gate_executor.py"]
    print("  attempting to EXEC the whole-file gate_executor body in isolation"
          " (mirrors module import at collection time)...")
    try:
        exec(compile(body, "ngv2/gate_executor.py", "exec"), {})
        print("  RESULT: module body executed OK")
    except Exception as exc:
        print(f"  RESULT RAISED: {type(exc).__name__}: {exc!r}")
        # show the forward-ref ordering
        tree = ast.parse(body)
        defs = [(n.lineno, n.name) for n in tree.body
                if isinstance(n, (ast.FunctionDef, ast.ClassDef))]
        assigns = []
        for n in tree.body:
            if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
                assigns.append((n.lineno, n.target.id))
            elif isinstance(n, ast.Assign):
                for t in n.targets:
                    if isinstance(t, ast.Name):
                        assigns.append((n.lineno, t.id))
        print(f"  top-level assigns (lineno,name): {sorted(assigns)[:12]}")


if __name__ == "__main__":
    # TASK 3: p11-build-evidence (the auto_commit_patch_failed KeyError candidate)
    replay_symbol_patch(
        "p11-build-evidence-structural-keys  [ledger: auto_commit_patch_failed 'build_evidence']",
        NG / "ngv2" / "conductor_seams.py",
        OUT / "p11-build-evidence-structural-keys.py",
    )
    # TASK 1: hlresume (R-anchor on spawn_agent; should APPLY OK -> failure was verification)
    replay_symbol_patch(
        "hlresume-continue-headless-impl  [ledger: verification_failed -> auto_commit_failed]",
        JM / "harness" / "orchestrator.py",
        OUT / "hlresume-continue-headless-impl.py",
    )
    # TASK 2: p11-gate-table (manifest whole-file; forward-ref NameError at import)
    probe_manifest_forwardref(
        "p11-gate-table-typed-terminals  [ledger: verification_failed NameError _STRUCTURAL_TRANSITIONS]",
        OUT / "p11-gate-table-typed-terminals.py",
    )
