#!/usr/bin/env python3
"""SCRIPT 1 -- REPRODUCE THE HOLE.

Drive the REAL harness/orchestrator.py::_run_wire_up_gate against a hermetic
fixture in which an ALREADY-TRACKED module gains a NEW zero-caller top-level
function. Show empirically that the current gate returns False (PROCEED / does
NOT reject) and writes NO orphan ledger row -- i.e. the dead symbol lands
unflagged. This is the hole the brief claims.

For a control, also build a BRAND-NEW orphan module and show the current gate
DOES reject it (so we know the gate machinery is live in this fixture and the
pass on the symbol-addition case is the real hole, not a dead test harness).
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path('/home/xnihil0zer0/JanusMaskJR')
sys.path.insert(0, str(REPO))

from harness.orchestrator import _run_wire_up_gate  # noqa: E402


def git(args, cwd):
    return subprocess.run(['git', *args], cwd=str(cwd), capture_output=True, text=True)


def build_parent_repo(root: Path):
    """A minimal 'live' project with a live root that imports pkg.mod, plus an
    already-tracked pkg/mod.py defining one function `already`."""
    (root / 'harness').mkdir(parents=True)
    (root / 'pkg').mkdir(parents=True)
    # live root that the wire-up gate seeds from
    (root / 'harness' / 'orchestrator.py').write_text(
        'import pkg.mod\n\n'
        'def main():\n'
        '    pkg.mod.already()\n'
    )
    (root / 'pkg' / '__init__.py').write_text('')
    (root / 'pkg' / 'mod.py').write_text(
        'def already():\n'
        '    return 0\n'
    )
    git(['init', '-q'], root)
    git(['config', 'user.email', 'x@x'], root)
    git(['config', 'user.name', 'x'], root)
    git(['add', '-A'], root)
    git(['commit', '-q', '-m', 'parent: pkg.mod with already()'], root)


def make_staging_clone(parent: Path, staging: Path):
    """Clone parent into a separate staging dir (acts as staging_path). We keep
    parent as worktree_root (HEAD = parent commit, before this change)."""
    subprocess.run(['cp', '-a', str(parent) + '/.', str(staging)], check=True)


def main():
    tmp = Path(tempfile.mkdtemp(prefix='repro_hole_'))
    parent = tmp / 'parent'
    staging = tmp / 'staging'
    state_dir = tmp / 'state'
    parent.mkdir()
    staging.mkdir()
    state_dir.mkdir()
    build_parent_repo(parent)
    make_staging_clone(parent, staging)

    # --- THE HOLE FIXTURE: add a NEW zero-caller top-level fn to the
    # already-tracked pkg/mod.py in the STAGING tree, and commit it there. ---
    (staging / 'pkg' / 'mod.py').write_text(
        'def already():\n'
        '    return 0\n\n'
        'def brand_new_uncalled():\n'   # NEW, referenced nowhere
        '    return 1\n'
    )
    git(['add', '-A'], staging)
    git(['commit', '-q', '-m', 'staging: add brand_new_uncalled (zero caller)'], staging)
    head = git(['rev-parse', 'HEAD'], staging).stdout.strip()

    task = {'meta_task_type': 'harness_self_fix'}
    files_touched = ['pkg/mod.py']
    result = {'sha': head}

    ledger = state_dir / 'impl_progress.jsonl'
    rejected = _run_wire_up_gate(
        task=task,
        files_touched=files_touched,
        state_dir=state_dir,
        task_id='hole-symbol-addition',
        staging_path=staging,
        worktree_root=parent,   # HEAD here = parent (pkg/mod.py IS tracked in parent)
        result=result,
        working_dir=parent,
    )
    print('=== HOLE CASE: new zero-caller fn added to ALREADY-TRACKED pkg/mod.py ===')
    print('  _tracked_in_parent(pkg/mod.py) ->',
          git(['cat-file', '-e', 'HEAD:pkg/mod.py'], parent).returncode == 0)
    print('  _run_wire_up_gate returned (True=REJECT, False=PROCEED):', rejected)
    print('  ledger written?', ledger.exists())
    if ledger.exists():
        print('  ledger rows:')
        for ln in ledger.read_text().splitlines():
            print('   ', ln)
    print('  VERDICT: dead symbol', 'WAS REJECTED' if rejected else 'PASSED (unflagged) -> HOLE CONFIRMED')
    print()

    # --- CONTROL: brand-new orphan MODULE -> gate should REJECT ---
    parent2 = tmp / 'parent2'
    staging2 = tmp / 'staging2'
    state2 = tmp / 'state2'
    parent2.mkdir(); staging2.mkdir(); state2.mkdir()
    build_parent_repo(parent2)
    make_staging_clone(parent2, staging2)
    (staging2 / 'pkg' / 'orphan_new.py').write_text(
        'def nobody_imports_me():\n    return 7\n'
    )
    git(['add', '-A'], staging2)
    git(['commit', '-q', '-m', 'staging2: add orphan module'], staging2)
    head2 = git(['rev-parse', 'HEAD'], staging2).stdout.strip()
    ledger2 = state2 / 'impl_progress.jsonl'
    rejected2 = _run_wire_up_gate(
        task={'meta_task_type': 'harness_self_fix'},
        files_touched=['pkg/orphan_new.py'],
        state_dir=state2,
        task_id='control-new-module',
        staging_path=staging2,
        worktree_root=parent2,
        result={'sha': head2},
        working_dir=parent2,
    )
    print('=== CONTROL: brand-new orphan MODULE pkg/orphan_new.py ===')
    print('  _tracked_in_parent(pkg/orphan_new.py) ->',
          git(['cat-file', '-e', 'HEAD:pkg/orphan_new.py'], parent2).returncode == 0)
    print('  _run_wire_up_gate returned (True=REJECT, False=PROCEED):', rejected2)
    print('  ledger written?', ledger2.exists())
    if ledger2.exists():
        for ln in ledger2.read_text().splitlines():
            print('   ', ln)
    print('  VERDICT: new orphan module',
          'WAS REJECTED (gate machinery is LIVE)' if rejected2 else 'PASSED (gate inert?!)')
    print()
    print('TMP (cleaned at exit):', tmp)


if __name__ == '__main__':
    main()
