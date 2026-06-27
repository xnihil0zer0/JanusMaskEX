"""S2: Prove (with code, not prose) how integration_contract.entrypoints relate to
the wire-up gate's live roots at JM HEAD fc8167a.

Claims under test:
 C1: The README (line 200) says the wire-up gate "reads `entrypoints` as extra live roots".
 C2: Code reality: in orchestrator._run_wire_up_gate the floor call
     symbol_reachable_from_live_root(staging_path, rel, _vsym) is invoked with NO roots=
     argument -> uses the DEFAULT hardcoded LIVE_ROOTS. entrypoints are NOT added to roots.
 C3: _contract_valid REQUIRES entrypoints to be a SUBSET of LIVE_ROOTS (each _ep in _live),
     so entrypoints can never be "extra" (outside-LIVE_ROOTS) roots.
 C4: detonate_oracle(..., list(_entrypoints), ...) is the only place entrypoints flow into a
     reachability/detonation computation (the contract-detonated path), not the static floor.
"""
import ast, inspect, pathlib
from harness import wire_up, orchestrator

print("=== LIVE_ROOTS (hardcoded) ===")
print(wire_up.LIVE_ROOTS)
print()

print("=== symbol_reachable_from_live_root signature ===")
print(inspect.signature(wire_up.symbol_reachable_from_live_root))
print("  -> default roots param is LIVE_ROOTS (JM-hardcoded)")
print()

# C2/C3/C4: AST-inspect _run_wire_up_gate for how entrypoints / roots are used.
src = inspect.getsource(orchestrator._run_wire_up_gate)
tree = ast.parse(src)

floor_calls_with_roots = []
floor_calls_default = []
detonate_calls = []
contract_valid_assigns = []

for node in ast.walk(tree):
    if isinstance(node, ast.Call):
        fn = node.func
        name = getattr(fn, 'id', None) or getattr(fn, 'attr', None)
        if name == 'symbol_reachable_from_live_root':
            kws = [k.arg for k in node.keywords]
            if 'roots' in kws:
                floor_calls_with_roots.append(ast.unparse(node))
            else:
                floor_calls_default.append(ast.unparse(node))
        if name == 'detonate_oracle':
            detonate_calls.append(ast.unparse(node))
    if isinstance(node, ast.Assign):
        for tgt in node.targets:
            if isinstance(tgt, ast.Name) and tgt.id == '_contract_valid':
                contract_valid_assigns.append(ast.unparse(node))

print("=== C2: floor calls (symbol_reachable_from_live_root) ===")
print("  WITH explicit roots= (entrypoints injected):", floor_calls_with_roots or "NONE")
print("  DEFAULT roots (uses hardcoded LIVE_ROOTS):  ", floor_calls_default or "NONE")
print()
print("=== C3: _contract_valid definition (note 'each _ep in _live') ===")
for a in contract_valid_assigns:
    print("  ", a)
print()
print("=== C4: detonate_oracle calls (the only entrypoints->reachability flow) ===")
for d in detonate_calls:
    print("  ", d)
print()

# Empirical: does symbol_reachable_from_live_root accept entrypoints as 'extra' roots beyond LIVE_ROOTS?
# Confirm the contract gate's subset requirement by reading the literal.
gate_src = src
print("=== C3 literal check: '_ep in _live' present in _run_wire_up_gate source? ===")
print("  ", "_ep in _live" in gate_src)
print("=== _live built from? ===")
for line in gate_src.splitlines():
    if "_live = " in line:
        print("  ", line.strip())
