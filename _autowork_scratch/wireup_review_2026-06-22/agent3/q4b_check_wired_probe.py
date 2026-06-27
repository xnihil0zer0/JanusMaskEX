#!/usr/bin/env python3
"""Q4b: Probe WHY the orphan-module case proceeded. Drive check_wired directly
on the synthetic staging tree and on a richer tree to show the new-FILE gate
DOES reject when discover sees a live root. Establishes that the existing gate
(module-level) is real for new files but the synthetic minimal tree had no
LIVE_ROOTS => external-rootless no-op branch.
"""
import subprocess, sys, tempfile
from pathlib import Path
REPO = Path('/home/xnihil0zer0/JanusMaskJR')
sys.path.insert(0, str(REPO))
from harness.wire_up import check_wired, LIVE_ROOTS, discover_live_roots
from harness.rebuild.discover import discover_modules

def _git(args, cwd):
    return subprocess.run(['git'] + args, cwd=str(cwd), capture_output=True, text=True)

def build_rich(tmp):
    """A tree that HAS a LIVE_ROOT (harness/orchestrator.py) importing one module,
    plus a brand-new orphan module with no importer."""
    root = tmp / 'rich'
    root.mkdir()
    h = root / 'harness'
    h.mkdir()
    (h / '__init__.py').write_text('')
    # a real live root from LIVE_ROOTS
    (h / 'orchestrator.py').write_text('from harness import wired_mod\n\ndef main():\n    return wired_mod.go()\n')
    (h / 'wired_mod.py').write_text('def go():\n    return 1\n')
    # brand-new orphan: nothing imports it
    (h / 'orphan_new_module.py').write_text('def thing():\n    return 1\n')
    return root

with tempfile.TemporaryDirectory() as td:
    tmp = Path(td)
    root = build_rich(tmp)
    mods, tests, seeds = discover_modules(root)
    print('discovered modules:', sorted(mods))
    print('LIVE_ROOTS present in tree:', [r for r in LIVE_ROOTS if (root / r).is_file()])
    print('discover_live_roots:', discover_live_roots(root))
    for rel in ('harness/wired_mod.py', 'harness/orphan_new_module.py'):
        wr = check_wired(root, rel)
        print(f'\ncheck_wired({rel}):')
        print(f'  wired={wr.wired}  reason={wr.reason}')
