#!/usr/bin/env python3
"""D4 — NEW GAP G14: the trust program's own acceptance gate (wire-up
IMPORT-reachability) cannot distinguish "imported" from "executed on the live
path", so it green-lights BUILT-not-WORKS env-FSM handlers (detect /
provision_gate / jail_build_gate) that run_hunt never calls.

Evidence:
  (1) the handlers ARE import-reachable (importable + the cluster imports each
      other) -> they satisfy a wire-up gate keyed on import-reachability.
  (2) they have ZERO call-sites from the live conductor
      (run_hunt / transition_planner / gate_executor / conductor_seams /
       workers/_runner / session_api / state_machine / stage_command_map).
  (3) NONE of the four live wiring touch-points is wired:
        - ENV_PHASE_ORDER is NOT spliced into the live PHASE_ORDER
        - run_hunt._INITIAL_PHASE == 'hunt' (not 'detect')
        - transition_planner.worker_phases starts at 'hunt'
        - gate_executor._TRANSITION_GATES has no env-state transition keys
        - no ngv2/workers/<env-phase>.py modules exist
"""
import sys, ast, importlib, pathlib, re
NG = "/home/xnihil0zer0/NobleGreedv2"
sys.path.insert(0, NG)

HANDLERS = {
    "ngv2.fsm_detect": "detect",
    "ngv2.fsm_provision": "provision_gate",
    "ngv2.fsm_jail_build": "jail_build_gate",
    "ngv2.fsm_evidence": "advance_gate",
}
CONDUCTOR = [
    "ngv2/run_hunt.py", "ngv2/transition_planner.py", "ngv2/gate_executor.py",
    "ngv2/conductor_seams.py", "ngv2/workers/_runner.py", "ngv2/session_api.py",
    "ngv2/state_machine.py", "ngv2/stage_command_map.py",
]

print("=== (1) handlers ARE import-reachable (importable + callable) ===")
for mod, fn in HANDLERS.items():
    m = importlib.import_module(mod)
    f = getattr(m, fn, None)
    print(f"  import {mod}.{fn}: {'OK callable' if callable(f) else 'MISSING'}")

print()
print("=== (2) call-sites of each handler from the LIVE conductor ===")
# A 'call-site' = the function NAME appears as an ast.Call func across conductor
# files (and the module is imported there). Import-only counts separately.
def scan_calls(path, names):
    src = pathlib.Path(NG, path).read_text()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return {}
    calls = {n: 0 for n in names}
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                imports.add(a.asname or a.name)
            if isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
        if isinstance(node, ast.Call):
            fn = node.func
            nm = None
            if isinstance(fn, ast.Name):
                nm = fn.id
            elif isinstance(fn, ast.Attribute):
                nm = fn.attr
            if nm in calls:
                calls[nm] += 1
    return calls, imports

handler_fns = list(HANDLERS.values())
total_calls = {fn: 0 for fn in handler_fns}
for path in CONDUCTOR:
    calls, imports = scan_calls(path, handler_fns)
    nonzero = {k: v for k, v in calls.items() if v}
    if nonzero:
        print(f"  {path}: CALLS {nonzero}")
    for k, v in calls.items():
        total_calls[k] += v
print(f"  TOTAL live call-sites across conductor: {total_calls}")
print(f"  -> sum = {sum(total_calls.values())} (expect 0 => orphaned)")

print()
print("=== (3) live wiring touch-points ===")
rh = pathlib.Path(NG, "ngv2/run_hunt.py").read_text()
m = re.search(r"_INITIAL_PHASE\s*=\s*'([a-z_]+)'", rh)
print(f"  run_hunt._INITIAL_PHASE = {m.group(1)!r}  (expect 'detect' if FSM live; got {'detect' if m and m.group(1)=='detect' else 'hunt -> NOT wired'})")

from ngv2.fsm_evidence import PHASE_ORDER, ENV_PHASE_ORDER
env_in_live = [p for p in ENV_PHASE_ORDER if p in PHASE_ORDER]
print(f"  ENV_PHASE_ORDER members present in live PHASE_ORDER: {env_in_live}  (expect all 6; got {len(env_in_live)}/6)")

import ngv2.gate_executor as GE
env_gate_keys = [k for k in GE._TRANSITION_GATES if k[0] in ENV_PHASE_ORDER or k[1] in ENV_PHASE_ORDER]
print(f"  gate_executor transition gates touching env states: {env_gate_keys}  (expect non-empty if wired)")

tp = pathlib.Path(NG, "ngv2/transition_planner.py").read_text()
tp_env = [p for p in ENV_PHASE_ORDER if re.search(rf"['\"]{p}['\"]", tp)]
print(f"  env states referenced in transition_planner.py: {tp_env}  (expect all 6 if wired)")

wdir = pathlib.Path(NG, "ngv2/workers")
wfiles = [p.stem for p in wdir.glob("*.py") if p.stem in ENV_PHASE_ORDER]
print(f"  ngv2/workers/<env-phase>.py modules: {wfiles}  (expect 6 if wired)")

print()
print("=== VERDICT G14 ===")
orphaned = sum(total_calls.values()) == 0
importable = True
print(f"  handlers importable (pass import-reachability gate): {importable}")
print(f"  handlers have ZERO live call-sites (BUILT-not-WORKS):  {orphaned}")
print(f"  G14 (reachability != called-ness): "
      f"{'CONFIRMED — a NEW first-class systemic gap' if (importable and orphaned) else 'NOT shown'}")
