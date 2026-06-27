import json, sys
from pathlib import Path
from harness.planner.plan_validator import validate_plan
from harness.planner.blind_draft import _coerce_meta_task_types, _coerce_task_priorities, _synthesize_wiring_oracle_tokens

WR = Path('/home/xnihil0zer0/JanusMaskJR_agentwork')
for agent in ['claude','gemini']:
    matches = sorted(WR.glob(f'{agent}/{agent}-r1-*/outbox/plan_draft.json'), key=lambda p:p.stat().st_mtime, reverse=True)
    if not matches:
        print(f'=== {agent}: NO draft artifact ===')
        continue
    p = matches[0]
    print(f'=== {agent} draft: {p} (mtime {p.stat().st_mtime}) ===')
    try:
        d = json.loads(p.read_text())
    except Exception as e:
        print('  JSON LOAD FAIL:', e); continue
    tasks = d.get('tasks') if isinstance(d,dict) else None
    print('  top keys:', list(d.keys()) if isinstance(d,dict) else type(d))
    print('  working_dir:', d.get('working_dir') if isinstance(d,dict) else None)
    if isinstance(tasks,list):
        print('  task count:', len(tasks))
        for t in tasks:
            if isinstance(t,dict):
                print('   id=%r meta=%r prio=%r mut=%r ft=%r'%(t.get('task_id'),t.get('meta_task_type'),t.get('priority'),t.get('mutation_target'),t.get('files_touched')))
                print('     vcmd=%r'%(t.get('verification_command')))
    # Replicate the pre-validation coercions the collector applies
    import copy
    d2 = copy.deepcopy(d)
    try:
        _coerce_meta_task_types(d2)
        _coerce_task_priorities(d2)
        _synthesize_wiring_oracle_tokens(d2, working_dir=d2.get('working_dir') or '/home/xnihil0zer0/NobleGreedv2')
    except Exception as e:
        print('  coerce error:', e)
    v = validate_plan(d2)
    print('  >>> validate_plan violations (post-coerce): %d'%len(v))
    for viol in v:
        print('      -', getattr(viol,'code',viol), '|', getattr(viol,'path',''), '|', getattr(viol,'message',''))
    # Also raw (no coerce)
    vr = validate_plan(d)
    print('  >>> validate_plan violations (RAW): %d'%len(vr))
    for viol in vr:
        print('      -', getattr(viol,'code',viol), '|', getattr(viol,'path',''))
