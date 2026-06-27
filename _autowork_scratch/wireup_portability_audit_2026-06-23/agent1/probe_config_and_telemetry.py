#!/usr/bin/env python3
"""AGENT1 probe: live config flag values + telemetry row counts.
Run from /home/xnihil0zer0/JanusMaskJR. READ-ONLY."""
import json
import sys
from pathlib import Path

sys.path.insert(0, "/home/xnihil0zer0/JanusMaskJR")

from harness.orchestrator import load_config

print("=== CLAIM 6: config flags via orchestrator.load_config() ===")
cfg = load_config()
aw = cfg.get("autowork", {}) if isinstance(cfg, dict) else {}
for k in ("wire_up_gate", "wire_up_runtime_gate", "wire_up_runtime_gate_enforce"):
    print(f"  {k} = {aw.get(k, '<ABSENT -> default False>')!r}")

print("\n=== CLAIM 8: telemetry row counts in state/impl_progress.jsonl ===")
ledger = Path("state/impl_progress.jsonl")
n_verdict = n_orphan_event = total = 0
sample_orphan = sample_verdict = None
with ledger.open() as fh:
    for line in fh:
        total += 1
        try:
            d = json.loads(line)
        except Exception:
            continue
        ev = d.get("event")
        if ev == "wireup_symbol_verdict":
            n_verdict += 1
            sample_verdict = sample_verdict or d
        if ev == "orphan_symbol_unwired":
            n_orphan_event += 1
            sample_orphan = sample_orphan or d
print(f"  total rows                         = {total}")
print(f"  event=='wireup_symbol_verdict'     = {n_verdict}")
print(f"  event=='orphan_symbol_unwired'     = {n_orphan_event}")
print(f"  sample verdict row                 = {sample_verdict}")
print(f"  sample orphan-event row            = {sample_orphan}")
