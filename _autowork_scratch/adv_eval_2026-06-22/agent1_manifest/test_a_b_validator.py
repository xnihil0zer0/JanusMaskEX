"""(a) stray manifest key dropped+accepted; (b) negative control: missing entry rejected."""
import sys, os, json
sys.path.insert(0, "/home/xnihil0zer0/JanusMaskJR")
from harness.orchestrator import _validate_submission

# A VALID py body that passes validate_code (deterministic, no banned constructs)
PY_BODY = "def f(x):\n    return x + 1\n"

def manifest_code(d):
    # Reproduce the __JANUSMASK_MANIFEST__ submission encoding the worker emits.
    return "__JANUSMASK_MANIFEST__ = " + repr(d) + "\n"

# ---- (a) stray key present, all declared present => DROP stray, accept ----
task_a = {
    "files_touched": ["harness/target_bootstrap.py"],
    "meta_task_type": "harness_self_fix",
    "constraints": {"deterministic": False},  # allow_nondet, irrelevant here
}
code_a = manifest_code({
    "harness/target_bootstrap.py": PY_BODY,
    "config/target_bootstrap.yaml": "key: value\n",   # STRAY undeclared key (non-py)
})
ok_a, viol_a = _validate_submission(code_a, "claude", task_a)
rules_a = sorted({getattr(v, "rule", None) for v in viol_a})
print("=== (a) stray-key drop ===")
print("ok_a:", ok_a)
print("rules_a:", rules_a)
print("PASS_A:", ok_a is True and "manifest_undeclared_key" not in rules_a)

# (a2) stray key is itself a .py file with a banned construct -> should be DROPPED
#      (not validated), so submission still accepted. Proves the stray is truly removed.
code_a2 = manifest_code({
    "harness/target_bootstrap.py": PY_BODY,
    "harness/stray_evil.py": "def g():\n    eval('1')\n",  # would FAIL validate_code if scanned
})
ok_a2, viol_a2 = _validate_submission(code_a2, "claude", task_a)
rules_a2 = sorted({getattr(v, "rule", None) for v in viol_a2})
print("=== (a2) stray .py with banned construct is dropped not scanned ===")
print("ok_a2:", ok_a2, "rules_a2:", rules_a2)
print("PASS_A2:", ok_a2 is True)

# ---- (b) NEGATIVE CONTROL: declared entry MISSING from manifest => manifest_incomplete ----
task_b = {
    "files_touched": ["harness/target_bootstrap.py", "harness/second_file.py"],
    "meta_task_type": "harness_self_fix",
    "constraints": {"deterministic": False},
}
code_b = manifest_code({
    "harness/target_bootstrap.py": PY_BODY,  # second_file.py OMITTED
})
ok_b, viol_b = _validate_submission(code_b, "claude", task_b)
rules_b = sorted({getattr(v, "rule", None) for v in viol_b})
print("=== (b) missing declared entry ===")
print("ok_b:", ok_b)
print("rules_b:", rules_b)
print("PASS_B:", ok_b is False and "manifest_incomplete" in rules_b)
