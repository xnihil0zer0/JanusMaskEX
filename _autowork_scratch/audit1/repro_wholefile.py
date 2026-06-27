#!/usr/bin/env python3
"""Validate PATH B (whole-file _ast_merge, single-symbol change) by loading the
full historical git_integration module with real stdlib preserved and only
harness-sibling imports stubbed."""
import sys, ast, textwrap, types, importlib.util

HERE = "/home/xnihil0zer0/JanusMaskJR/_autowork_scratch/audit1"
SRC = open(f"{HERE}/conductor_seams_orig.py").read()

NEW_BE = textwrap.dedent('''\
    def build_evidence(state: Dict[str, Any]) -> Dict[str, Any]:
        ev = dict(state.get('evidence') or {})
        ev['__p11_marker__'] = True
        return ev
''')
orig_tree = ast.parse(SRC)
bds = next(x for x in orig_tree.body if getattr(x, "name", None) == "build_default_seams")
be = next(x for x in ast.walk(bds) if isinstance(x, ast.FunctionDef) and x.name == "build_evidence")
L = SRC.splitlines(keepends=True)
new_be = "".join("    " + l if l.strip() else l for l in NEW_BE.splitlines(keepends=True))
WHOLE_BDS = "".join(L[bds.lineno-1:be.lineno-1]) + new_be + "".join(L[be.end_lineno:bds.end_lineno])
WHOLE_FILE = "".join(L[:bds.lineno-1]) + WHOLE_BDS + "".join(L[bds.end_lineno:])

def load_module(path, modname):
    """Load full module text; stub only failing (harness-sibling) imports."""
    src = open(path).read()
    import builtins
    real = builtins.__import__
    STDLIB_OK = True
    def imp(name, *a, **k):
        try:
            return real(name, *a, **k)
        except Exception:
            m = sys.modules.get(name) or types.ModuleType(name)
            # give attribute access that returns more stubs
            sys.modules[name] = m
            return m
    # Only stub names that are clearly harness siblings (relative-ish)
    HARNESS = {"harness", "paths", "agent_jail"}
    def selective(name, *a, **k):
        top = name.split(".")[0]
        if top in HARNESS or name.startswith("."):
            m = sys.modules.get(name) or types.ModuleType(name)
            sys.modules[name] = m
            return m
        return real(name, *a, **k)
    ns = {"__name__": modname}
    builtins.__import__ = selective
    try:
        exec(compile(src, path, "exec"), ns)
    finally:
        builtins.__import__ = real
    return ns

for label, path in [("a400a38 (BEFORE chain)", f"{HERE}/git_integration_a400a38.py"),
                    ("f4d8ba3 (HEAD)",          f"{HERE}/git_integration_f4d8ba3.py")]:
    print("=" * 70)
    print(label)
    try:
        ns = load_module(path, "gi_" + label[:7])
        am = ns["_ast_merge"]
        out = am(WHOLE_FILE, SRC)
        marker = "__p11_marker__" in out
        nt = ast.parse(out)
        o = {n.name: ast.dump(n) for n in orig_tree.body if hasattr(n, "name")}
        nn = {n.name: ast.dump(n) for n in nt.body if hasattr(n, "name")}
        changed = [k for k in o if k in nn and o[k] != nn[k]]
        print(f"  _ast_merge OK: marker={marker} top_level_changed={changed} ({len(out)} chars)")
        print(f"  whole_file_drift gate (len(changed)>1) would fire: {len(changed) > 1}")
    except Exception as e:
        import traceback; traceback.print_exc()
