#!/usr/bin/env bash
# Prove the runtime-gate + watchdog flag defaults (config.yaml + gate fns) and the
# enforce/observe/report mode of the wire-up symbol gate. Read-only.
set -u
cd /home/xnihil0zer0/JanusMaskJR
echo "=== config.yaml autowork wire-up + watchdog flags (the literal shipped defaults) ==="
grep -nE "wire_up_gate|wire_up_runtime_gate|wire_up_runtime_gate_enforce|^\s*watchdog|JM_WATCHDOG" harness/config.yaml
echo
echo "=== python: load_config() and read each flag the gate actually reads ==="
.venv/bin/python - <<'PY'
import sys
sys.path.insert(0, '.')
from harness.config import load_config
cfg = load_config()
aw = cfg.get('autowork', {})
for k in ('wire_up_gate','wire_up_runtime_gate','wire_up_runtime_gate_enforce'):
    print(f"autowork.{k} = {aw.get(k, '<ABSENT->default False>')!r}")
print("autowork.watchdog =", aw.get('watchdog', '<ABSENT>'))
PY
echo
echo "=== gate fns: what each returns now (default False; runtime gate dark, enforce dark) ==="
.venv/bin/python - <<'PY'
import sys; sys.path.insert(0,'.')
from harness import orchestrator as o
print("_wire_up_gate_enabled()                 =", o._wire_up_gate_enabled())
print("_wire_up_runtime_gate_enabled()         =", o._wire_up_runtime_gate_enabled())
print("_wire_up_runtime_gate_enforce_enabled() =", o._wire_up_runtime_gate_enforce_enabled())
PY
echo
echo "=== watchdog enable predicate in state_reconciler (env + config) ==="
sed -n '1190,1210p' harness/state_reconciler.py
echo
echo "=== does detect_and_heal_stalls emit a stall_detected / stall_healed style event? ==="
grep -n "stall_detected\|stall_healed\|stall_detect\|def detect_and_heal_stalls\|stall_escalat\|stall_heal" harness/state_reconciler.py | head -20
