#!/usr/bin/env python3
"""S1: Parse harness/config.yaml and print the exact values README §2/§8 assert."""
import yaml, sys, pathlib
root = pathlib.Path("/home/xnihil0zer0/JanusMaskJR")
cfg = yaml.safe_load((root / "harness/config.yaml").read_text())

print("=== workers ===")
w = cfg["workers"]
print("workers.claude_backend           =", repr(w.get("claude_backend")))
print("workers.agy_pool                 =", repr(w.get("agy_pool")))
print("workers.pin_task_cwd             =", repr(w.get("pin_task_cwd")))
print("workers.resume_pinned_session    =", repr(w.get("resume_pinned_session")))

print("\n=== autowork ===")
a = cfg["autowork"]
for k in ["parallel_cap", "claude_parallel_cap", "wire_up_gate",
          "wire_up_runtime_gate", "wire_up_runtime_gate_enforce",
          "onesided_oracle", "onesided_oracle_blocking", "onesided_metamorphic"]:
    print(f"autowork.{k:<32} = {a.get(k, '<<ABSENT>>')!r}")

print("\n=== presence vs absence (current file) ===")
for k in ["onesided_metamorphic", "wire_up_runtime_gate", "wire_up_runtime_gate_enforce", "claude_parallel_cap"]:
    print(f"  autowork.{k}: {'PRESENT' if k in a else 'ABSENT'}")
