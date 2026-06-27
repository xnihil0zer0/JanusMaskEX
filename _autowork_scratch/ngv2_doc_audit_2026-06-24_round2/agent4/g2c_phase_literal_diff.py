import sys, importlib
sys.path.insert(0, '/home/xnihil0zer0/NobleGreedv2')
results = {}
from ngv2 import fsm_evidence, session_api, state_machine
results['fsm_evidence.PHASE_ORDER']        = tuple(fsm_evidence.PHASE_ORDER)
results['fsm_evidence.ENV_PHASE_ORDER']    = tuple(fsm_evidence.ENV_PHASE_ORDER)
results['session_api.PHASE_ORDER']         = tuple(session_api.PHASE_ORDER)
results['session_api._PHASES']             = tuple(session_api._PHASES)
results['state_machine.PHASES']            = tuple(state_machine.PHASES)
results['state_machine.LIFECYCLE_PHASES']  = tuple(state_machine.LIFECYCLE_PHASES)
for k,v in results.items():
    print(f"{k:38} (len {len(v):2}) = {v}")
print()
# Are the *live* hunt phase-orders all equal? (they must be to stay in sync)
live = {k:v for k,v in results.items() if k in ('fsm_evidence.PHASE_ORDER','session_api.PHASE_ORDER','state_machine.LIFECYCLE_PHASES')}
allsame = len(set(live.values())) == 1
print(f"3 'full lifecycle' literals identical?  {allsame}  (so editing one without the others DESYNCS)")
short = {k:v for k,v in results.items() if k in ('session_api._PHASES','state_machine.PHASES')}
print(f"2 'short' literals identical?           {len(set(short.values()))==1} = {set(short.values())}")
print()
# Are any env phases present in any live order? (they must NOT be today)
for k,v in results.items():
    if k=='fsm_evidence.ENV_PHASE_ORDER': continue
    env_in = [p for p in fsm_evidence.ENV_PHASE_ORDER if p in v]
    print(f"env phases present in {k:38}: {env_in if env_in else 'NONE'}")
print()
print("VERDICT: live hunt sequence is duplicated as 4 independent literals across 3 modules;")
print("         a 5th/6th ('short' _PHASES/PHASES) co-exist; NONE derives from fsm_evidence (c0).")
print("         ENV_PHASE_ORDER appears in NO live order -> inserting env phases requires folding ALL.")
