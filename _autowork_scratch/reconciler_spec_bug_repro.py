#!/usr/bin/env python3
"""Analytic repro: the reconciler brief's impl spec ('call reap_for_task on the
FIRST task') inherits reap_for_task's implicit-accept (`integrated.add(task_id)`)
and WRONGLY reaps a partially-integrated plan. Proves the bug AND that an explicit
all-integrated gate via _integrated_task_ids fixes it — matching oracle cases (a)/(b).
Run: PYTHONPATH=. python3 _autowork_scratch/reconciler_spec_bug_repro.py
"""
import json, tempfile, shutil, datetime
from pathlib import Path
from tools.brief_reaper import reap_for_task, _integrated_task_ids

STAMP = datetime.date.today().isoformat()

def _build(root: Path, accepted_ids):
    (root / 'state').mkdir(parents=True)
    (root / 'plan_hooks_demo.json').write_text(
        json.dumps({'tasks': [{'task_id': 'demo-task-1'}, {'task_id': 'demo-task-2'}]}))
    (root / 'brief_hooks_demo.md').write_text('# Demo Brief\n')
    with open(root / 'state' / 'impl_progress.jsonl', 'w') as f:
        for tid in accepted_ids:
            f.write(json.dumps({'task_id': tid, 'phase': 'accepted'}) + '\n')

def _current_spec_logic(root):
    """Brief AS-WRITTEN: take FIRST task id, call reap_for_task (implicit-accept)."""
    out = []
    for pf in sorted(root.glob('plan_hooks_*.json')):
        data = json.loads(pf.read_text())
        first = data['tasks'][0]['task_id']
        out.extend(reap_for_task(root, first, stamp=STAMP))
    return out

def _fixed_logic(root):
    """FIX: gate on ALL plan ids genuinely integrated BEFORE reaping."""
    out = []
    for pf in sorted(root.glob('plan_hooks_*.json')):
        data = json.loads(pf.read_text())
        plan_ids = [t['task_id'] for t in data.get('tasks', []) if isinstance(t, dict) and t.get('task_id')]
        if not plan_ids:
            continue
        integrated = _integrated_task_ids(root)
        if not all(tid in integrated for tid in plan_ids):
            continue  # partial -> skip
        out.extend(reap_for_task(root, plan_ids[0], stamp=STAMP))
    return out

def run_case(name, accepted_ids, logic):
    d = Path(tempfile.mkdtemp())
    try:
        _build(d, accepted_ids)
        integ = _integrated_task_ids(d)
        result = logic(d)
        reaped = not (d / 'brief_hooks_demo.md').exists()
        return {'integrated': sorted(integ), 'result': result, 'brief_reaped': reaped}
    finally:
        shutil.rmtree(d, ignore_errors=True)

print("=== sanity: does _integrated_task_ids count phase:accepted rows? ===")
print("  both-accepted ->", sorted(_integrated_task_ids.__wrapped__(Path('/nonexistent'))) if hasattr(_integrated_task_ids,'__wrapped__') else "(n/a)")

print("\n=== CURRENT SPEC LOGIC (reap_for_task on tasks[0]) ===")
a = run_case('(a) full', ['demo-task-1', 'demo-task-2'], _current_spec_logic)
b = run_case('(b) partial', ['demo-task-2'], _current_spec_logic)
print("  (a) fully-integrated :", a)
print("  (b) partial          :", b)

print("\n=== FIXED LOGIC (all-integrated gate) ===")
a2 = run_case('(a) full', ['demo-task-1', 'demo-task-2'], _fixed_logic)
b2 = run_case('(b) partial', ['demo-task-2'], _fixed_logic)
print("  (a) fully-integrated :", a2)
print("  (b) partial          :", b2)

print("\n=== ORACLE EXPECTATIONS: (a) reaped=['demo'], (b) reaped=[] ===")
ok = (a['result'] == ['demo'] and b['result'] == ['demo']          # current: (b) WRONGLY reaps
      and a2['result'] == ['demo'] and b2['result'] == []           # fixed: (b) correctly skips
      and a2['brief_reaped'] is True and b2['brief_reaped'] is False)
print("  CURRENT-SPEC reproduces the bug (b wrongly reaps):", b['result'] == ['demo'])
print("  FIXED-LOGIC passes BOTH oracle cases            :", a2['result'] == ['demo'] and b2['result'] == [])
print("\nRESULT:", "PROVEN — spec bug real, fix correct" if ok else "UNEXPECTED — re-examine")
