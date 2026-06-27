#!/usr/bin/env python3
"""Q1: Model the PROPOSED Phase-2 report-only branch EXACTLY as the brief
specifies (brief_hooks_wire_up_runtime_reachability_gate.md, Implementation
Note 2) and prove that, in the delivered state, an orphan symbol:
  (1) with the runtime flag OFF (the SHIPPED default): produces NO row and the
      gate proceeds (strict no-op) -> orphan auto-commits.
  (2) with the runtime flag ON (the maximum the brief delivers): writes a
      `phase:'report'` row and STILL proceeds (verdict stays False) ->
      orphan STILL auto-commits. The gate is a LOGGER, never a blocker.

This faithfully reimplements the brief's report-only branch logic in isolation
(the production code does not yet contain it) using the REAL Phase-1 primitive
contract (new_top_level_callables) modeled here, and the EXACT control-flow the
brief mandates: 'control always continue()s', 'MUST NEVER ... return True'.
"""
import json, subprocess, sys, tempfile, time
from pathlib import Path
REPO = Path('/home/xnihil0zer0/JanusMaskJR')
sys.path.insert(0, str(REPO))
import ast

def new_top_level_callables(parent_src, child_src):
    """Faithful model of the Phase-1 AST-diff primitive (brief Note 2)."""
    def tops(src):
        names = set()
        try:
            tree = ast.parse(src or '')
        except SyntaxError:
            return names
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names.add(node.name)
            elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Lambda):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        names.add(t.id)
        return names
    return sorted(tops(child_src) - tops(parent_src))

def proposed_runtime_branch(task, rel, parent_src, child_src, state_dir, task_id,
                            files_touched, result, flag_enabled):
    """EXACT control flow of the brief's Implementation Note 2 report-only branch.

    Returns the gate's per-file action: 'continue' always (never rolls back,
    never returns True). Writes a report row iff armed AND uncovered.
    Returns (action, verdict_contribution) where verdict_contribution is always
    False (the symbol path 'MUST NEVER ... return True').
    """
    if not flag_enabled:
        # default-OFF: byte-identical to today -> plain continue, no row
        return 'continue', False
    try:
        new_syms = new_top_level_callables(parent_src, child_src)
        _c = task.get('constraints') if isinstance(task.get('constraints'), dict) else {}
        _contract = _c.get('integration_contract') if isinstance(_c.get('integration_contract'), dict) else {}
        _entrypoints = _contract.get('entrypoints') if isinstance(_contract.get('entrypoints'), list) else []
        _exempt_raw = task.get('wire_exempt') or _c.get('wire_exempt') or []
        _exempt = set(_exempt_raw) if isinstance(_exempt_raw, (list, tuple, set)) else set()
        uncovered = sorted(s for s in new_syms if s not in _exempt and not _entrypoints)
        if uncovered:
            row = {'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                   'phase': 'report', 'task_id': task_id,
                   'event': 'orphan_symbol_unwired', 'commit_sha': result.get('sha'),
                   'files': files_touched, 'file': rel, 'symbols': uncovered,
                   'reason': 'new top-level callables added with no integration_contract '
                             'and no wire_exempt; runtime-reachability contract missing '
                             '(report-only, default-OFF)'}
            (state_dir / 'impl_progress.jsonl').open('a').write(json.dumps(row) + '\n')
    except Exception:
        pass
    # The brief: "Then `continue` (the existing behavior). The symbol path MUST
    # NEVER call _rollback_rejected_commit, remove_staging_worktree, _mark_blocked,
    # or return True."
    return 'continue', False

def run(label, *, flag_enabled, task):
    with tempfile.TemporaryDirectory() as td:
        state_dir = Path(td) / 'state'; state_dir.mkdir()
        parent_src = 'def already():\n    return 0\n'
        child_src = 'def already():\n    return 0\n\ndef brand_new():\n    return 1\n'
        result = {'sha': 'deadbeef'}
        files_touched = ['pkg/mod.py']
        action, verdict = proposed_runtime_branch(
            task, 'pkg/mod.py', parent_src, child_src, state_dir,
            'orphan-symbol-task', files_touched, result, flag_enabled)
        ledger = state_dir / 'impl_progress.jsonl'
        rows = []
        if ledger.exists():
            rows = [json.loads(l) for l in ledger.read_text().splitlines() if l.strip()]
        print(f'--- {label} ---')
        print(f'  runtime flag enabled = {flag_enabled}')
        print(f'  new top-level callables added = {new_top_level_callables(parent_src, child_src)}')
        print(f'  gate per-file action = {action!r}  (always continue; never reject)')
        print(f'  gate returns True (BLOCK)? = {verdict}  (False => orphan symbol AUTO-COMMITS)')
        print(f'  ledger rows written = {len(rows)}')
        for r in rows:
            print(f'    row: phase={r.get("phase")!r} event={r.get("event")!r} symbols={r.get("symbols")}')
        # the orphan lands in EVERY case (verdict False)
        print(f'  ORPHAN SYMBOL OUTCOME = {"LANDS (auto-commits)" if not verdict else "BLOCKED"}')
        print()

if __name__ == '__main__':
    no_contract = {'id': 'orphan-symbol-task'}  # no integration_contract, no wire_exempt
    print('Modeling the EXACT report-only branch from '
          'brief_hooks_wire_up_runtime_reachability_gate.md (Impl Note 2).\n')
    run('DELIVERED DEFAULT (flag OFF -- the shipped state)', flag_enabled=False, task=no_contract)
    run('ARMED (flag ON -- the MAX the brief delivers, still report-only)', flag_enabled=True, task=no_contract)
