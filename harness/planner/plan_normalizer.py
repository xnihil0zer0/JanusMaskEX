"""Deterministic leaf-plan normalizer (fully-hands-off backstop).

For fully-hands-off autowork the daemon auto-plans each child brief and must get
an EXECUTABLE plan with ZERO operator vetting. Two recurring 2-agent-merge (or
single-agent draft) defects deadlock execution:

1. DUPLICATE test_authoring oracle -- both agents propose an oracle for the same
   ``mutation_target`` (e.g. claude ``symbol-ledger-oracle`` + gemini
   ``oracle-symbol-ledger``) and the merge keeps BOTH (one orphaned).
2. INVERTED impl/oracle dependency -- the impl task depends on the oracle
   ("oracle-first"). But the auto-commit non-vacuity mutation gate REQUIRES the
   target module to already EXIST in the staging worktree when a test_authoring
   oracle is verified (it applies the mutant to ``mutation_target`` and reruns
   the test). So an oracle-first ordering makes the oracle un-acceptable ->
   retried -> ``.exhausted`` -> A3 terminally blocks the impl -> child never
   completes.

``normalize_plan`` corrects ANY plan deterministically: DEDUPE ORACLES + ENFORCE
MODULE-FIRST. It is PURE (no I/O), IDEMPOTENT (running twice == once), and a
NO-OP for an already-correct plan. It preserves every field it does not touch and
keeps ``validate_plan(normalized)`` violation-free whenever the input was
field-complete.
"""
from __future__ import annotations

import copy


def _module_file_for(mutation_target: str) -> str:
    """``harness.symbol_ledger`` -> ``harness/symbol_ledger.py``."""
    return mutation_target.replace('.', '/') + '.py'


def _is_test_authoring(task: object) -> bool:
    return (
        isinstance(task, dict)
        and task.get('meta_task_type') == 'test_authoring'
        and isinstance(task.get('mutation_target'), str)
        and bool(task.get('mutation_target'))
    )


def _find_impl_for(tasks: list, module_file: str) -> dict | None:
    """First NON-test_authoring task whose ``files_touched`` creates module_file."""
    for t in tasks:
        if not isinstance(t, dict):
            continue
        if t.get('meta_task_type') == 'test_authoring':
            continue
        ft = t.get('files_touched')
        if isinstance(ft, list) and module_file in ft:
            return t
    return None


def normalize_plan(plan: dict) -> dict:
    """Return a normalized COPY of ``plan`` (dedupe oracles + enforce module-first).

    A non-dict, a plan with no ``tasks`` list, or an empty task list is returned
    unchanged (the input object itself, not a copy) -- there is nothing to fix.
    """
    if not isinstance(plan, dict):
        return plan
    tasks = plan.get('tasks')
    if not isinstance(tasks, list) or not tasks:
        return plan

    out = copy.deepcopy(plan)
    tasks = out['tasks']

    # ----------------------------- DEDUPE ORACLES ----------------------------- #
    groups: dict[str, list] = {}
    for t in tasks:
        if _is_test_authoring(t):
            groups.setdefault(t['mutation_target'], []).append(t)

    dropped_to_kept: dict[str, str] = {}
    for mt, grp in groups.items():
        if len(grp) <= 1:
            continue
        module_file = _module_file_for(mt)
        impl = _find_impl_for(tasks, module_file)
        kept = None
        # Prefer the oracle whose own test file is referenced by the module
        # impl task's verification_command.
        if impl is not None:
            vcmd = impl.get('verification_command') or ''
            if isinstance(vcmd, str) and vcmd:
                for cand in sorted(grp, key=lambda c: str(c.get('task_id') or '')):
                    for f in (cand.get('files_touched') or []):
                        if isinstance(f, str) and f and f in vcmd:
                            kept = cand
                            break
                    if kept is not None:
                        break
        # Otherwise the first by task_id (deterministic).
        if kept is None:
            kept = sorted(grp, key=lambda c: str(c.get('task_id') or ''))[0]
        for cand in grp:
            if cand is kept:
                continue
            cid = cand.get('task_id')
            if cid is not None:
                dropped_to_kept[cid] = kept.get('task_id')

    if dropped_to_kept:
        tasks = [
            t for t in tasks
            if not (isinstance(t, dict) and t.get('task_id') in dropped_to_kept)
        ]
        out['tasks'] = tasks
        # Rewrite every dependency referencing a dropped id to the kept id;
        # drop a resulting self-dependency and de-duplicate, order-preserving.
        for t in tasks:
            if isinstance(t, dict) and isinstance(t.get('dependencies'), list):
                new_deps: list = []
                seen: set = set()
                for d in t['dependencies']:
                    nd = dropped_to_kept.get(d, d)
                    if nd == t.get('task_id'):
                        continue
                    if nd not in seen:
                        seen.add(nd)
                        new_deps.append(nd)
                t['dependencies'] = new_deps

    # --------------------------- ENFORCE MODULE-FIRST -------------------------- #
    for o in tasks:
        if not _is_test_authoring(o):
            continue
        module_file = _module_file_for(o['mutation_target'])
        impl = _find_impl_for(tasks, module_file)
        if impl is None:
            # No impl creates this module -> it depends on a pre-existing module;
            # leave O untouched.
            continue
        impl_id = impl.get('task_id')
        o_id = o.get('task_id')
        if impl_id is None or o_id is None or impl_id == o_id:
            continue
        # Break any inversion FIRST (remove O from I.dependencies) so adding the
        # I->O edge below can never create a direct cycle.
        impl_deps = impl.get('dependencies')
        if isinstance(impl_deps, list) and o_id in impl_deps:
            impl['dependencies'] = [d for d in impl_deps if d != o_id]
        # Ensure O depends on I (module-first).
        o_deps = o.get('dependencies')
        if not isinstance(o_deps, list):
            o_deps = []
            o['dependencies'] = o_deps
        if impl_id not in o_deps:
            o_deps.append(impl_id)

    return out
