#!/usr/bin/env python3
"""Q4: Empirically establish the CURRENT gate behavior baseline.

Drives the REAL `_run_wire_up_gate` over two synthetic git trees:
  (a) a brand-new orphan MODULE file (no live importer)
  (b) a NEW orphan SYMBOL added to an ALREADY-TRACKED module

Reports for each: gate return value (True=reject, False=proceed), and whether
an `orphan_unwired` ledger row was written. READ-ONLY on production: builds its
own tmp git trees, never touches state/ or the repo.
"""
import json, os, subprocess, sys, tempfile, textwrap
from pathlib import Path

REPO = Path('/home/xnihil0zer0/JanusMaskJR')
sys.path.insert(0, str(REPO))

# import the real gate + flag reader
from harness import orchestrator as orch

def _git(args, cwd):
    return subprocess.run(['git'] + args, cwd=str(cwd), capture_output=True, text=True)

def build_tree(tmp, *, child_adds_new_module, child_adds_new_symbol):
    """Build a parent commit then a staging worktree with a child commit.

    Returns (worktree_root, staging_path, files_touched).
    Mirrors the gate's expectation: worktree_root HEAD = parent (pre-change),
    staging_path = parent+1 (the child commit), file on disk at staging_path/rel.
    """
    parent = tmp / 'parent'
    parent.mkdir()
    _git(['init', '-q'], parent)
    _git(['config', 'user.email', 'x@x'], parent)
    _git(['config', 'user.name', 'x'], parent)
    pkg = parent / 'harness'
    pkg.mkdir()
    (pkg / '__init__.py').write_text('')
    # an existing already-tracked module
    (pkg / 'existing_mod.py').write_text('def already():\n    return 0\n')
    _git(['add', '-A'], parent)
    _git(['commit', '-q', '-m', 'parent'], parent)

    # staging worktree = a clone (separate dir) at parent+1
    staging = tmp / 'staging'
    # use a plain copy + commit to emulate staging_path (the gate only reads disk + git show HEAD in worktree_root)
    subprocess.run(['cp', '-r', str(parent), str(staging)], check=True)
    files_touched = []
    if child_adds_new_module:
        # brand-new orphan module file, no importer
        (staging / 'harness' / 'orphan_new_module.py').write_text('def thing():\n    return 1\n')
        files_touched = ['harness/orphan_new_module.py']
    if child_adds_new_symbol:
        # add a new top-level callable to the ALREADY-tracked existing_mod.py
        (staging / 'harness' / 'existing_mod.py').write_text(
            'def already():\n    return 0\n\ndef brand_new():\n    return 1\n')
        files_touched = ['harness/existing_mod.py']
    _git(['add', '-A'], staging)
    _git(['commit', '-q', '-m', 'child'], staging)
    child_sha = _git(['rev-parse', 'HEAD'], staging).stdout.strip()
    # worktree_root must be the PARENT tree (HEAD not advanced) for `git show HEAD:<rel>`
    # The gate's _tracked_in_parent runs `git cat-file -e HEAD:<rel>` with cwd=worktree_root=parent.
    return parent, staging, files_touched, child_sha

def run_case(label, *, new_module, new_symbol):
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        worktree_root, staging_path, files_touched, child_sha = build_tree(
            tmp, child_adds_new_module=new_module, child_adds_new_symbol=new_symbol)
        state_dir = tmp / 'state'
        state_dir.mkdir()
        ledger = state_dir / 'impl_progress.jsonl'
        task = {'id': 'demo-task'}
        result = {'sha': child_sha}
        # We must NOT let the gate's rollback destroy anything outside tmp; it
        # operates on staging_path (our tmp). Acceptable.
        try:
            verdict = orch._run_wire_up_gate(
                task, files_touched, state_dir, 'demo-task',
                staging_path, worktree_root, result, str(worktree_root))
        except Exception as e:
            verdict = f'EXC:{type(e).__name__}:{e}'
        rows = []
        if ledger.exists():
            for ln in ledger.read_text().splitlines():
                if ln.strip():
                    rows.append(json.loads(ln))
        print(f'--- CASE: {label} ---')
        print(f'  files_touched          = {files_touched}')
        print(f'  gate verdict (True=REJECT/blocks, False=proceed) = {verdict!r}')
        print(f'  ledger rows written    = {len(rows)}')
        for r in rows:
            print(f'    row: phase={r.get("phase")!r} event={r.get("event")!r} file={r.get("file")!r}')
        print()

if __name__ == '__main__':
    print('wire_up_gate config flag (live):', orch._wire_up_gate_enabled())
    print()
    run_case('(a) brand-new ORPHAN MODULE file', new_module=True, new_symbol=False)
    run_case('(b) new ORPHAN SYMBOL in already-tracked module', new_module=False, new_symbol=True)
