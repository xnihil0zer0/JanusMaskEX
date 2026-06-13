---
complexity_score: 3
interfaces: "in-place EDIT of harness/planner/plan_normalizer.py — inside _sanitize_impl_verification_commands (def at L179, called from normalize_plan L756), relax the unconditional skip guard at L234 so the repo-aware existing-test lookup (L251-269) ALSO runs for an impl whose verification_command is a WEAK import-smoke (python -c \"import ...\") that names no oracle file. NO signature change; NO other line of _sanitize_impl_verification_commands changes; NO other symbol touched; behaviour for oracle-referencing commands, brand-new modules with no paired test, and repo_root=None is byte-identical."
---

# Title

Planner must gate a new-module / harness_self_fix impl on its paired committed pytest oracle, not a vacuous import-smoke (harness/planner/plan_normalizer.py EDIT — harness_self_fix, defect A.2)

# Scope

EDIT `harness/planner/plan_normalizer.py` (SENSITIVE path under `harness/**` — meta_task_type MUST be `harness_self_fix`; the operator decision file `state/control/decisions/planner-honors-verification-command.json` authorizes the commit).

THE BUG (defect A.2, found AND verified 2026-06-13): `_sanitize_impl_verification_commands` (def at `harness/planner/plan_normalizer.py:179`, called from `normalize_plan` at L756) only rewrites a non-`test_authoring` impl's `verification_command` to a real pytest run when that command ALREADY contains the literal path of a sibling oracle's `files_touched`. The guard, byte-for-byte at L231-235, is:

```python
        vcmd = t.get('verification_command')
        if not isinstance(vcmd, str) or not vcmd:
            continue
        if not any((of in vcmd for of in oracle_files)):
            continue
```

For a NEW-module / `harness_self_fix` leaf the blind-drafted impl frequently emits a WEAK `python -c "import <module>"` import-smoke that names NO oracle file, so `any((of in vcmd ...))` is False, the guard `continue`s, and the repo-aware existing-test lookup at L251-269 (which globs `tests/**/test_<leaf>.py`) is NEVER consulted — the weak smoke survives even when a PAIRED COMMITTED test exists on disk under `repo_root`. The buggy-but-importable module then ACCEPTs on a vacuous import. (Refactor/edit tasks were unaffected: their drafted vcmd already named the oracle file, so it DID trip the rewrite — the defect is scoped to the import-smoke case.) An impl not gated on its real oracle is the fuel for the A.1 dep-gate leak. VERIFIED at HEAD: with a fake repo containing `tests/pkg/test_widget.py` and an impl whose vcmd is `python -c "import pkg.widget"`, `normalize_plan(..., repo_root=repo)` leaves the vcmd unchanged.

THE FIX (verified-diff: built in a /tmp clean-worktree 2026-06-13 and proven the RED oracle goes 5/5 GREEN with the 31 existing normalizer/vcmd-sanitize regression tests still green — 36/36 total): replace the unconditional L234 skip so the pass ALSO enters when the command is an import-smoke that should be upgraded. Change the guard block (L231-235) to, byte-for-byte:

```python
        vcmd = t.get('verification_command')
        if not isinstance(vcmd, str) or not vcmd:
            continue
        references_oracle = any((of in vcmd for of in oracle_files))
        # A.2: also handle a WEAK import-smoke (python -c "import ...") that
        # names no oracle file — when a paired committed tests/**/test_<leaf>.py
        # exists on disk we must still upgrade it to a real pytest gate, else a
        # buggy-but-importable new-module / harness_self_fix impl ACCEPTs vacuously.
        is_import_smoke = 'python -c' in vcmd and 'import' in vcmd
        if not references_oracle and not is_import_smoke:
            continue
```

EVERYTHING downstream is unchanged. The existing block computes `modules`/`leaves` from `files_touched` (L236-250); at L251 when `repo_root is not None and leaves` it globs `tests/**/test_<leaf>.py` (excluding oracle files) and, when found, sets `t['verification_command'] = 'python -m pytest ' + ' '.join(existing_tests) + ' -q'` (L267-269). When NO paired test exists it falls to the `if modules:` import-smoke fallback (L270-272) — which for an already-import-smoke command is a byte-identical no-op, preserving the brand-new-module and idempotency contracts. The token-strip tail (L273-277) still only meaningfully runs for oracle-referencing commands with no importable module.

LOUD DISPATCH DIRECTIVE — PATCH FORMAT (`harness/planner/plan_normalizer.py` is a LARGE file; this MUST be a partial edit): emit a single top-level `__JANUSMASK_PATCHES__` list with EXACTLY ONE entry, kind `'symbol'`, name `'_sanitize_impl_verification_commands'`, whose `code` is the FULL `def _sanitize_impl_verification_commands(plan, repo_root=None):` reproduced BYTE-FOR-BYTE from the read-only staged target at `{WORK_DIR}/inbox/targets/harness/planner/plan_normalizer.py`, changing ONLY the guard block shown above (replace the `if not any((of in vcmd for of in oracle_files)): continue` two-line skip with the `references_oracle`/`is_import_smoke` computation + the relaxed combined skip + the explanatory comment). `_sanitize_impl_verification_commands` spans lines 179-278 at HEAD (~100 lines, incl. the long docstring L180-211). KNOWN GOTCHA — SYMBOL TRUNCATION: agents have deterministically truncated symbol reproductions before. POST-EMIT SELF-CHECK (mandatory): your emitted symbol must START with `def _sanitize_impl_verification_commands(plan: Dict[str, Any], repo_root: Optional[Any]=None) -> Dict[str, Any]:`, must still contain the full docstring, the `import os` line, the `oracle_files: Set[str] = set()` build loop, the `boilerplate = {'python', 'python3', 'pytest'}` literal, the `modules`/`leaves` derivation, the `if repo_root is not None and leaves:` glob block setting `'python -m pytest ' + ' '.join(existing_tests) + ' -q'`, the `if modules:` import-smoke fallback, and the `kept`/`meaningful` token-strip tail, and END with `    return result` — all byte-identical except the one changed guard block. If your draft dropped any of those, you truncated — re-read the staged target and re-emit. Do NOT emit a `__JANUSMASK_MANIFEST__`, do NOT emit a whole-file rewrite, do NOT add any new top-level symbol (no R-anchor — the change is wholly inside `_sanitize_impl_verification_commands`), do NOT touch `normalize_plan`, `_force_smoke_gated_leaf_impl`, `_inject_oracle_sources`, `_drop_redundant_precommitted_oracles`, or any other symbol.

INV9 capability gate: the staged symbol `_sanitize_impl_verification_commands` builds/normalizes STRINGS and globs the filesystem; the fix introduces only string membership checks (`'python -c' in vcmd`, `'import' in vcmd`) — it contains NO `eval`/`exec`/`os.system`/`subprocess(..., shell=True)` Call node, so the staged symbol is capability-clean.

# Required plan shape

EXACTLY ONE impl task. Use this task_id VERBATIM (the operator decision file is keyed to it): `task_id`: `planner-honors-verification-command`. `meta_task_type`: `harness_self_fix`. `priority`: high. `dependencies`: `[]`. `spec_author`: `null`. SELF task (no `working_dir` — this edits JM itself). `files_touched`: `["harness/planner/plan_normalizer.py"]` ONLY. partial_edit semantics (single `__JANUSMASK_PATCHES__` list with ONE `'symbol'` entry for `_sanitize_impl_verification_commands`, per the LOUD DISPATCH DIRECTIVE). `verification_command`: `python -m pytest tests/planner/test_impl_vcmd_upgrades_import_smoke_to_paired_test.py tests/planner/test_sanitize_vcmd_repo_mapping.py tests/planner/test_plan_normalizer_vcmd_sanitize.py -q`. The pre-authored RED oracle `tests/planner/test_impl_vcmd_upgrades_import_smoke_to_paired_test.py` is the authoritative contract — make it 5/5 green; do NOT author new tests.

`spec.functional_requirements` (FR): name at least these TWO — (1) an impl whose `verification_command` is a `python -c "import ..."` import-smoke is upgraded to `python -m pytest <paired tests/**/test_<leaf>.py> -q` when that paired committed test exists under `repo_root`; (2) a brand-new module with NO paired committed test still falls back to the import-smoke, and `repo_root=None` stays a pure smoke check (backward compatible). `spec.non_goals` MUST include a line containing the literal word **integration** (e.g. "Integration testing of the end-to-end planner→stage→worker→accept flow is OUT OF SCOPE — this is a behaviour-only unit fix verified by the pre-authored oracle plus the existing vcmd-sanitize regression set.").

TEST-SPEC BALANCE (gates): `test_spec.unit_tests` length MUST be >= len(functional_requirements); `test_spec.minimum_test_count` MUST be >= 1.5 × len(functional_requirements); `token_budget_ratio.test_tokens` MUST be >= 1.5 × `token_budget_ratio.implementation_tokens`. Provide at least TWO `regression_tests` naming EXISTING committed tests: `tests/planner/test_sanitize_vcmd_repo_mapping.py` and `tests/planner/test_plan_normalizer_vcmd_sanitize.py` (both green at HEAD; they pin the oracle-referencing rewrite, the brand-new-module smoke fallback, the `repo_root=None` backward-compat path, and idempotency, and must stay green).

# Non-Goals

- Integration testing of the end-to-end planner→stage→worker→accept flow is OUT OF SCOPE — behaviour-only unit fix verified by the pre-authored oracle plus the existing vcmd-sanitize regression set.
- Does NOT change `_sanitize_impl_verification_commands`'s signature, its docstring, the `oracle_files` build, the `modules`/`leaves` derivation, the `repo_root` glob block, the `if modules:` import-smoke fallback, or the token-strip tail — ONLY the guard block (replace the `if not any(...): continue` skip with the `references_oracle`/`is_import_smoke` relaxed skip + comment).
- Does NOT touch `normalize_plan`, `_force_smoke_gated_leaf_impl`, `_inject_oracle_sources`, `_drop_redundant_precommitted_oracles`, or any other symbol; does NOT add any module-top import (the fix uses only string membership checks; `os` is already imported function-locally).
- Does NOT change behaviour for oracle-referencing commands, for brand-new modules with no paired test, or for `repo_root=None` — all byte-identical.
- Does NOT touch any file other than `harness/planner/plan_normalizer.py`.

# Inputs

- Authoritative contract: the pre-authored RED oracle `tests/planner/test_impl_vcmd_upgrades_import_smoke_to_paired_test.py` (committed `fc7fc54`). Confirmed RED 2026-06-13: 2 failed (`test_import_smoke_impl_upgraded_to_paired_committed_test`, `test_harness_self_fix_import_smoke_upgraded_to_paired_test` — impl keeps `python -c "import ..."`) / 3 passed (brand-new-no-test smoke, repo_root=None smoke, idempotency). After the fix it is 5/5 GREEN.
- Regression / drift guards (pre-existing, all green at HEAD): `tests/planner/test_sanitize_vcmd_repo_mapping.py`, `tests/planner/test_plan_normalizer_vcmd_sanitize.py` (and, if desired, `tests/planner/test_plan_normalizer.py`, `tests/test_planner_verification_path_normalization_wired.py`) — 31/31 at HEAD; must stay green (pin the oracle-referencing rewrite, brand-new-module fallback, repo_root=None backward-compat, idempotency).
- VERIFIED DIFF (2026-06-13, /tmp clean-worktree build): with ONLY the guard block changed as shown in `# Scope`, the RED oracle is 5/5 GREEN and the 31 existing normalizer/vcmd-sanitize regression tests stay green (36/36 total); INV9 capability gate passes (the symbol builds/normalizes strings and globs the filesystem; no `subprocess(..., shell=True)`/eval/exec/os.system Call node).
- The verbatim CURRENT guard block and its exact corrected form are embedded in `# Scope`; the staged read-only target is at `{WORK_DIR}/inbox/targets/harness/planner/plan_normalizer.py` (`_sanitize_impl_verification_commands` spans lines 179-278 at HEAD).

# Deliverables

`harness/planner/plan_normalizer.py` with `_sanitize_impl_verification_commands`'s guard block changed so a non-`test_authoring` impl whose `verification_command` is a `python -c "import ..."` import-smoke ALSO enters the repo-aware existing-test lookup, and is upgraded to `python -m pytest <paired tests/**/test_<leaf>.py> -q` whenever a paired committed test exists under `repo_root` — so a new-module / `harness_self_fix` impl is gated on its real oracle instead of a vacuous import (closing defect A.2, the fuel for the A.1 dep-gate leak). Turns `tests/planner/test_impl_vcmd_upgrades_import_smoke_to_paired_test.py` 5/5 GREEN while the existing vcmd-sanitize regression set stays green. Every other line of `_sanitize_impl_verification_commands` and of `harness/planner/plan_normalizer.py` is byte-identical; behaviour for oracle-referencing commands, brand-new modules with no paired test, and `repo_root=None` is unchanged.
