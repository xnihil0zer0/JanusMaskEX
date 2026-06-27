#!/usr/bin/env python3
"""Analytic validation of the PROPOSED delegated reap_spent_briefs refactor.

Faithfully reproduces the proposed design (gate on _integrated_task_ids BEFORE
reap_for_task, per-plan try/except, call reap_for_task(root, plan_ids[0])) and
drives it through both:
  - the EXISTING committed oracle's fixture shapes (cases a/b/c/d), asserting
    the oracle's exact assertions still hold, and
  - the two NEW defect cases the shipped impl mis-handles:
      (e1) reject_rollback OVER-REAP  -> must NOT reap
      (e2) epic OVER-REAP            -> must NOT reap

Also probes the git side effect (reap_for_task stages `git rm --cached` on the
moved-from paths) in a REAL git repo.

Run: PYTHONPATH=. python3 _autowork_scratch/parity_fix_validation.py
"""
import json, datetime, tempfile, shutil, subprocess, os
from pathlib import Path
from tools.brief_reaper import reap_for_task, _integrated_task_ids

TODAY = datetime.date.today().isoformat()


# ---- PROPOSED delegated reap_spent_briefs (verbatim to the brief design) ----
def reap_spent_briefs_PROPOSED(root) -> list:
    root_path = Path(root)
    reaped = []
    for plan_path in sorted(root_path.glob('plan_hooks_*.json')):
        try:
            data = json.loads(plan_path.read_text(encoding='utf-8'))
            if not isinstance(data, dict):
                continue
            tasks = data.get('tasks')
            if not isinstance(tasks, list) or not tasks:
                continue
            plan_ids = [t['task_id'] for t in tasks
                        if isinstance(t, dict) and isinstance(t.get('task_id'), str) and t.get('task_id')]
            if not plan_ids:
                continue
            integrated = _integrated_task_ids(root_path)   # gate BEFORE reap_for_task
            if not all(tid in integrated for tid in plan_ids):
                continue
            reaped.extend(reap_for_task(root_path, plan_ids[0], stamp=TODAY))
        except Exception:
            continue
    return sorted(reaped)   # SHIP-WITH-ADDITION under test: keep sorted contract


def _mk(root, slug, task_ids, accepted_rows, *, epic=False, brief_lines='# Demo Brief\n'):
    """accepted_rows: list of dict rows to append to the ledger (raw)."""
    (root / 'state').mkdir(parents=True, exist_ok=True)
    (root / ('plan_hooks_%s.json' % slug)).write_text(
        json.dumps({'tasks': [{'task_id': t} for t in task_ids]}), encoding='utf-8')
    fm = '---\nepic: true\n---\n' if epic else ''
    (root / ('brief_hooks_%s.md' % slug)).write_text(fm + brief_lines, encoding='utf-8')
    with open(root / 'state' / 'impl_progress.jsonl', 'a', encoding='utf-8') as f:
        for r in accepted_rows:
            f.write(json.dumps(r) + '\n')


def case(label, build_fn, expect_reaped, expect_brief_present):
    d = Path(tempfile.mkdtemp())
    try:
        build_fn(d)
        slug = 'demo'
        plan = d / ('plan_hooks_%s.json' % slug)
        brief = d / ('brief_hooks_%s.md' % slug)
        out = reap_spent_briefs_PROPOSED(d)
        arch = d / '_autowork_archive' / TODAY / 'reconciled'
        brief_present = brief.exists()
        plan_present = plan.exists()
        arch_plan = (arch / ('plan_hooks_%s.json' % slug)).exists()
        arch_brief = (arch / ('brief_hooks_%s.md' % slug)).exists()
        # idempotency re-run
        out2 = reap_spent_briefs_PROPOSED(d)
        ok = (out == expect_reaped and brief_present == expect_brief_present
              and plan_present == expect_brief_present and out2 == [])
        if expect_reaped:
            ok = ok and arch_plan and arch_brief
        print('  %-46s reaped=%-9s brief@root=%-5s arch=%s/%s rerun=%s  %s'
              % (label, out, brief_present, arch_plan, arch_brief, out2,
                 'PASS' if ok else 'FAIL <<<'))
        return ok
    finally:
        shutil.rmtree(d, ignore_errors=True)


print('=== Delegated reap_spent_briefs: oracle cases + 2 defect cases ===')
results = []

# (a) fully-integrated -> reap  (oracle test a/c)
results.append(case('(a) fully-integrated -> REAP',
    lambda d: _mk(d, 'demo', ['demo-task-1', 'demo-task-2'],
                  [{'task_id': 'demo-task-1', 'phase': 'accepted'},
                   {'task_id': 'demo-task-2', 'phase': 'accepted'}]),
    ['demo'], False))

# (b) partial -> skip  (oracle test b)
results.append(case('(b) partial -> SKIP',
    lambda d: _mk(d, 'demo', ['demo-task-1', 'demo-task-2'],
                  [{'task_id': 'demo-task-2', 'phase': 'accepted'}]),
    [], True))

# (c) single-task fully-integrated -> reap  (oracle test c wiring)
results.append(case('(c) single-task integrated -> REAP',
    lambda d: _mk(d, 'demo', ['demo-task-1'],
                  [{'task_id': 'demo-task-1', 'phase': 'accepted'}]),
    ['demo'], False))

# (d) empty root -> clean noop  (oracle test d) -- separate, no fixture
d = Path(tempfile.mkdtemp())
try:
    out = reap_spent_briefs_PROPOSED(d)
    out2 = reap_spent_briefs_PROPOSED(d)
    ok = (out == [] and out2 == [])
    print('  %-46s reaped=%-9s rerun=%s  %s' % ('(d) empty root -> clean []', out, out2, 'PASS' if ok else 'FAIL <<<'))
    results.append(ok)
finally:
    shutil.rmtree(d, ignore_errors=True)

# (e1) reject_rollback OVER-REAP defect: accepted then reverted -> must SKIP
results.append(case('(e1) accepted+reject_rollback -> SKIP (defect#1)',
    lambda d: _mk(d, 'demo', ['demo-task-1', 'demo-task-2'],
                  [{'task_id': 'demo-task-1', 'phase': 'accepted'},
                   {'task_id': 'demo-task-2', 'phase': 'accepted'},
                   {'task_id': 'demo-task-2', 'event': 'reject_rollback'}]),
    [], True))

# (e2) epic OVER-REAP defect: fully integrated epic plan -> must SKIP
results.append(case('(e2) fully-integrated EPIC -> SKIP (defect#2)',
    lambda d: _mk(d, 'demo', ['demo-task-1'],
                  [{'task_id': 'demo-task-1', 'phase': 'accepted'}], epic=True),
    [], True))

# extra: malformed plan JSON among good ones -> fail-safe, still reaps the good one
d = Path(tempfile.mkdtemp())
try:
    (d / 'state').mkdir(parents=True)
    (d / 'plan_hooks_bad.json').write_text('{not json', encoding='utf-8')
    (d / 'brief_hooks_bad.md').write_text('# bad\n', encoding='utf-8')
    _mk(d, 'good', ['g1'], [{'task_id': 'g1', 'phase': 'accepted'}])
    out = reap_spent_briefs_PROPOSED(d)
    ok = (out == ['good'] and (d / 'plan_hooks_bad.json').exists()
          and not (d / 'plan_hooks_good.json').exists())
    print('  %-46s reaped=%-9s  %s' % ('(f) malformed plan among good -> fail-safe', out, 'PASS' if ok else 'FAIL <<<'))
    results.append(ok)
finally:
    shutil.rmtree(d, ignore_errors=True)

# ---- git side-effect probe in a REAL repo ----
print('\n=== git rm --cached side effect (real git repo) ===')
d = Path(tempfile.mkdtemp())
try:
    subprocess.run(['git', 'init', '-q', str(d)], check=True)
    subprocess.run(['git', '-C', str(d), 'config', 'user.email', 'x@y.z'], check=True)
    subprocess.run(['git', '-C', str(d), 'config', 'user.name', 'x'], check=True)
    _mk(d, 'gitdemo', ['t1'], [{'task_id': 't1', 'phase': 'accepted'}])
    # commit the tracked brief+plan so a deletion is meaningful
    subprocess.run(['git', '-C', str(d), 'add', '-A'], check=True)
    subprocess.run(['git', '-C', str(d), 'commit', '-qm', 'seed'], check=True)
    out = reap_spent_briefs_PROPOSED(d)
    # inspect index: staged deletions?
    status = subprocess.run(['git', '-C', str(d), 'status', '--porcelain'],
                            capture_output=True, text=True).stdout
    staged_dels = [l for l in status.splitlines() if l.startswith('D ')]
    untracked_arch = [l for l in status.splitlines() if '_autowork_archive' in l]
    print('  reaped:', out)
    print('  porcelain status:\n   ', '\n    '.join(status.splitlines()) or '(clean)')
    print('  staged deletions (D ):', staged_dels)
    print('  -> archived copy is UNTRACKED (move preserved):', bool(untracked_arch))
    results.append(out == ['gitdemo'] and len(staged_dels) == 2)
    print('  %s git rm --cached staged BOTH source paths, archive untracked'
          % ('PASS' if (out == ['gitdemo'] and len(staged_dels) == 2) else 'FAIL <<<'))
finally:
    shutil.rmtree(d, ignore_errors=True)

print('\n=== SUMMARY ===')
print('  cases passed: %d/%d' % (sum(1 for r in results if r), len(results)))
print('  VERDICT:', 'ALL GREEN — delegated design satisfies oracle + fixes both defects'
      if all(results) else 'FAILURE — re-examine')
