"""Fix-forward red-pair acceptance predicate.

The EXISTING-module complement of orchestrator._new_module_red_by_absence: decides whether
a RED ``test_authoring`` oracle for an EXISTING module is a legitimate fix-forward red-pair
(a paired non-test_authoring impl in the same plan, verified by the oracle's OWN authored
test file) and therefore acceptable through the acceptance gate. Mirrors the keystone
file-keyed red-pair logic in harness/planner/plan_normalizer.py (kept self-contained so the
trust boundary does not import the planner surface).
"""
from __future__ import annotations
import json
import re
from pathlib import Path
_MODULE_RE = re.compile('[A-Za-z_][A-Za-z0-9_]*(?:\\.[A-Za-z_][A-Za-z0-9_]*)*')

def _meta_type(task):
    if not isinstance(task, dict):
        return None
    return task.get('meta_task_type') or (task.get('constraints') or {}).get('meta_task_type')

def is_fix_forward_redpair(task, worktree_root, sibling_tasks) -> bool:
    """True iff ``task`` is a RED test_authoring oracle for an EXISTING module that forms a
    valid fix-forward red-pair with some impl in ``sibling_tasks``. Never raises."""
    try:
        if _meta_type(task) != 'test_authoring':
            return False
        mt = task.get('mutation_target')
        if not isinstance(mt, str) or not mt:
            return False
        if '/' in mt or '\\' in mt or '..' in mt or mt.endswith('.py'):
            return False
        if not _MODULE_RE.fullmatch(mt):
            return False
        target_rel = mt.replace('.', '/') + '.py'
        if not (Path(worktree_root) / target_rel).is_file():
            return False
        own_files = {f for f in task.get('files_touched') or [] if isinstance(f, str) and f}
        if not own_files:
            return False
        if not isinstance(sibling_tasks, list):
            return False
        for impl in sibling_tasks:
            if not isinstance(impl, dict):
                continue
            if _meta_type(impl) == 'test_authoring':
                continue
            impl_files = {f for f in impl.get('files_touched') or [] if isinstance(f, str)}
            if target_rel not in impl_files:
                continue
            vc = impl.get('verification_command')
            if isinstance(vc, str) and any((of in vc for of in own_files)):
                return True
        return False
    except Exception:
        return False

def load_sibling_tasks(state_dir, task, task_id) -> list:
    """Load sibling task dicts: every id in task['dependencies'] plus every task whose
    'dependencies' contains task_id, read from state/tasks/processed/, state/tasks/ (base),
    and state/tasks/blocked/. A blocked sibling is included only when still live-retryable;
    a blocked sibling <sib> carrying a state/tasks/blocked/<sib>.exhausted sidecar is
    permanently dead and is skipped. Skips missing/corrupt files. Never raises."""
    out = []
    try:
        sd = Path(state_dir)
        proc = sd / 'tasks' / 'processed'
        base = sd / 'tasks'
        blocked = sd / 'tasks' / 'blocked'
        seen = set()

        def _dead_blocked(d, sib):
            try:
                if d != blocked or not isinstance(sib, str) or not sib:
                    return False
                return (blocked / (sib + '.exhausted')).exists()
            except Exception:
                return False

        def _read(tid):
            if not isinstance(tid, str) or not tid or tid in seen:
                return
            seen.add(tid)
            for d in (proc, base, blocked):
                if _dead_blocked(d, tid):
                    continue
                p = d / (tid + '.json')
                try:
                    if p.is_file():
                        out.append(json.loads(p.read_text()))
                        return
                except Exception:
                    continue
        deps = task.get('dependencies') or [] if isinstance(task, dict) else []
        for tid in deps:
            _read(tid)
        for d in (proc, base, blocked):
            try:
                if not d.is_dir():
                    continue
                for p in d.glob('*.json'):
                    if _dead_blocked(d, p.stem):
                        continue
                    try:
                        obj = json.loads(p.read_text())
                    except Exception:
                        continue
                    if isinstance(obj, dict) and task_id in (obj.get('dependencies') or []):
                        tid = obj.get('task_id') or p.stem
                        if tid not in seen:
                            seen.add(tid)
                            out.append(obj)
            except Exception:
                continue
    except Exception:
        return out
    return out
