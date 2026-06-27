#!/usr/bin/env python3
"""S3: Exercise _apply_symbol_patch for: 2-part dotted Outer.method,
DEEP dotted Outer.Mid.inner (NEW capability?), 1-part bare nested name (reject?),
and a truly-absent name (KeyError)."""
import sys
sys.path.insert(0, "/home/xnihil0zer0/JanusMaskJR")
from harness.git_integration import _apply_symbol_patch

SRC = '''\
class Outer:
    def method(self):
        return 1

    class Mid:
        def inner(self):
            return 2

def top():
    def nested_only():
        return 3
    return nested_only
'''

def trial(qual, block):
    try:
        out = _apply_symbol_patch(SRC, qual, block)
        # show whether the replacement text appears
        return ("OK", "REPLACED_OK" if "REPLACED" in out else "applied(no-marker)")
    except KeyError as e:
        return ("KeyError", repr(e))
    except ValueError as e:
        return ("ValueError", str(e)[:300])
    except Exception as e:
        return (type(e).__name__, str(e)[:200])

print("=== (a) 2-part dotted Outer.method ===")
print("  ", trial("Outer.method", "def method(self):\n    return 'REPLACED'\n"))

print("\n=== (b) 3-part DEEP dotted Outer.Mid.inner (was 'else: raise KeyError') ===")
print("  ", trial("Outer.Mid.inner", "def inner(self):\n    return 'REPLACED'\n"))

print("\n=== (c) 1-part bare nested-only name 'nested_only' (should REJECT w/ ValueError) ===")
print("  ", trial("nested_only", "def nested_only():\n    return 'REPLACED'\n"))

print("\n=== (d) 1-part bare nested name with MULTIPLE enclosers ===")
SRC2 = '''\
def a():
    def shared():
        return 1
def b():
    def shared():
        return 2
'''
try:
    _apply_symbol_patch(SRC2, "shared", "def shared():\n    return 9\n")
    print("   UNEXPECTED OK")
except ValueError as e:
    print("   ValueError:", str(e)[:300])
except Exception as e:
    print("  ", type(e).__name__, str(e)[:200])

print("\n=== (e) truly-absent name 'ghost' (should raise bare KeyError) ===")
print("  ", trial("ghost", "def ghost():\n    return 0\n"))
