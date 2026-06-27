#!/usr/bin/env python3
"""SCRIPT 2 -- VERIFY whether the brief's static gate is itself foolable by a
DEAD / never-executed caller.

Build trees where the new symbol's ONLY reference is in dead/unreachable code,
run the faithful brief primitive, and report whether it says WIRED (ok=True).
If a dead reference -> ok=True, the static gate is a half-measure (it checks
reference EXISTENCE, not live reachability), which the brief itself states.
"""
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from brief_primitive import check_new_symbols_called  # noqa: E402

PARENT_MOD = 'def already():\n    return 0\n'
CHILD_MOD = (
    'def already():\n'
    '    return 0\n\n'
    'def brand_new_uncalled():\n'
    '    return 1\n'
)


def build_tree(tmp: Path, extra_files: dict, child_mod: str = CHILD_MOD):
    (tmp / 'harness').mkdir(parents=True, exist_ok=True)
    (tmp / 'pkg').mkdir(parents=True, exist_ok=True)
    (tmp / 'harness' / 'orchestrator.py').write_text('import pkg.mod\n')
    (tmp / 'pkg' / '__init__.py').write_text('')
    (tmp / 'pkg' / 'mod.py').write_text(child_mod)
    for rel, content in extra_files.items():
        p = tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)


def run_case(name, extra_files, *, exempt=(), child_mod=CHILD_MOD,
             target='brand_new_uncalled'):
    tmp = Path(tempfile.mkdtemp(prefix='probe_'))
    build_tree(tmp, extra_files, child_mod=child_mod)
    res = check_new_symbols_called(tmp, 'pkg/mod.py', PARENT_MOD, exempt=exempt)
    print(f'=== {name} ===')
    print('  new_symbols:', res.new_symbols)
    print('  ok=%s  unwired=%s  exempted=%s' % (res.ok, res.unwired, res.exempted))
    print('  reason:', res.reason)
    flagged = target in res.unwired
    print('  -> %s : %s' % (target, 'FLAGGED unwired' if flagged else 'PASSED as wired'))
    print()
    return res


print('############ BASELINE SANITY ############\n')

run_case('A. truly zero reference (should FLAG)', {})

run_case('B. LIVE caller in a real reachable module (should PASS)', {
    'pkg/caller.py': ('from pkg.mod import brand_new_uncalled\n\n'
                      'def go():\n    return brand_new_uncalled()\n'),
})

run_case('C. wire_exempt marker (should PASS via exempt)', {}, exempt=('brand_new_uncalled',))

run_case('D. caller ONLY in tests/ (should FLAG -- test caller does not count)', {
    'tests/test_x.py': ('from pkg.mod import brand_new_uncalled\n\n'
                        'def test_it():\n    assert brand_new_uncalled() == 1\n'),
})

run_case('E. caller ONLY in _autowork_scratch/ (should FLAG)', {
    '_autowork_scratch/s.py': ('from pkg.mod import brand_new_uncalled\n'
                               'brand_new_uncalled()\n'),
})

print('############ DEAD / FOOLABLE-CALLER PROBES ############\n')

# D1: reference inside `if False:` block (statically present, never runs)
run_case('F1. ref inside `if False:` (DEAD branch)', {
    'pkg/caller.py': ('from pkg.mod import brand_new_uncalled\n\n'
                      'if False:\n'
                      '    brand_new_uncalled()\n'),
})

# F2: reference inside an ORPHAN/unreferenced function nobody ever calls
run_case('F2. ref inside an unreferenced (dead) function', {
    'pkg/caller.py': ('from pkg.mod import brand_new_uncalled\n\n'
                      'def never_called_anywhere():\n'
                      '    return brand_new_uncalled()\n'),
})

# F3: reference inside a flag-gated branch that never runs
run_case('F3. ref behind an always-false flag guard', {
    'pkg/caller.py': ('from pkg.mod import brand_new_uncalled\n\n'
                      'ENABLED = False\n'
                      'def go():\n'
                      '    if ENABLED:\n'
                      '        return brand_new_uncalled()\n'),
})

# F4: reference ONLY inside a string literal (brief's AST test should NOT see it)
run_case('F4. name ONLY inside a string literal', {
    'pkg/caller.py': ('X = "we should call brand_new_uncalled() someday"\n'),
})

# F5: mutual reference between two NEW siblings in the SAME commit
#     (brief Non-Goal (c) lines 262-264) -- new fn B references new fn A.
run_case('F5. new symbol referenced ONLY by a sibling NEW fn (same commit)', {},
         child_mod=(
             'def already():\n    return 0\n\n'
             'def brand_new_uncalled():\n    return 1\n\n'
             'def also_brand_new():\n    return brand_new_uncalled()\n'
         ))
