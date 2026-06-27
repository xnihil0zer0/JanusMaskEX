"""Analytic diagnostic for p11-build-evidence-structural-keys auto_commit_failed.

Proves:
  (1) the worker's emitted kind:symbol patch on the NESTED closure `build_evidence`
      now raises the TYPED nested-symbol ValueError from _apply_symbol_patch
      (the just-landed diagnostic fix, commit 2dbc13e).
  (2) which patch shape WILL successfully apply for this nested closure:
        - symbol patch on the ENCLOSING top-level `build_default_seams`  -> works
        - region patch -> NOT viable (no sentinels in source)
        - whole-file rewrite -> works (trivially)

Read-only: imports the harness apply functions and runs them against an
IN-MEMORY copy of the live conductor_seams.py. Writes nothing to disk.
"""
import sys
import ast

REPO = "/home/xnihil0zer0/JanusMaskJR"
sys.path.insert(0, REPO)

from harness.git_integration import _apply_symbol_patch, _apply_region_patch  # noqa: E402

TARGET = "/home/xnihil0zer0/NobleGreedv2/ngv2/conductor_seams.py"
with open(TARGET) as fh:
    SOURCE = fh.read()


def banner(s):
    print("\n" + "=" * 78)
    print(s)
    print("=" * 78)


# ---------------------------------------------------------------------------
# 0. Confirm structure: build_evidence is nested inside build_default_seams.
# ---------------------------------------------------------------------------
banner("0. STRUCTURE CHECK")
tree = ast.parse(SOURCE)
top_level_names = {n.name for n in tree.body
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
print("top-level defs/classes:", sorted(top_level_names))
print("'build_evidence' is top-level?:", "build_evidence" in top_level_names)
print("'build_default_seams' is top-level?:", "build_default_seams" in top_level_names)

# find the nested build_evidence and its enclosing chain
enclosers = []
for outer in tree.body:
    if isinstance(outer, ast.FunctionDef):
        for inner in ast.walk(outer):
            if isinstance(inner, ast.FunctionDef) and inner.name == "build_evidence" and inner is not outer:
                # confirm it is genuinely nested (lineno within outer span)
                if outer.lineno < inner.lineno <= (outer.end_lineno or inner.lineno):
                    enclosers.append((outer.name, inner.lineno, inner.end_lineno))
print("nested build_evidence found at:", enclosers)

# size of the enclosing symbol
bds = next(n for n in tree.body if getattr(n, "name", None) == "build_default_seams")
print(f"build_default_seams spans lines {bds.lineno}-{bds.end_lineno} "
      f"({bds.end_lineno - bds.lineno + 1} lines)")


# ---------------------------------------------------------------------------
# 1. The worker's actual patch: kind:symbol name='build_evidence'.
#    Expect the TYPED nested-symbol ValueError (NOT a bare KeyError).
# ---------------------------------------------------------------------------
banner("1. WORKER PATCH (kind:symbol name='build_evidence') -> expect TYPED error")
worker_new_block = (
    "def build_evidence(state):\n"
    "    ev = dict(state.get('evidence') or {})\n"
    "    return ev\n"
)
try:
    _apply_symbol_patch(SOURCE, "build_evidence", worker_new_block)
    print("!!! UNEXPECTED: apply SUCCEEDED (no error raised)")
except ValueError as e:
    print("RAISED ValueError (the new typed diagnostic):")
    print("  " + str(e))
except KeyError as e:
    print("!!! RAISED bare KeyError (OLD behavior, fix NOT live):", repr(e))


# ---------------------------------------------------------------------------
# 2a. Enclosing top-level symbol patch on build_default_seams -> expect SUCCESS.
#     We re-emit build_default_seams verbatim (its exact current source slice)
#     to prove the apply path resolves + splices the enclosing symbol cleanly.
# ---------------------------------------------------------------------------
banner("2a. ENCLOSING SYMBOL PATCH (kind:symbol name='build_default_seams') -> expect SUCCESS")
src_lines = SOURCE.splitlines(keepends=True)
bds_block = "".join(src_lines[bds.lineno - 1: bds.end_lineno])
try:
    out = _apply_symbol_patch(SOURCE, "build_default_seams", bds_block)
    ast.parse(out)  # result must be valid Python
    print("apply SUCCEEDED; result parses. byte-identical to source?:", out == SOURCE)
    print("  -> enclosing-symbol patch is a VIABLE shape (worker re-emits the whole")
    print("     build_default_seams with the new build_evidence body inside it).")
except Exception as e:
    print("!!! UNEXPECTED failure:", type(e).__name__, e)


# ---------------------------------------------------------------------------
# 2b. Region patch -> requires sentinels already present in source. They are
#     NOT. Prove the apply raises KeyError (no sentinel) => NOT viable as-is.
# ---------------------------------------------------------------------------
banner("2b. REGION PATCH (kind:region) -> expect KeyError (no sentinels in source)")
has_region = "# JANUSMASK_REGION:" in SOURCE
print("source already contains a JANUSMASK_REGION sentinel?:", has_region)
try:
    _apply_region_patch(SOURCE, "build_evidence", "    pass\n")
    print("!!! UNEXPECTED: region apply succeeded")
except KeyError as e:
    print("RAISED KeyError (no sentinel present):", str(e))
    print("  -> region patch is NOT viable: the live file carries no sentinel lines,")
    print("     and a kind:symbol/kind:region patch cannot itself INSERT them around")
    print("     a nested closure without rewriting the enclosing def anyway.")
except Exception as e:
    print("other:", type(e).__name__, e)


# ---------------------------------------------------------------------------
# 3. Confirm the TYPED error names the enclosing top-level symbol (actionable).
# ---------------------------------------------------------------------------
banner("3. SUMMARY")
try:
    _apply_symbol_patch(SOURCE, "build_evidence", worker_new_block)
except ValueError as e:
    msg = str(e)
    names_enclosing = "build_default_seams" in msg
    tells_fix = "enclosing top-level symbol" in msg or "patch the enclosing" in msg
    print("typed error names enclosing 'build_default_seams'?:", names_enclosing)
    print("typed error tells the worker the fix?:", tells_fix)
print("\nVIABLE SHAPES: symbol-on-build_default_seams = YES; whole-file = YES; region = NO (no sentinels)")
