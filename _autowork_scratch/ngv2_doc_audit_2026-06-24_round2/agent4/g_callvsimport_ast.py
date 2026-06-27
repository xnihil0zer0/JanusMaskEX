import ast, os, sys
ROOT='/home/xnihil0zer0/NobleGreedv2/ngv2'
HANDLERS={'detect','provision_gate','jail_build_gate'}  # the c1/c2/c3 entry fns
HANDLER_FILES={'fsm_detect.py','fsm_provision.py','fsm_jail_build.py','fsm_evidence.py'}
imports=[]; calls=[]
for dp,_,fs in os.walk(ROOT):
    if '__pycache__' in dp: continue
    for fn in fs:
        if not fn.endswith('.py'): continue
        if fn.startswith('test_') or '/tests' in dp: continue
        p=os.path.join(dp,fn); rel=os.path.relpath(p,ROOT)
        try: tree=ast.parse(open(p).read())
        except: continue
        for node in ast.walk(tree):
            # import of handler modules
            if isinstance(node,(ast.Import,ast.ImportFrom)):
                mod=getattr(node,'module','') or ''
                names=[a.name for a in node.names]
                if 'fsm_detect' in mod or 'fsm_provision' in mod or 'fsm_jail_build' in mod or any('fsm_' in n for n in names) or any(n in HANDLERS for n in names):
                    if fn not in HANDLER_FILES:
                        imports.append(f"{rel}:{node.lineno}  imports {mod or names}")
            # CALL of a handler fn
            if isinstance(node,ast.Call):
                f=node.func
                nm=None
                if isinstance(f,ast.Name): nm=f.id
                elif isinstance(f,ast.Attribute): nm=f.attr
                if nm in HANDLERS and fn not in HANDLER_FILES:
                    calls.append(f"{rel}:{node.lineno}  CALLS {nm}()")
print("=== AST: non-test, non-handler-file IMPORTS of c1/c2/c3 handlers/modules ===")
print("\n".join(imports) if imports else "  (NONE)")
print("\n=== AST: non-test, non-handler-file CALL sites of detect()/provision_gate()/jail_build_gate() ===")
print("\n".join(calls) if calls else "  (ZERO CALL SITES -> handlers are import-only / never invoked in production)")
