#!/usr/bin/env python3
"""Independent verification of the Int 4 P0 sandbox main_pool() dedup.

Run with: PYTHONPATH=. python3 _autowork_scratch/verify_sandbox_dedup.py

Asserts (against the CURRENT on-disk harness/sandbox.py):
  1. SINGLE DEFINITION: source contains 'def main_pool():' exactly once;
     _MAIN_POOL_TEMPLATE defined exactly once; 0 real main_pool AST funcs.
  2. NO real exec/eval/compile/__import__ Call nodes added (AST-enforcer safety).
  3. BYTE-IDENTITY: runtime values of _RUNNER_TEMPLATE and _BATCH_RUNNER_TEMPLATE
     equal the golden HEAD sha256 captured in the baseline file.
  4. Both emitted runner scripts still compile.
  5. The two templates still each embed exactly one main_pool body, identical.
"""
import ast
import hashlib
import importlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BASELINE = json.load(open(REPO / "_autowork_scratch" / "sandbox_dedup_baseline.json"))
GOLD_RUNNER = BASELINE["_RUNNER_TEMPLATE"]
GOLD_BATCH = BASELINE["_BATCH_RUNNER_TEMPLATE"]

src = (REPO / "harness" / "sandbox.py").read_text()
tree = ast.parse(src)

ok = True
def check(label, cond):
    global ok
    print(("PASS" if cond else "FAIL"), label)
    ok = ok and cond

# 1. single definition
check("source 'def main_pool():' occurs exactly once", src.count("def main_pool():") == 1)
mpt_assigns = sum(
    1 for n in tree.body
    if isinstance(n, ast.Assign) and any(getattr(t, "id", None) == "_MAIN_POOL_TEMPLATE" for t in n.targets)
)
check("_MAIN_POOL_TEMPLATE defined exactly once", mpt_assigns == 1)
real_mp = sum(1 for n in ast.walk(tree) if getattr(n, "name", None) == "main_pool")
check("0 real main_pool AST functions (still string template)", real_mp == 0)

# 2. no real dangerous calls
bad = [(n.func.id, n.lineno) for n in ast.walk(tree)
       if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
       and n.func.id in ("exec", "eval", "compile", "__import__")]
check(f"no real exec/eval/compile/__import__ Call nodes (found {bad})", not bad)

# 3 + 4 + 5: runtime values
sys.path.insert(0, str(REPO))
import harness.sandbox as sb
importlib.reload(sb)
r_sha = hashlib.sha256(sb._RUNNER_TEMPLATE.encode()).hexdigest()
b_sha = hashlib.sha256(sb._BATCH_RUNNER_TEMPLATE.encode()).hexdigest()
check(f"_RUNNER_TEMPLATE runtime value byte-identical to HEAD", r_sha == GOLD_RUNNER)
check(f"_BATCH_RUNNER_TEMPLATE runtime value byte-identical to HEAD", b_sha == GOLD_BATCH)
try:
    compile(sb._RUNNER_TEMPLATE, "<runner>", "exec")
    compile(sb._BATCH_RUNNER_TEMPLATE, "<batch>", "exec")
    check("both emitted runner scripts compile", True)
except SyntaxError as e:
    check(f"both emitted runner scripts compile ({e})", False)

def mp(v):
    i = v.index("def main_pool():"); j = v.index("if __name__", i); return v[i:j]
check("both templates embed identical main_pool body",
      mp(sb._RUNNER_TEMPLATE) == mp(sb._BATCH_RUNNER_TEMPLATE))

print("\nOVERALL:", "ALL PASS" if ok else "FAILURES PRESENT")
sys.exit(0 if ok else 1)
