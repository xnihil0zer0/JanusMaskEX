#!/usr/bin/env python3
"""G10 verification: the doc (§2 G10, §8A 2026-06-21) claims the vacuous-confirm
footgun is STILL LIVE at HEAD — that semantic_verdict(0,'VULNERABLE','','no fs
changes',sig='') -> 'confirmed' and "sig=''->confirmed unaddressed".

Empirically test current ngv2.detonation.semantic_verdict.
"""
import sys, inspect
sys.path.insert(0, "/home/xnihil0zer0/NobleGreedv2")
from ngv2.detonation import semantic_verdict

print("=== signature of semantic_verdict (does it now take a nonce?) ===")
print(inspect.signature(semantic_verdict))
print()

# The EXACT call the doc says still yields 'confirmed':
print("=== doc's exact vacuous case: empty sig ===")
try:
    r = semantic_verdict(0, 'VULNERABLE', '', 'no fs changes',
                         success_marker='VULNERABLE', expected_fs_signature='')
    print(f"  semantic_verdict(...,expected_fs_signature='')  -> {r!r}")
    print(f"  DOC CLAIM (sig='' -> 'confirmed'): {'STILL TRUE' if r=='confirmed' else 'STALE/FALSE (now '+r+')'}")
except Exception as e:
    print(f"  RAISED: {type(e).__name__}: {e}")
print()

print("=== whitespace-only sig ===")
try:
    r = semantic_verdict(0, 'VULNERABLE', '', 'no fs changes',
                         success_marker='VULNERABLE', expected_fs_signature='   ')
    print(f"  expected_fs_signature='   '  -> {r!r}")
except Exception as e:
    print(f"  RAISED: {type(e).__name__}: {e}")
print()

print("=== nonempty sig, marker present, sig in diff, NO nonce -> still confirms (legit) ===")
r = semantic_verdict(0, 'VULNERABLE', '', 'created pwned_marker_abc',
                     success_marker='VULNERABLE', expected_fs_signature='pwned_marker_abc')
print(f"  -> {r!r}")
print()

print("=== nonce provided but absent from outputs -> refuted (new nonce gate) ===")
r = semantic_verdict(0, 'VULNERABLE present', '', 'created pwned_marker_abc',
                     success_marker='VULNERABLE', expected_fs_signature='pwned_marker_abc',
                     nonce='N0NCE_XYZ')
print(f"  nonce='N0NCE_XYZ' absent everywhere -> {r!r}  (expect 'refuted')")
print()

print("=== nonce provided AND present everywhere -> confirmed ===")
r = semantic_verdict(0, 'VULNERABLE N0NCE_XYZ', '', 'created pwned_N0NCE_XYZ',
                     success_marker='VULNERABLE', expected_fs_signature='pwned_N0NCE_XYZ',
                     nonce='N0NCE_XYZ')
print(f"  -> {r!r}  (expect 'confirmed')")
