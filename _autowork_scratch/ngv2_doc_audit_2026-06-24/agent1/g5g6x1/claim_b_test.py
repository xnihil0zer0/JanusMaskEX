"""CLAIM B empirical test: count _TRANSITION_GATES transitions, count
TypedTerminal members, and read transition_planner worker_phases spawn set.

Run from /home/xnihil0zer0/NobleGreedv2 with PYTHONPATH=.
"""
from ngv2 import gate_executor
from ngv2 import transition_planner

# 1. Transition gates
gates = gate_executor._TRANSITION_GATES
print('=== _TRANSITION_GATES ===')
print('  number of (from,to) transition keys:', len(gates))
for k in gates:
    n_specs = len(gates[k])
    print(f"    {k}  -> {n_specs} gate-spec(s)")

# 2. Typed terminals
tt = gate_executor.TypedTerminal
members = {name: getattr(tt, name) for name in dir(tt) if not name.startswith('_')}
print('=== TypedTerminal members ===')
print('  count:', len(members))
for name, val in sorted(members.items()):
    print(f"    {name} = {val!r}")

# 3. transition_planner worker phases (the spawn set)
import inspect
src = inspect.getsource(transition_planner.plan_next_action)
print('=== transition_planner worker_phases spawn set ===')
for line in src.splitlines():
    if 'worker_phases' in line and '=' in line:
        print('  ', line.strip())

# Derive the spawn phase set from _next_phase chain
chain = []
p = 'source'
seen = set()
while p is not None and p not in seen:
    seen.add(p)
    chain.append(p)
    p = transition_planner._next_phase(p)
print('  _next_phase chain:', ' -> '.join(chain))

worker_set = {'hunt', 'triage', 'verify', 'poc', 'detonate', 'novelty', 'report'}
chain_has_all = worker_set.issubset(set(chain))
print('=== ONE-LINE VERDICT ===')
print(f"transitions={len(gates)}  typed_terminals={len(members)}  "
      f"full_worker_spawn_set_present={chain_has_all}")
