"""ADVERSARIAL empirical GREEN proof for brief_hooks_reap_spent_briefs_parity_impl_fix.md.

Faithfully implements the brief's Deliverables-mandated reap_spent_briefs, monkeypatches
harness.state_reconciler.reap_spent_briefs with it, then imports BOTH oracle test modules
and runs EVERY test function in them, reporting pass/fail per test.

Run:  PYTHONPATH=/home/xnihil0zer0/JanusMaskJR python _autowork_scratch/parity_fix_proof.py
"""
import sys
import traceback
import inspect
from pathlib import Path

import harness.state_reconciler as sr


# ---- FAITHFUL impl EXACTLY as the brief's Deliverables mandate ----
def reap_spent_briefs(root, *, stamp=None) -> list:
    from pathlib import Path as _Path
    import json
    import datetime
    try:
        from tools.brief_reaper import reap_for_task, _integrated_task_ids
    except Exception:
        return []
    root_path = _Path(root)
    if stamp is None:
        stamp = datetime.date.today().isoformat()
    try:
        integrated = _integrated_task_ids(root_path)
    except Exception:
        integrated = set()
    reaped = []
    try:
        plans = sorted(root_path.glob('plan_hooks_*.json'))
    except OSError:
        plans = []
    for plan_path in plans:
        try:
            data = json.loads(plan_path.read_text(encoding='utf-8'))
            if not isinstance(data, dict):
                continue
            plan_ids = [t['task_id'] for t in data.get('tasks', [])
                        if isinstance(t, dict) and t.get('task_id')]
            if not plan_ids:
                continue
            # ALL-INTEGRATED GATE: guard reap_for_task's implicit-accept of plan_ids[0]
            if any(tid not in integrated for tid in plan_ids):
                continue
            # THE FIX: source the reaped list SOLELY from reap_for_task's return value
            reaped.extend(reap_for_task(root_path, plan_ids[0], stamp=stamp))
        except Exception:
            continue
    return sorted(reaped)


# Monkeypatch the live symbol so reap_stale_disk's internal call also uses the faithful impl.
sr.reap_spent_briefs = reap_spent_briefs

# Re-bind the name in the already-imported oracle modules if they did `from ... import reap_spent_briefs`.
import tests.harness.test_reap_spent_briefs_parity as parity_mod
import tests.harness.test_reconciler_reaps_spent_briefs as recon_mod
parity_mod.reap_spent_briefs = reap_spent_briefs
recon_mod.reap_spent_briefs = reap_spent_briefs


def _run_module(mod):
    import tempfile
    results = []
    fns = [(n, f) for n, f in vars(mod).items()
           if n.startswith('test_') and inspect.isfunction(f)]
    for name, fn in fns:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            try:
                sig = inspect.signature(fn)
                kwargs = {}
                if 'tmp_path' in sig.parameters:
                    kwargs['tmp_path'] = tmp_path
                fn(**kwargs)
                results.append((name, 'PASS', None))
            except Exception:
                results.append((name, 'FAIL', traceback.format_exc()))
    return results


def main():
    all_ok = True
    for label, mod in [('test_reap_spent_briefs_parity', parity_mod),
                       ('test_reconciler_reaps_spent_briefs', recon_mod)]:
        print('=' * 70)
        print(label)
        print('=' * 70)
        for name, status, tb in _run_module(mod):
            print('  %-55s %s' % (name, status))
            if status == 'FAIL':
                all_ok = False
                print('    ' + '\n    '.join(tb.splitlines()))
    print('=' * 70)
    print('OVERALL:', 'ALL GREEN' if all_ok else 'SOME FAILED')
    return 0 if all_ok else 1


if __name__ == '__main__':
    sys.exit(main())
