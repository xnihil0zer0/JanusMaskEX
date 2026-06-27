#!/usr/bin/env python3
"""Does patching the ENCLOSING top-level symbol 'build_default_seams' WHOLE
(a 1-part symbol patch — no harness nested-support needed) land the P1.1 edit
on the OLD harness (a400a38, before today's chain)?  This is the candidate
'fundamental correction: no harness change'.

Also tests the WHOLE-FILE manifest path via _ast_merge."""
import sys, ast, textwrap

HERE = "/home/xnihil0zer0/JanusMaskJR/_autowork_scratch/audit1"
SRC = open(f"{HERE}/conductor_seams_orig.py").read()

NEW_BUILD_EVIDENCE = textwrap.dedent('''\
    def build_evidence(state: Dict[str, Any]) -> Dict[str, Any]:
        ev = dict(state.get('evidence') or {})
        ev['__p11_marker__'] = True
        return ev
''')

# Build the WHOLE enclosing build_default_seams with the modified closure spliced in
orig_tree = ast.parse(SRC)
bds = next(x for x in orig_tree.body if getattr(x, "name", None) == "build_default_seams")
be = next(x for x in ast.walk(bds) if isinstance(x, ast.FunctionDef) and x.name == "build_evidence")
all_lines = SRC.splitlines(keepends=True)
new_be_indented = "".join("    " + l if l.strip() else l for l in NEW_BUILD_EVIDENCE.splitlines(keepends=True))
WHOLE_BDS = ("".join(all_lines[bds.lineno-1:be.lineno-1]) + new_be_indented +
             "".join(all_lines[be.end_lineno:bds.end_lineno]))

def extract_func(path, fname):
    src = open(path).read()
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == fname:
            func_src = ast.get_source_segment(src, node)
            ns = {}
            exec(compile("import ast, textwrap\n" + func_src, path, "exec"), ns)
            return ns[fname]
    return None

def verify(out):
    ok = "__p11_marker__" in out
    try:
        ast.parse(out); parses = "parses-OK"
    except SyntaxError as e:
        parses = f"PARSE-FAIL({e})"
    sib = all(c in out for c in ("load_state", "persist", "advance", "build_evidence"))
    # count how many top-level symbols changed (drift check)
    nt = ast.parse(out)
    o = {n.name: ast.dump(n) for n in orig_tree.body if hasattr(n, "name")}
    nn = {n.name: ast.dump(n) for n in nt.body if hasattr(n, "name")}
    changed = [k for k in o if k in nn and o[k] != nn[k]]
    return f"marker={ok} {parses} siblings_intact={sib} top_level_changed={changed}"

COMMITS = [
    ("a400a38 (BEFORE today's chain)", f"{HERE}/git_integration_a400a38.py"),
    ("f4d8ba3 (HEAD)",                 f"{HERE}/git_integration_f4d8ba3.py"),
]

print("### PATH A: 1-part symbol patch of the WHOLE enclosing 'build_default_seams'")
for label, path in COMMITS:
    fn = extract_func(path, "_apply_symbol_patch")
    try:
        out = fn(SRC, "build_default_seams", WHOLE_BDS)
        print(f"  {label}: OK -> {verify(out)}")
    except Exception as e:
        print(f"  {label}: RAISED {type(e).__name__}: {str(e)[:120]}")

print("\n### PATH B: WHOLE-FILE manifest via _ast_merge (single-symbol change)")
# Build whole-file output: original file with build_default_seams replaced wholesale
WHOLE_FILE = "".join(all_lines[:bds.lineno-1]) + WHOLE_BDS + "".join(all_lines[bds.end_lineno:])
for label, path in COMMITS:
    fn = extract_func(path, "_ast_merge")
    if fn is None:
        print(f"  {label}: _ast_merge NOT FOUND"); continue
    try:
        out = fn(WHOLE_FILE, SRC)  # (output_code, target_code)
        print(f"  {label}: OK -> {verify(out)}")
    except Exception as e:
        print(f"  {label}: RAISED {type(e).__name__}: {str(e)[:120]}")
print("\nNOTE: whole_file_drift gate fires at len(changed)>1; here exactly ONE")
print("top-level symbol (build_default_seams) changes -> gate does NOT fire.")
