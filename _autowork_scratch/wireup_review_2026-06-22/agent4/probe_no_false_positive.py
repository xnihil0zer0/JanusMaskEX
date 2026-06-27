#!/usr/bin/env python3
"""SCRIPT 5 -- confirm the brief's load-bearing false-positive guard:
a PRE-EXISTING zero-caller symbol (already in parent) is NEVER flagged because
it is not 'new in this commit'. This is what protects the current tree's
cleanup_state/reap_stale_disk/etc. from being retroactively flagged."""
import sys, tempfile
from pathlib import Path
sys.path.insert(0, '/home/xnihil0zer0/JanusMaskJR/_autowork_scratch/wireup_review_2026-06-22/agent4')
from brief_primitive import check_new_symbols_called

tmp = Path(tempfile.mkdtemp(prefix='fp_'))
(tmp/'harness').mkdir(parents=True); (tmp/'pkg').mkdir(parents=True)
(tmp/'harness'/'orchestrator.py').write_text('import pkg.mod\n')
(tmp/'pkg'/'__init__.py').write_text('')
# PARENT already had a zero-caller orphan `old_uncalled`; child ADDS only a
# new symbol that DOES have a live caller.
parent_src = ('def already():\n    return 0\n\n'
              'def old_uncalled():\n    return 9\n')
(tmp/'pkg'/'mod.py').write_text(parent_src +
    '\ndef new_and_called():\n    return 1\n')
(tmp/'pkg'/'caller.py').write_text(
    'from pkg.mod import new_and_called\nnew_and_called()\n')
res = check_new_symbols_called(tmp, 'pkg/mod.py', parent_src)
print('new_symbols:', res.new_symbols)
print('ok=%s unwired=%s' % (res.ok, res.unwired))
print("old_uncalled flagged?", 'old_uncalled' in res.unwired,
      "(MUST be False -- pre-existing, not new-in-commit)")
print("new_and_called flagged?", 'new_and_called' in res.unwired,
      "(MUST be False -- has a live caller)")
