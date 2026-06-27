#!/usr/bin/env python3
"""AGENT1 probe: floor reachability, check_wired, discover_live_roots,
validate_exemption, and the NGv2 run_hunt sanity probe. READ-ONLY.
Run from /home/xnihil0zer0/JanusMaskJR."""
import inspect
import sys

sys.path.insert(0, "/home/xnihil0zer0/JanusMaskJR")

from harness import wire_up
from harness.wire_up import (
    LIVE_ROOTS,
    symbol_reachable_from_live_root,
    check_wired,
    discover_live_roots,
    validate_exemption,
)

JM = "/home/xnihil0zer0/JanusMaskJR"
NG = "/home/xnihil0zer0/NobleGreedv2"

print("=== CLAIM 1: LIVE_ROOTS exact value ===")
print(f"  LIVE_ROOTS = {LIVE_ROOTS}")

print("\n=== CLAIM 3: symbol_reachable_from_live_root signature ===")
print("  sig:", inspect.signature(symbol_reachable_from_live_root))

print("\n=== CLAIM 4: check_wired signature ===")
print("  sig:", inspect.signature(check_wired))

print("\n=== CLAIM 5: discover_live_roots over BOTH trees ===")
jm_roots = discover_live_roots(JM)
print(f"  JM discover_live_roots -> {len(jm_roots)} roots; first 8: {jm_roots[:8]}")
ng_roots = discover_live_roots(NG)
print(f"  NGv2 discover_live_roots -> {len(ng_roots)} roots; first 12: {ng_roots[:12]}")
print(f"  NGv2: 'ngv2/run_hunt.py' in roots? {'ngv2/run_hunt.py' in ng_roots}")
print(f"  NGv2: any JM LIVE_ROOT present? {[r for r in LIVE_ROOTS if r in ng_roots]}")

print("\n=== CLAIM 9: FLOOR over real NGv2 run_hunt with HARDCODED JM LIVE_ROOTS ===")
# Default roots = JM LIVE_ROOTS (no override) -> mimics the orchestrator call at line 2347
floor_hardcoded = symbol_reachable_from_live_root(NG, "ngv2/run_hunt.py", "run_hunt")
print(f"  symbol_reachable_from_live_root(NG, 'ngv2/run_hunt.py', 'run_hunt')  [JM roots] = {floor_hardcoded}")
print(f"  would_be_orphan (floor only) = {not floor_hardcoded}")
# And with NGv2's own discovered roots, to show the floor CAN see it if reconciled
floor_ngroots = symbol_reachable_from_live_root(NG, "ngv2/run_hunt.py", "run_hunt", roots=ng_roots)
print(f"  same FLOOR but roots=NGv2 discovered roots = {floor_ngroots}")

print("\n=== CLAIM 4: OLD check_wired over real NGv2 run_hunt module (default JM roots) ===")
wr = check_wired(NG, "ngv2/run_hunt.py")
print(f"  check_wired(NG, 'ngv2/run_hunt.py').wired = {wr.wired}")
print(f"  reason: {wr.reason[:160]}")

print("\n=== CLAIM 3 (cont): does the FLOOR have a rootless no-op / discover_live_roots fallback? ===")
src = inspect.getsource(symbol_reachable_from_live_root)
print(f"  'discover_live_roots' in FLOOR source? {'discover_live_roots' in src}")
print(f"  'external_reconciled' in FLOOR source? {'external_reconciled' in src}")
cw_src = inspect.getsource(check_wired)
print(f"  'discover_live_roots' in check_wired source? {'discover_live_roots' in cw_src}")
print(f"  'external_reconciled' in check_wired source? {'external_reconciled' in cw_src}")

print("\n=== CLAIM 7: validate_exemption staged_sibling -> requires_recheck ===")
v_staged = validate_exemption("staged_sibling", "run_hunt", "ngv2/run_hunt.py", NG)
print(f"  validate_exemption('staged_sibling', ...) = {v_staged}")
v_pure = validate_exemption("pure_helper", "run_hunt", "ngv2/run_hunt.py", NG)
print(f"  validate_exemption('pure_helper', ...)    = {v_pure}  (re-runs the same floor)")
v_bad = validate_exemption("frobnicate", "run_hunt", "ngv2/run_hunt.py", NG)
print(f"  validate_exemption('frobnicate', ...)     = {v_bad}")
