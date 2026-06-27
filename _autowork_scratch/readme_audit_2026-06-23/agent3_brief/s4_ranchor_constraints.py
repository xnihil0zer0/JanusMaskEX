#!/usr/bin/env python3
"""S4: Confirm R-ANCHOR constraints in README §10 are UNCHANGED:
allowed_extra tuple, 'extras only for 1-part', collide rejection, no-extras byte-identity."""
import sys, ast, inspect
sys.path.insert(0, "/home/xnihil0zer0/JanusMaskJR")
from harness import git_integration as gi
from harness.git_integration import _apply_symbol_patch

src = inspect.getsource(_apply_symbol_patch)
# Extract the allowed_extra literal
import re
m = re.search(r"allowed_extra = \((.*?)\)", src)
print("=== allowed_extra tuple in code ===")
print("  ", m.group(0))
readme_tuple = "ast.Import, ImportFrom, FunctionDef, AsyncFunctionDef, ClassDef, Assign, AnnAssign"
code_kinds = [x.strip().replace("ast.", "") for x in m.group(1).split(",")]
print("  code kinds:", code_kinds)
print("  README lists: Import, ImportFrom, FunctionDef, AsyncFunctionDef, ClassDef, Assign, AnnAssign")
print("  MATCH:", code_kinds == ["Import","ImportFrom","FunctionDef","AsyncFunctionDef","ClassDef","Assign","AnnAssign"])

print("\n=== 'extras only for 1-part' still enforced? ===")
print("  has guard:", "extra top-level nodes are only permitted for a 1-part" in src)

print("\n=== Live: no-extras symbol replace is byte-identical-ish ===")
SRC = "def anchor():\n    return 1\n\ndef other():\n    return 2\n"
out = _apply_symbol_patch(SRC, "anchor", "def anchor():\n    return 99\n")
print("  out:", repr(out))

print("\n=== Live: R-anchor additive (anchor verbatim + new def before it) ===")
add_block = "def newfn():\n    return 'X'\n\ndef anchor():\n    return 1\n"
out2 = _apply_symbol_patch(SRC, "anchor", add_block)
print("  has newfn:", "def newfn" in out2, "| has anchor:", "def anchor" in out2)

print("\n=== Live: extras on a DOTTED qualname must REJECT (1-part only) ===")
SRC3 = "class C:\n    def m(self):\n        return 1\n"
try:
    _apply_symbol_patch(SRC3, "C.m", "def extra():\n    pass\n\ndef m(self):\n    return 2\n")
    print("  UNEXPECTED OK")
except ValueError as e:
    print("  ValueError:", str(e)[:120])

print("\n=== Live: collide rejection ===")
SRC4 = "def anchor():\n    return 1\n\ndef existing():\n    return 0\n"
try:
    _apply_symbol_patch(SRC4, "anchor", "def existing():\n    return 9\n\ndef anchor():\n    return 1\n")
    print("  UNEXPECTED OK")
except ValueError as e:
    print("  ValueError:", str(e)[:120])
