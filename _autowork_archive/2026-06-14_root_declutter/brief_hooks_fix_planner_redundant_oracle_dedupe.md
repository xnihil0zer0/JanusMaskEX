---
interfaces: "in-place EDIT of harness/planner/plan_normalizer.py — add ONE new repo_root-aware pass that drops a SINGLETON test_authoring oracle only when its mutation_target module already EXISTS under repo_root AND a committed oracle file already covers that target (a tests/**/test_*.py importing the module or sharing its leaf stem), rewiring dependents (reusing the drop_map dependency-rewire pattern already in _dedupe_oracles). Conservative: drop only on a confident match; KEEP on any doubt. The new pass is threaded into normalize_plan AFTER _dedupe_oracles; with repo_root=None it is a strict no-op (no filesystem access), matching every other repo_root-aware pass in this module. New top-level helper(s) ride as extra node(s) placed BEFORE the anchor symbol (R-ANCHOR convention)."
---

# Title

Fix planner normalize_plan: drop redundant singleton test_authoring oracle when target module exists and a committed oracle already covers it (harness/planner/plan_normalizer.py EDIT, harness_self_fix)

# Scope

EDIT `harness/planner/plan_normalizer.py` (SENSITIVE path under `harness/**` — meta_task_type MUST be `harness_self_fix`; the operator decision file `state/control/decisions/fix-planner-redundant-oracle-dedupe.json` authorizes the commit).

THE BUG (verified against current code at HEAD 4a80a0d): `_dedupe_oracles` (lines ~86-140) only collapses when MORE THAN ONE `test_authoring` task shares a `mutation_target` (`if len(group) <= 1: continue`, line ~103). A SINGLETON `test_authoring` oracle survives even when (1) its mutation_target module already EXISTS on disk and (2) a non-vacuous committed oracle file already covers that module. That redundant oracle then dispatches, churns ~7 min, hits `retry_exhausted`, and feeds the `runaway_ceiling`. There is no current pass that drops a singleton redundant oracle against on-disk reality, because `_dedupe_oracles` is plan-internal only (no repo_root) and the `len(group) <= 1` guard exempts singletons.

# Required plan shape

EXACTLY ONE impl task. Use this task_id VERBATIM (the operator decision file is keyed to it): `task_id`: `fix-planner-redundant-oracle-dedupe`. meta_task_type=`harness_self_fix`. priority: high. dependencies: []. SELF task (no `working_dir` — this edits JM itself). files_touched: `["harness/planner/plan_normalizer.py"]` ONLY. partial_edit semantics: a single `__JANUSMASK_PATCHES__` list. Because this adds a NEW top-level helper plus edits the existing `normalize_plan`, emit the NEW helper symbol(s) as extra node(s) placed BEFORE their anchor (R-ANCHOR: a new top-level function rides as an extra node placed immediately BEFORE its anchor — anchor it on `normalize_plan`), plus a `'symbol'` entry for `normalize_plan` reproduced BYTE-FOR-BYTE from the staged target with ONLY the one new call line added. Prefer minimal additive logic; if a single new helper is needed, that is the only new top-level symbol. verification_command (CWD-RELATIVE, NO `cd` prefix): `python -m pytest tests/planner/test_dedupe_precommitted_oracle.py -q`. The pre-committed RED oracle is the authoritative contract — make it all green; do NOT author new tests.

REQUIRED: at least TWO `edge_cases` in `test_spec`, mirrored by name into `regression_tests`. Name exactly these:
  1. singleton sibling DROPPED when the target module exists AND a committed oracle file (tests/**/test_<stem>.py importing/sharing-stem) exists under repo_root.
  2. sibling KEPT when no committed oracle exists for the target (conservative keep).
  3. dependents of a dropped oracle are rewired (no dangling dependency references introduced).
  4. conservative keep-on-doubt: repo_root=None, or module absent, or no matching committed oracle -> oracle KEPT, plan otherwise byte-identical.
`minimum_test_count` must be >= 1.5 x len(functional_requirements).

# Non-Goals

- This is a behavior-only EDIT; integration testing of the end-to-end planner/daemon dispatch flow is OUT OF SCOPE (the integration-test requirement is excused — the pre-committed oracle file is the full contract).
- Does NOT change `_dedupe_oracles`'s existing plan-internal dedupe (the `len(group) <= 1` guard stays) — the singleton/on-disk drop is a SEPARATE conservative pass.
- Does NOT change `normalize_plan`'s SIGNATURE (`normalize_plan(plan, repo_root=None)`); only its body gains one new call line threading repo_root into the new pass.
- Does NOT drop anything when `repo_root is None` (strict no-op, no filesystem access — matches every other repo_root-aware pass in this module).
- Must be CONSERVATIVE: drop ONLY on a confident match (module file exists under repo_root AND a committed covering oracle exists); when in doubt, KEEP. No aggressive removal.
- Does NOT touch `_enforce_module_first`, `_strip_unresolvable_dependencies`, `_sanitize_impl_verification_commands`, `_inject_oracle_sources`, `_force_smoke_gated_leaf_impl`, `_canonicalize_oracle_paths`, `_correct_meta_task_type_by_target`, `_inject_credential_naming_constraint`, or any file other than plan_normalizer.py.

# Inputs

- Authoritative contract (pre-committed RED oracle, confirmed RED at HEAD 0c79818): `tests/planner/test_dedupe_precommitted_oracle.py` — RED today: 1 failed (`test_singleton_sibling_dropped_when_committed_oracle_exists` — ORACLE_1 survives) / 1 passed (`test_sibling_kept_when_no_committed_oracle`). After fix: 2/2 green. The test calls `normalize_plan(plan, repo_root=tmp_path)` — the REAL current signature (verified: `def normalize_plan(plan, repo_root=None)` at line 629).
- The oracle's DROP scenario: an impl task `IMPL_1` (files_touched `pkg/mod.py`, vcmd `python -m pytest tests/pkg/test_mod.py -q`), a singleton `test_authoring` `ORACLE_1` (mutation_target `pkg.mod`, files_touched `tests/pkg/test_mod_new.py`). On disk under repo_root: `pkg/mod.py` exists AND `tests/pkg/test_mod.py` exists importing `from pkg.mod import f`. Expected: ORACLE_1 dropped, IMPL_1 kept.
- The oracle's KEEP scenario: same plan but NO committed `tests/pkg/test_mod.py` on disk -> ORACLE_1 kept.
- Existing reusable machinery in this module: `_module_path(mutation_target)` -> `mutation_target.replace('.', '/') + '.py'`; `_mutation_target(task)`; `_is_test_authoring(task)`; the drop_map dependency-rewire loop in `_dedupe_oracles` (lines ~120-139) is the pattern to MIRROR for rewiring dependents of a dropped oracle. The repo_root-aware glob pattern `Path(repo_root).glob('tests/**/test_<leaf>.py')` is used in `_sanitize_impl_verification_commands` (line ~257) — follow the SAME glob + leaf-stem convention for committed-oracle detection.
- The staged read-only target is at `{WORK_DIR}/inbox/targets/harness/planner/plan_normalizer.py`.

# Deliverables

`harness/planner/plan_normalizer.py` with a new conservative pass that drops a redundant singleton test_authoring oracle. Implementation (transcribe the shape; keep it minimal and additive):

1. A NEW top-level helper, e.g. `_drop_redundant_precommitted_oracles(tasks, repo_root)`, placed (R-ANCHOR) immediately BEFORE `normalize_plan`. It MUST:
   - return `tasks` unchanged when `repo_root is None` (strict no-op, no filesystem access).
   - for each SINGLETON `test_authoring` task with a non-empty `mutation_target` (a target that appears on exactly one test_authoring task — do not interfere with multi-oracle groups already handled by `_dedupe_oracles`):
     - compute the module file path via `_module_path(target)` and require `Path(repo_root, module_path).is_file()` (module EXISTS) — else KEEP.
     - require a committed covering oracle: a file matching `Path(repo_root).glob('tests/**/test_' + leaf + '.py')` where `leaf = target.rsplit('.', 1)[-1]`, OR any `tests/**/*.py` under repo_root that imports the dotted module (`from <target> import` / `import <target>`) — and that file is NOT one of this oracle's own `files_touched` (do not count the oracle's own to-be-authored file). Require a non-empty match — else KEEP.
     - only on a CONFIDENT match (module exists AND a committed covering oracle exists), record the oracle for dropping.
   - drop the matched oracle(s) and rewire dependents using the SAME drop_map pattern as `_dedupe_oracles` (lines ~120-139): build `drop_map = {dropped_id: ''}` semantics — since there is no surviving kept sibling, simply REMOVE the dropped id from every other task's `dependencies` (drop the reference, do not point it at a non-existent task), de-duplicated, never introducing a self-edge or a dangling reference.
   - operate conservatively and idempotently; KEEP on any exception (`TypeError`/`ValueError`/`OSError`).
2. Thread the new pass into `normalize_plan` immediately AFTER the `tasks = _dedupe_oracles(tasks)` line (line ~648) and before `_enforce_module_first(tasks)`:
```python
    tasks = _dedupe_oracles(tasks)
    tasks = _drop_redundant_precommitted_oracles(tasks, repo_root)
    normalized['tasks'] = tasks
```
Make `tests/planner/test_dedupe_precommitted_oracle.py` 2/2 green. With `repo_root=None` the output is byte-identical to prior behavior (the new pass is a strict no-op); the KEEP scenario is unchanged; only the confident DROP scenario removes the redundant singleton oracle and rewires dependents. No other symbol in plan_normalizer.py is touched.
