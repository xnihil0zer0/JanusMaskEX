#!/bin/bash
# S1: Does the README's "entrypoints as extra live roots" actually hold at JM HEAD fc8167a?
# Investigate: _inject_integration_contracts, the floor caller (symbol_reachable_from_live_root), _contract_valid.
JM=/home/xnihil0zer0/JanusMaskJR
echo "=== JM HEAD ==="; git -C $JM rev-parse --short HEAD
echo
echo "=== A) _inject_integration_contracts in plan_normalizer.py ==="
grep -rn "_inject_integration_contracts\|integration_contract" $JM/harness/planner/plan_normalizer.py | head -40
echo
echo "=== B) _contract_valid (where?) ==="
grep -rln "_contract_valid" $JM/harness/ 2>/dev/null
echo "---"
grep -rn "def _contract_valid" $JM/harness/ 2>/dev/null
echo
echo "=== C) wire_up.py: symbol_reachable_from_live_root + LIVE_ROOTS + entrypoints + extra roots ==="
grep -n "def symbol_reachable_from_live_root\|LIVE_ROOTS\|entrypoint\|extra_root\|integration_contract\|wire_up.roots\|roots" $JM/harness/wire_up.py | head -60
