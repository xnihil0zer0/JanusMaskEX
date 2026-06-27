#!/usr/bin/env python3
"""Test the DOTTED path AND the bare-name path against each HISTORICAL
git_integration.py. Extracts ONLY the _apply_symbol_patch function source via
AST and exec's it standalone (it is pure: ast + textwrap only)."""
import sys, ast, textwrap

HERE = "/home/xnihil0zer0/JanusMaskJR/_autowork_scratch/audit1"
SRC = open(f"{HERE}/conductor_seams_orig.py").read()

NEW_BUILD_EVIDENCE = textwrap.dedent('''\
    def build_evidence(state: Dict[str, Any]) -> Dict[str, Any]:
        ev = dict(state.get('evidence') or {})
        ev['__p11_marker__'] = True
        return ev
''')

def extract_func(path, fname="_apply_symbol_patch"):
    src = open(path).read()
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == fname:
            func_src = ast.get_source_segment(src, node)
            ns = {}
            import ast as _ast, textwrap as _tw
            exec(compile("import ast, textwrap\n" + func_src, path, "exec"), ns)
            return ns[fname]
    return None

COMMITS = [
    ("a400a38 (g7 impl — state BEFORE today's nested chain)", f"{HERE}/git_integration_a400a38.py"),
    ("2dbc13e (nested_symbol_patch_DIAGNOSTIC impl)",         f"{HERE}/git_integration_2dbc13e.py"),
    ("58300e5 (nested_symbol_patch_APPLY impl)",              f"{HERE}/git_integration_58300e5.py"),
    ("f4d8ba3 (nested_symbol_patch_ONEPART impl = HEAD)",     f"{HERE}/git_integration_f4d8ba3.py"),
]

def try_call(fn, qual):
    try:
        out = fn(SRC, qual, NEW_BUILD_EVIDENCE)
        ok = "__p11_marker__" in out
        try:
            ast.parse(out); parses = "parses-OK"
        except SyntaxError as e:
            parses = f"PARSE-FAIL({e})"
        # confirm exactly build_default_seams changed and siblings intact
        sib = all(c in out for c in ("load_state", "persist", "advance"))
        return f"OK marker={ok} {parses} siblings_intact={sib} ({len(out)} chars)"
    except Exception as e:
        return f"RAISED {type(e).__name__}: {str(e)[:130]}"

for label, path in COMMITS:
    print("\n" + "=" * 78)
    print(label)
    print("=" * 78)
    fn = extract_func(path)
    if fn is None:
        print("  _apply_symbol_patch NOT FOUND")
        continue
    print(f"  bare   'build_evidence'                     : {try_call(fn, 'build_evidence')}")
    print(f"  dotted 'build_default_seams.build_evidence' : {try_call(fn, 'build_default_seams.build_evidence')}")
