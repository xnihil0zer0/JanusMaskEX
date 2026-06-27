#!/usr/bin/env python3
"""Analytic root-cause + feasibility verification for smoke-gated-gate-impl.

Operates ONLY on COPIES of production under this scratch dir.  Never edits the
live orchestrator_worker.py.

Three independent proofs, each printing explicit PASS/FAIL:

  PROOF 1 (root cause A -- patch apply): take the WORKER'S OWN failed emission
    (state/output/smoke-gated-gate-impl.py) and run its first __JANUSMASK_PATCHES__
    entry through the SAME _apply_symbol_patch the auto-committer uses, against a
    COPY of orchestrator_worker.py.  Confirm it raises the exact ledger error
    "unsupported extra assignment target kind: Attribute".

  PROOF 2 (root cause B -- broken oracle): show that the committed oracle's
    test_regression_no_unapproved_or_manifest_files_created is UNCONDITIONALLY
    red because pre-existing tree files contain 'manifest' in their name -- no
    impl on orchestrator_worker.py can ever turn it green.

  PROOF 3 (feasible shape): build a 2-entry __JANUSMASK_PATCHES__ list
    (predicate via R-anchor on a small helper + one-line gate rewire of main),
    apply BOTH to a COPY, assert parse + apply succeed, import _task_bypasses_fuzz
    from the patched copy and assert the oracle's behavioral cases hold, AND grep
    the patched main to confirm the gate now calls the predicate (wiring proof).
"""
import ast
import importlib.util
import sys
from pathlib import Path

REPO = Path('/home/xnihil0zer0/JanusMaskJR')
sys.path.insert(0, str(REPO))

from harness.git_integration import _apply_symbol_patch  # noqa: E402

WORKER = REPO / 'harness' / 'orchestrator_worker.py'
EMISSION = REPO / 'state' / 'output' / 'smoke-gated-gate-impl.py'
SCRATCH = Path(__file__).resolve().parent

results = []


def record(name, ok, detail=''):
    tag = 'PASS' if ok else 'FAIL'
    print(f'[{tag}] {name}: {detail}')
    results.append((name, ok))


# ---------------------------------------------------------------------------
# PROOF 1 -- reproduce the attempt-2 auto_commit_patch_failed
# ---------------------------------------------------------------------------
print('=' * 72)
print('PROOF 1 -- reproduce attempt-2 apply failure from worker emission')
print('=' * 72)
src = WORKER.read_text()
ns: dict = {}
exec(EMISSION.read_text(), ns)  # defines __JANUSMASK_PATCHES__ (a literal list)
emitted = ns['__JANUSMASK_PATCHES__']
print(f'emission has {len(emitted)} patch entries; '
      f'names={[e["name"] for e in emitted]}')
entry0 = emitted[0]
print(f'entry[0] name={entry0["name"]!r}')
# show the offending Attribute-target assignment lives in the code block
has_attr_assign = 'pathlib.Path.glob = ' in entry0['code']
print(f'entry[0] code contains "pathlib.Path.glob = " (Attribute target): '
      f'{has_attr_assign}')
err_msg = None
try:
    _apply_symbol_patch(src, entry0['name'], entry0['code'])
    record('proof1_reproduces_apply_failure', False,
           'apply unexpectedly SUCCEEDED -- did not reproduce')
except ValueError as e:
    err_msg = str(e)
    expected = 'unsupported extra assignment target kind: Attribute'
    record('proof1_reproduces_apply_failure', err_msg == expected,
           f'raised ValueError: {err_msg!r} (ledger expected: {expected!r})')
except Exception as e:
    record('proof1_reproduces_apply_failure', False,
           f'unexpected {type(e).__name__}: {e}')

# ---------------------------------------------------------------------------
# PROOF 2 -- the committed oracle has an unconditionally-red regression test
# ---------------------------------------------------------------------------
print()
print('=' * 72)
print('PROOF 2 -- committed oracle is environmentally RED regardless of impl')
print('=' * 72)
offenders = []
for f in REPO.glob('**/*'):
    if f.is_file() and 'manifest' in f.name.lower():
        offenders.append(f.relative_to(REPO).as_posix())
        if len(offenders) >= 6:
            break
print(f'tree files whose NAME contains "manifest" (sample): {offenders}')
# The oracle test walks Path(".") and PROJECT_ROOT for **/* and asserts NO
# file name contains "manifest".  Any offender => that test is red and NO edit
# to orchestrator_worker.py can change it.
record('proof2_oracle_regression_test_unfixable', len(offenders) > 0,
       f'{len(offenders)}+ pre-existing manifest-named files exist; '
       'test_regression_no_unapproved_or_manifest_files_created can NEVER pass '
       'via an orchestrator_worker.py edit')

# ---------------------------------------------------------------------------
# PROOF 3 -- the feasible 2-entry shape applies, imports, and WIRES the gate
# ---------------------------------------------------------------------------
print()
print('=' * 72)
print('PROOF 3 -- feasible patch shape (predicate R-anchor + main gate rewire)')
print('=' * 72)

# Re-emit the small existing helper _emit_lifecycle_safe VERBATIM as the
# primary, with _task_bypasses_fuzz as an EXTRA top-level FunctionDef
# (R-anchor additive).  Extras here are ONLY ImportFrom + FunctionDef -> allowed.
worker_tree = ast.parse(src)
anchor_name = '_emit_lifecycle_safe'
anchor_node = next(n for n in worker_tree.body
                   if isinstance(n, ast.FunctionDef) and n.name == anchor_name)
anchor_src = ''.join(src.splitlines(keepends=True)[anchor_node.lineno - 1:anchor_node.end_lineno])

predicate_block = anchor_src + '''

def _task_bypasses_fuzz(task: Any, mtt: Any) -> bool:
    """True when the differential fuzz gate must be BYPASSED for *task*.

    Honors a planner-set ``smoke_gated`` flag (an unfuzzability signal) in
    addition to the existing meta-task-type bypass set.  Pure: never mutates
    *task* or the bypass set; tolerates a non-dict *task*.
    """
    try:
        from harness.planner.taxonomies import BYPASS_FUZZER_TYPES as _bft
    except Exception:
        _bft = {
            'mcp_server_change', 'config_schema', 'test_unit', 'test_integration',
            'test_e2e', 'test_acceptance', 'docs_writing', 'hooks_integration',
            'mcp_plumbing', 'epic_planning',
        }
    smoke = isinstance(task, dict) and task.get('smoke_gated') is True
    return bool(smoke or mtt in _bft)
'''

# Entry B: rewire the gate inside main.  We do a TARGETED text swap of the one
# gate line on the located main block, then hand the whole rewritten main back
# as the symbol patch code (no extras -> byte-identical replacement path).
main_node = next(n for n in worker_tree.body
                 if isinstance(n, ast.FunctionDef) and n.name == 'main')
main_src = ''.join(src.splitlines(keepends=True)[main_node.lineno - 1:main_node.end_lineno])
OLD_GATE = 'if mtt in BYPASS_FUZZER_TYPES or _skip_ifz:'
NEW_GATE = 'if _task_bypasses_fuzz(task, mtt) or _skip_ifz:'
assert main_src.count(OLD_GATE) == 1, f'expected exactly 1 gate line, got {main_src.count(OLD_GATE)}'
main_block = main_src.replace(OLD_GATE, NEW_GATE)

entries = [
    {'file': 'harness/orchestrator_worker.py', 'kind': 'symbol',
     'name': anchor_name, 'code': predicate_block},
    {'file': 'harness/orchestrator_worker.py', 'kind': 'symbol',
     'name': 'main', 'code': main_block},
]

# Apply both entries in order to a COPY (string), like _apply_patch_entries does.
patched = src
apply_ok = True
try:
    for e in entries:
        patched = _apply_symbol_patch(patched, e['name'], e['code'])
    record('proof3_both_entries_apply', True, 'both symbol patches applied cleanly')
except Exception as e:
    apply_ok = False
    record('proof3_both_entries_apply', False, f'{type(e).__name__}: {e}')

if apply_ok:
    # parse check
    try:
        ast.parse(patched)
        record('proof3_patched_parses', True, 'patched source ast.parse OK')
    except SyntaxError as e:
        record('proof3_patched_parses', False, f'SyntaxError: {e}')

    # write copy, import, and exercise the predicate the way the oracle does
    copy_path = SCRATCH / 'orchestrator_worker_PATCHED_COPY.py'
    copy_path.write_text(patched)
    spec = importlib.util.spec_from_file_location('owk_patched', copy_path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
        from harness.planner.taxonomies import BYPASS_FUZZER_TYPES
        bmtt = next(iter(BYPASS_FUZZER_TYPES))
        cases = [
            (mod._task_bypasses_fuzz({'smoke_gated': True}, 'data_model'), True),
            (mod._task_bypasses_fuzz({}, 'data_model'), False),
            (mod._task_bypasses_fuzz({}, bmtt), True),
            (mod._task_bypasses_fuzz({'smoke_gated': False}, 'data_model'), False),
            (mod._task_bypasses_fuzz(None, 'data_model'), False),
            (mod._task_bypasses_fuzz(123, bmtt), True),
        ]
        all_ok = all(got is exp for got, exp in cases)
        record('proof3_oracle_behaviour_holds', all_ok,
               f'predicate cases {[g for g, _ in cases]} (expected '
               f'{[e for _, e in cases]})')
    except Exception as e:
        record('proof3_oracle_behaviour_holds', False,
               f'{type(e).__name__}: {e}')

    # wiring proof: the patched main MUST call the predicate at the gate
    wired = NEW_GATE in patched and OLD_GATE not in patched
    record('proof3_gate_is_wired', wired,
           f'patched main references _task_bypasses_fuzz at the gate '
           f'(new gate present={NEW_GATE in patched}, '
           f'old gate gone={OLD_GATE not in patched})')

# ---------------------------------------------------------------------------
print()
print('=' * 72)
ok_all = all(ok for _, ok in results)
print(f'OVERALL: {"ALL PASS" if ok_all else "SOME FAIL"} '
      f'({sum(1 for _, o in results if o)}/{len(results)})')
print('=' * 72)
sys.exit(0 if ok_all else 1)
