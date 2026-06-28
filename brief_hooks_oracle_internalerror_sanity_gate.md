---
working_dir: "/home/xnihil0zer0/AI-Data/JanusMaskEX"
required_task_ids:
  - oracle-internalerror-sanity-gate-oracle
  - oracle-internalerror-sanity-gate-impl
interfaces: >
  Close a SYSTEMIC HOLE in the test_authoring acceptance path: a fix-forward
  red-pair oracle (a RED `test_authoring` task whose `mutation_target` is an
  ALREADY-EXISTING module) is accepted with ZERO execution-sanity checks on the
  oracle's own captured run. In harness/orchestrator.py, once
  `is_fix_forward_redpair(...)` returns True it sets `_nm_oracle=True`, and
  that flag SKIPS BOTH the verify-exit RED guard (line ~3151:
  `if verify_exit != 0 and not _nm_oracle`) AND the entire mutation/non-vacuity
  gate (line ~3166: `(... or _mtt == 'test_authoring' ...) and not _nm_oracle`).
  So an oracle that does not actually fail RED *for a legitimate reason* lands
  green. In particular a pytest INTERNALERROR — e.g. the 2026-06-25 park oracle
  (`tests/harness/test_park_survives_reauthor.py`, committed 0f7d615) whose
  `def mock_stat(self):` omits the `follow_symlinks` kwarg that Python 3.13's
  `Path.stat(self, *, follow_symlinks=True)` passes, so pytest's OWN
  `p.exists()` raises `TypeError: ... got an unexpected keyword argument
  'follow_symlinks'` during failure reporting — exits non-zero and is accepted
  as a "RED" oracle. The paired `*-impl` task then runs that exact oracle as its
  verification_command, hits the same INTERNALERROR forever, and can NEVER pass
  (observed: park-survives-reauthor-impl stuck in a re-dispatch/`verification_failed`
  loop). An INTERNALERROR is NOT a legitimate RED: it means the oracle is
  un-runnable, not that the impl is absent.

  The fix is a NARROW, fail-closed oracle-sanity gate that, for a
  redpair/`_nm_oracle` oracle against an EXISTING module, inspects the oracle's
  ALREADY-CAPTURED `verify_stdout`/`verify_stderr` (in scope at that point — no
  extra subprocess) and REJECTS the oracle fail-closed if its non-zero exit is a
  pytest INTERNALERROR / collection error / usage error rather than a genuine
  assertion/expected-failure RED. This prevents an un-runnable oracle from
  landing and dooming its paired impl.

  TWO tasks, each editing/creating exactly ONE file:

  (1) oracle-internalerror-sanity-gate-oracle (test_authoring):
      RED behavioral oracle in
      tests/harness/test_oracle_internalerror_sanity_gate.py for a NEW pure
      predicate in harness/redpair_acceptance.py. The predicate
      `oracle_red_is_legitimate(stdout, stderr) -> bool` MUST return False when
      the captured output contains a pytest INTERNALERROR (the literal
      `INTERNALERROR>` marker), a collection error (`errors during collection`,
      `ERROR collecting`), or a usage/argument error
      (`got an unexpected keyword argument`, `INTERNALERROR`), and MUST return
      True for an ordinary assertion failure (`assert`, `AssertionError`,
      `Failed`, `1 failed`). mutation_target is `harness.redpair_acceptance`
      (an EXISTING module) so this is itself a fix-forward red-pair; the
      predicate function is NEW so the oracle is RED-before by absence
      (AttributeError on import of the not-yet-added symbol). NO production
      edit in this task.

  (2) oracle-internalerror-sanity-gate-impl (harness/orchestrator.py +
      harness/redpair_acceptance.py — see SPLIT note below):
      Add the pure predicate to harness/redpair_acceptance.py and wire it into
      harness/orchestrator.py: immediately AFTER `_nm_oracle` is finalized (the
      redpair branch, ~line 3148) and BEFORE the verify-exit skip (~line 3151),
      if `_nm_oracle` is True AND verify_exit not in (None, 0) AND the predicate
      `oracle_red_is_legitimate(verify_stdout, verify_stderr)` is False, then
      ROLL BACK fail-closed exactly like the existing verification_failed path
      (call `_rollback_rejected_commit(...)`, `remove_staging_worktree(...)`,
      write an `impl_progress.jsonl` row with event
      `oracle_red_illegitimate`, and `return False`).
---

# Title
Add a fail-closed oracle-sanity gate so a fix-forward red-pair oracle that
"fails RED" only because of a pytest INTERNALERROR / collection error (an
un-runnable oracle — e.g. a `Path.stat` mock missing `follow_symlinks` under
Python 3.13) is REJECTED at acceptance instead of landing green and dooming its
paired impl to an unpassable verification_command.

# Background / proof of the gap (read before editing)
- Runtime: the factory runs oracles under `sys.executable` (Python 3.13.0;
  harness/sandbox.py and harness/orchestrator.py both use `sys.executable`).
  `inspect.signature(pathlib.Path.stat)` == `(self, *, follow_symlinks=True)`.
- The landed park oracle `tests/harness/test_park_survives_reauthor.py:111-115`
  (committed 0f7d615) monkeypatches `pathlib.Path.stat` with `def mock_stat(self):`
  (no `follow_symlinks`, no `**kwargs`). Running
  `python -m pytest tests/harness/test_park_survives_reauthor.py::test_os_error_resilience`
  yields a pytest `INTERNALERROR> TypeError: mock_stat() got an unexpected
  keyword argument 'follow_symlinks'` — pytest's OWN internal `p.exists()`
  crashes during failure reporting. NO impl can pass this oracle.
- Acceptance path (harness/orchestrator.py): for a `test_authoring` task whose
  `mutation_target='harness.autowork_daemon'` (an EXISTING module),
  `is_fix_forward_redpair(...)` (harness/redpair_acceptance.py:21) returns True
  → `_nm_oracle=True` (orchestrator.py:3148). That flag skips the verify-exit
  guard (3151) AND the mutation gate (3166), so the oracle is accepted WITHOUT
  ever being required to fail-RED for a legitimate reason. `verify_stdout` /
  `verify_stderr` are already captured in scope at that point and already
  contain the `INTERNALERROR>` text — so the gate is a pure string check on
  already-available data, NO new subprocess.
- Provenance: the `_nm_oracle` redpair bypass was wired in commit `0234872`
  ("fix-forward-redpair-orchestrator-wiring", 2026-06-17); the predicate it
  calls lives in `harness/redpair_acceptance.py` (introduced `d0974bd`).
- NOTE (out of scope for this brief, do NOT touch): the SAME park oracle's
  `park-survives-reauthor-impl` is ALSO blocked by a separate
  `auto_commit_patch_failed: disallowed extra top-level` patch-apply problem
  (the WHOLE_FILE_DRIFT / __JANUSMASK_PATCHES__ recipe issue). This brief fixes
  the ROOT acceptance gap (un-runnable oracle lands green); the broken park
  oracle itself should be re-authored/superseded separately.

# Scope
TWO tasks. One `test_authoring` oracle task and one `harness_self_fix` impl
task. READ each file first.

NOTE on the impl task editing TWO files: the impl adds a small pure predicate
to `harness/redpair_acceptance.py` and a ~6-line guard block to
`harness/orchestrator.py`. Per the multi-file rule, if the planner cannot
express a single task touching two files via per-file `__JANUSMASK_PATCHES__`,
SPLIT into:
  - oracle-internalerror-sanity-gate-predicate-impl (harness/redpair_acceptance.py only)
  - oracle-internalerror-sanity-gate-wiring-impl   (harness/orchestrator.py only)
and add both to `required_task_ids`, with the wiring task depending on the
predicate task. Prefer the split — each file then uses a clean per-symbol
`__JANUSMASK_PATCHES__` patch and never a whole-file manifest.

## DECISION FILE REQUIRED
`harness/orchestrator.py` is TRUST-CORE (in `_NEVER_AUTO_APPROVE`). The wiring
task that edits orchestrator.py needs an operator decision file under
`state/control/decisions/<task-id>.json` even with auto_approve. The
`harness/redpair_acceptance.py` predicate task is a normal `harness/**`
`harness_self_fix` (paired test_authoring oracle + decision per the new-module
gates) but is not trust-core.

# Tasks

## 1. oracle-internalerror-sanity-gate-oracle  (meta_task_type: test_authoring)
Author `tests/harness/test_oracle_internalerror_sanity_gate.py`.
- `mutation_target: harness.redpair_acceptance` (existing module; bare dotted).
- Import `harness.redpair_acceptance.oracle_red_is_legitimate` (NEW symbol — the
  import-time AttributeError is the RED-before-absence).
- Assert it returns **False** for outputs containing each of:
  `'INTERNALERROR>'`; `"got an unexpected keyword argument 'follow_symlinks'"`;
  `'errors during collection'`; `'ERROR collecting'`.
- Assert it returns **True** for a genuine assertion-failure tail, e.g.
  `'E       assert 1 == 2\n1 failed, 0 passed'` and for
  `'AssertionError: expected behaviour absent'`.
- Assert it returns True for empty/None-ish inputs treated as no-internalerror
  (decide the safe default: an absence of an internalerror marker = legitimate).
- Name tests `test_<unit>_<behaviour>`; non-vacuous (a stub predicate that
  returns a constant must fail at least one assertion).

## 2. oracle-internalerror-sanity-gate-impl  (split as noted)
### a) harness/redpair_acceptance.py — NEW pure predicate
```
def oracle_red_is_legitimate(stdout, stderr) -> bool:
    """True iff a non-zero oracle run is a GENUINE red (assertion / expected
    failure), False iff it is an un-runnable oracle: pytest INTERNALERROR,
    collection error, or usage/argument error. Pure; never raises."""
```
- Combine `(stdout or '') + '\n' + (stderr or '')`.
- Return False if it contains ANY of (case-sensitive markers pytest emits):
  `'INTERNALERROR>'`, `'errors during collection'`, `'ERROR collecting'`,
  `'got an unexpected keyword argument'`, `'INTERNALERROR'`,
  `'no tests ran'` (a vacuous/empty collection — decide whether to include).
- Else return True. Stdlib only; no spawn/model/network.

### b) harness/orchestrator.py — wire the guard (TRUST-CORE, decision file)
Insert immediately AFTER the redpair branch finalizes `_nm_oracle`
(around line 3148, after the `try/except` that may set `_nm_oracle=True`) and
BEFORE `if verify_exit != 0 and not _nm_oracle:` (line ~3151):
```
            if _nm_oracle and verify_exit not in (None, 0):
                from harness.redpair_acceptance import oracle_red_is_legitimate
                if not oracle_red_is_legitimate(verify_stdout, verify_stderr):
                    logger.warning('oracle_red_illegitimate: task=%s -- oracle '
                                   'failed RED via pytest INTERNALERROR/collection '
                                   'error (un-runnable), not a real assertion; '
                                   'rejected fail-closed', task_id)
                    _rollback_rejected_commit(staging_path, result.get('sha'),
                                              target_rel, task_id,
                                              'oracle_red_illegitimate')
                    git_integration.remove_staging_worktree(str(staging_path),
                                              parent_root=worktree_root)
                    try:
                        write_jsonl_row(state_dir / 'impl_progress.jsonl', {
                            'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                            'phase': 'rejected', 'task_id': task_id,
                            'event': 'oracle_red_illegitimate',
                            'commit_sha': result.get('sha'),
                            'files': [target_rel],
                            'stderr_tail': (verify_stderr or '')[-2000:]})
                    except OSError:
                        pass
                    return False
```
Use a per-symbol `__JANUSMASK_PATCHES__` patch on the enclosing function in
orchestrator.py (do NOT submit a whole-file manifest). READ the function first
to get the exact anchor and the in-scope names (`verify_stdout`,
`verify_stderr`, `result`, `staging_path`, `target_rel`, `worktree_root`,
`state_dir`, `_rollback_rejected_commit`, `git_integration`, `write_jsonl_row`
are all already in scope at that point).

# Non-goals (excuse for the integration/orchestrator wiring)
- This is integration wiring into an existing trust-core acceptance path; the
  orchestrator-wiring task's "test" is the behavioral predicate oracle plus the
  decision file, not a new end-to-end harness run.
- Do NOT re-author or fix the broken park oracle here (separate supersede).
- Do NOT touch the differential fuzzer or the answer-key path (both verified
  healthy 2026-06-25).

# Acceptance
- The predicate oracle is RED-before (AttributeError) and GREEN-after the
  predicate lands; mutation gate passes (a constant-returning stub fails it).
- The orchestrator guard, exercised by re-running an INTERNALERROR oracle
  through acceptance, produces an `oracle_red_illegitimate` rejection instead of
  a green land. (Demonstrate on the park oracle text as the captured output.)
