#!/usr/bin/env python3
"""S7: Check _module_scope_order_fixup (ast-merge-order) effect on whole-file merge:
(a) no-hazard merge stays byte-stable, (b) hazard reorders, (c) cyclic raises ValueError,
(d) whole_file_drift gate (1-symbol allowed, 2+ rejected) still holds via _finalize_existing_py_target."""
import sys
sys.path.insert(0, "/home/xnihil0zer0/JanusMaskJR")
from harness.git_integration import _ast_merge, _finalize_existing_py_target

print("=== (a) no-hazard merge byte-stable (edit one fn, no reorder needed) ===")
tgt = "X = 1\n\ndef f():\n    return X\n"
out = "X = 1\n\ndef f():\n    return X + 1\n"
merged = _ast_merge(out, tgt)
print("  order preserved (X before f):", merged.index("X = 1") < merged.index("def f"))

print("\n=== (b) forward-hazard: stmt using global defined later gets reordered ===")
# target: USE = helper(); def helper(): ... ; reordering moves helper before USE
tgt2 = "def g():\n    return USE\n\nUSE = compute()\n\ndef compute():\n    return 5\n"
try:
    merged2 = _ast_merge(tgt2, tgt2)  # merge with self exercises the fixup
    print("  merged ok; compute before USE:", merged2.index("def compute") < merged2.index("USE = compute"))
except ValueError as e:
    print("  ValueError:", str(e)[:120])

print("\n=== (c) whole_file_drift: 1 changed symbol ALLOWED ===")
base = "def a():\n    return 1\n\ndef b():\n    return 2\n"
one = "def a():\n    return 99\n\ndef b():\n    return 2\n"
try:
    r = _finalize_existing_py_target(one, base)
    print("  1-symbol change accepted; 'return 99' present:", "return 99" in r)
except ValueError as e:
    print("  UNEXPECTED ValueError:", str(e)[:120])

print("\n=== (d) whole_file_drift: 2 changed symbols REJECTED ===")
two = "def a():\n    return 99\n\ndef b():\n    return 88\n"
try:
    _finalize_existing_py_target(two, base)
    print("  UNEXPECTED OK")
except ValueError as e:
    print("  ValueError:", str(e)[:120])

print("\n=== (e) test_authoring bypasses drift (wholesale replace) ===")
ta = "def a():\n    return 99\n\ndef b():\n    return 88\n\ndef c():\n    return 7\n"
r2 = _finalize_existing_py_target(ta, base, meta_task_type="test_authoring")
print("  test_authoring replace accepted; has c():", "def c" in r2)
