#!/usr/bin/env python3
"""S5: Prove a manifest carrying an UNDECLARED key is now ACCEPTED with the key
DROPPED (was: rejected as manifest_undeclared_key)."""
import sys, inspect
sys.path.insert(0, "/home/xnihil0zer0/JanusMaskJR")
from harness import orchestrator as orch

# Confirm the old rejection violation is GONE and the new drop path exists.
src = inspect.getsource(orch._validate_submission)
print("=== _validate_submission: old reject vs new drop ===")
print("  'manifest_undeclared_key' Violation still raised:", "rule='manifest_undeclared_key'" in src)
print("  drops undeclared keys (manifest.pop):", "manifest.pop(_k, None)" in src)
print("  'DROPPED undeclared keys' log:", "DROPPED undeclared keys" in src)

print("\n=== _restrict_sidecar_to_declared exists in orchestrator ===")
print("  has func:", hasattr(orch, "_restrict_sidecar_to_declared"))

print("\n=== Live: manifest with an undeclared key -> validation result ===")
code = (
    "__JANUSMASK_MANIFEST__ = {\n"
    "  'harness/declared_mod.py': r'''def a():\\n    return 1\\n''',\n"
    "  'harness/UNDECLARED_mod.py': r'''def b():\\n    return 2\\n''',\n"
    "}\n"
)
task = {"task_id": "t1", "files_touched": ["harness/declared_mod.py"], "meta_task_type": "data_model"}
try:
    ok, violations = orch._validate_submission(code, "claude", task)
    print("  ok:", ok)
    print("  violations:", [(v.rule, v.message[:60]) for v in violations] if violations else [])
except Exception as e:
    print("  raised:", type(e).__name__, str(e)[:200])
