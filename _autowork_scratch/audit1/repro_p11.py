#!/usr/bin/env python3
"""ADVERSARIAL P1.1 patch-apply repro — runs against the CURRENT harness
git_integration on copies of the real NGv2 target files. No production state
touched.

Questions answered:
 (Q1) What does a bare `kind:symbol` patch on `build_evidence` actually raise?
 (Q2a) region patch feasibility
 (Q2b) patching the ENCLOSING top-level symbol `build_default_seams` whole
 (Q2c) DOTTED `build_default_seams.build_evidence`  <-- the candidate simple path
"""
import sys, ast, traceback, textwrap
sys.path.insert(0, "/home/xnihil0zer0/JanusMaskJR")
from harness.git_integration import _apply_symbol_patch, _parse_patches, _ast_merge

HERE = "/home/xnihil0zer0/JanusMaskJR/_autowork_scratch/audit1"
SRC = open(f"{HERE}/conductor_seams_orig.py").read()

def banner(t):
    print("\n" + "=" * 78)
    print(t)
    print("=" * 78)

def show(label, fn):
    try:
        out = fn()
        print(f"[{label}] -> OK ({len(out)} chars). Re-parses: ", end="")
        try:
            ast.parse(out)
            print("YES")
        except SyntaxError as e:
            print(f"NO  ({e})")
        return out
    except Exception as e:
        print(f"[{label}] -> RAISED {type(e).__name__}: {str(e)[:240]}")
        return None

# A representative new body for build_evidence (adds a structural-key line).
NEW_BUILD_EVIDENCE = textwrap.dedent('''\
    def build_evidence(state: Dict[str, Any]) -> Dict[str, Any]:
        ev = dict(state.get('evidence') or {})
        ev['__p11_marker__'] = True   # P1.1 structural-key add
        return ev
''')

banner("Q1: bare kind:symbol patch keyed on the CLOSURE 'build_evidence'")
print("This is what the prior agent attempted (per deviation log).")
show("bare-name build_evidence", lambda: _apply_symbol_patch(SRC, "build_evidence", NEW_BUILD_EVIDENCE))

banner("Q2c: DOTTED 'build_default_seams.build_evidence'  (CANDIDATE SIMPLE PATH)")
out_dotted = show("dotted build_default_seams.build_evidence",
                  lambda: _apply_symbol_patch(SRC, "build_default_seams.build_evidence", NEW_BUILD_EVIDENCE))
if out_dotted:
    # verify the marker is present and exactly one symbol changed
    changed = []
    orig_tree = ast.parse(SRC)
    new_tree = ast.parse(out_dotted)
    o = {n.name: ast.dump(n) for n in orig_tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    n = {x.name: ast.dump(x) for x in new_tree.body if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    for name in o:
        if name in n and o[name] != n[name]:
            changed.append(name)
    print(f"   top-level symbols whose AST changed: {changed}")
    print(f"   '__p11_marker__' present in output: {'__p11_marker__' in out_dotted}")
    # also confirm the OTHER closures inside build_default_seams are intact
    for closure in ("load_state", "persist", "advance"):
        print(f"   closure {closure!r} still present: {closure in out_dotted}")

banner("Q2b: patch the ENCLOSING top-level symbol 'build_default_seams' WHOLE")
# We rebuild build_default_seams verbatim but with the modified build_evidence inside.
# Extract the original whole function text, do a naive in-text swap to simulate a
# worker emitting the whole enclosing function with the modified closure.
orig_tree = ast.parse(SRC)
bds = next(x for x in orig_tree.body if getattr(x, "name", None) == "build_default_seams")
lines = SRC.splitlines(keepends=True)
bds_text = "".join(lines[bds.lineno - 1:bds.end_lineno])
# swap the build_evidence closure body inside the extracted text
be = next(x for x in ast.walk(bds) if isinstance(x, ast.FunctionDef) and x.name == "build_evidence")
be_lines_abs = (be.lineno, be.end_lineno)
# reconstruct enclosing with replaced closure (re-indented to 4 spaces)
new_be_indented = "".join("    " + l if l.strip() else l for l in NEW_BUILD_EVIDENCE.splitlines(keepends=True))
all_lines = SRC.splitlines(keepends=True)
whole_new_bds = "".join(all_lines[bds.lineno-1:be.lineno-1]) + new_be_indented + "".join(all_lines[be.end_lineno:bds.end_lineno])
show("whole build_default_seams",
     lambda: _apply_symbol_patch(SRC, "build_default_seams", whole_new_bds))

banner("Q2a: region patch feasibility")
print("Region patches require a pre-existing '# JANUSMASK_REGION:<S>' sentinel PAIR in the source.")
print("Sentinels present in conductor_seams.py:", "JANUSMASK_REGION" in SRC)
print("-> region patch is NOT usable without first ADDING sentinels (which itself needs a symbol/whole-file edit).")
