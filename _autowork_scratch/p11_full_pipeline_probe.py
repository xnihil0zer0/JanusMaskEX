import json, copy, sys
from pathlib import Path
from harness.planner.brief_loader import load_brief
from harness.orchestrator import load_config
from harness.planner.plan_validator import validate_plan
from harness.planner.plan_normalizer import normalize_plan
from harness.planner.blind_draft import _coerce_meta_task_types, _coerce_task_priorities, _synthesize_wiring_oracle_tokens

brief = load_brief(Path('brief_hooks_p11_build_evidence_perphase.md'))
wd = getattr(brief,'working_dir',None)
print('brief.working_dir =', wd)
print('brief.required_task_ids? ', getattr(brief,'required_task_ids',None))

# Use the gemini outbox draft (proven to be the p11 plan) as a stand-in for what
# the planner builds, then push it through normalize + validate as cli.py does.
gd = json.load(open('/home/xnihil0zer0/JanusMaskJR_agentwork/gemini/gemini-r1-notask-da39a3ee/outbox/plan_draft.json'))
print('\n=== gemini draft top keys:', list(gd.keys()))
print('required_task_ids in draft:', gd.get('required_task_ids'))

# Simulate the cli post-amend path: normalize_plan(final_plan, repo_root=effective_repo_root)
# effective repo root = working_dir for external brief
final = copy.deepcopy(gd)
_coerce_meta_task_types(final); _coerce_task_priorities(final)
_synthesize_wiring_oracle_tokens(final, wd)

# stamp brief metadata like _stamp_brief_metadata: required_task_ids from brief
rt = getattr(brief,'required_task_ids',None)
if rt:
    final['required_task_ids'] = rt
print('\n--- BEFORE normalize: task ids =', [t.get('task_id') for t in final.get('tasks',[])])
norm = normalize_plan(final, repo_root=Path(wd) if wd else None)
print('--- AFTER normalize: task ids =', [t.get('task_id') for t in norm.get('tasks',[])])
print('--- normalize dropped any oracle?', set(t.get('task_id') for t in final['tasks']) - set(t.get('task_id') for t in norm['tasks']))
norm['required_task_ids'] = final.get('required_task_ids')
v = validate_plan(norm)
print('\n>>> validate_plan(normalized) violations:', len(v))
for viol in v:
    print('   -', getattr(viol,'code',viol),'|',getattr(viol,'path',''),'|',getattr(viol,'message','')[:160])
