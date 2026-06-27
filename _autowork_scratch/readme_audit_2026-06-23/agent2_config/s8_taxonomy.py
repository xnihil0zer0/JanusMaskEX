#!/usr/bin/env python3
"""S8: Import taxonomies and verify the §9 table + derived-sets for data_model.
README §9 table row: `data_model | yes (bypass_fuzzer) | skip decomp`.
Diff flipped data_model.bypass_fuzzer True->False. Prove current policy + sets."""
import sys, subprocess, pathlib
root = pathlib.Path("/home/xnihil0zer0/JanusMaskJR")
sys.path.insert(0, str(root))
from harness.planner.taxonomies import (
    META_TASK_POLICY, BYPASS_FUZZER_TYPES, SIDE_EFFECT_META_TYPES, META_TASK_TYPES)

print("=== data_model policy (HEAD) ===")
print("META_TASK_POLICY['data_model'] =", META_TASK_POLICY["data_model"])
print("data_model in BYPASS_FUZZER_TYPES :", "data_model" in BYPASS_FUZZER_TYPES)
print("data_model in SIDE_EFFECT_META_TYPES (skip_structural_decomp):",
      "data_model" in SIDE_EFFECT_META_TYPES)

print("\n=== baseline e5c0f9fb data_model policy ===")
base = subprocess.check_output(["git", "show", "e5c0f9fb:harness/planner/taxonomies.py"], cwd=root, text=True)
import re
m = re.search(r"'data_model': (\{[^}]*\})", base)
print("baseline data_model =", m.group(1) if m else "<not parsed>")

print("\n=== set membership counts (sanity) ===")
print("len(META_TASK_TYPES)        =", len(META_TASK_TYPES))
print("len(BYPASS_FUZZER_TYPES)    =", len(BYPASS_FUZZER_TYPES))
print("'implementation' a member?  =", "implementation" in META_TASK_TYPES)

# Confirm no type added/removed vs baseline
base_keys = set(re.findall(r"'([a-z_]+)': \{'bypass_fuzzer'", base))
head_keys = set(META_TASK_TYPES)
print("\ntypes added since baseline   :", head_keys - base_keys or "(none)")
print("types removed since baseline :", base_keys - head_keys or "(none)")
