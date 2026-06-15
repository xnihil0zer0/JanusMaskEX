---
working_dir: /home/xnihil0zer0/JanusMaskJR
interfaces: "in-place EDIT of harness/planner/plan_normalizer.py — add ONE new repo_root-aware top-level pass that DROPS an impl task whose module already EXISTS at HEAD in the resolved target root (a re-build clobber of a module a DIFFERENT brief already committed), together with its paired (re-creating) test_authoring oracle, surfacing the telemetry marker `duplicate_module_skipped`. A legitimate same-brief fix-forward EDIT of an existing module (an impl with NO paired re-creating test_authoring oracle in the same plan) is KEPT. HEAD-membership is probed with `git cat-file -e HEAD:<rel>` run in the resolved target root (NOT working-tree presence). Conservative: drop only on a confident match (module at HEAD AND a paired re-creating oracle); KEEP on any doubt. The new pass is threaded into normalize_plan AFTER `_dedupe_oracles`/`_drop_redundant_precommitted_oracles`; with repo_root=None it is a strict no-op (no git/filesystem access), matching every other repo_root-aware pass in this module. New top-level helper(s) ride as extra node(s) placed BEFORE the anchor symbol (R-ANCHOR convention), anchored on `normalize_plan`."
---

# Title

Fix planner normalize_plan: drop impl tasks that clobber an already-committed module (and their paired oracle), keeping same-brief fix-forward edits (harness/planner/plan_normalizer.py EDIT, harness_self_fix)

# Scope

EDIT `harness/planner/plan_normalizer.py` (SENSITIVE path under `harness/**` — meta_task_type MUST be `harness_self_fix`; the operator decision file `state/control/decisions/planner-committed-module-dedup-impl.json` authorizes the commit).

THE BUG (PRIMARY clobber root cause): the planner decomposes each brief in isolation and only dedups `test_authoring` oracles — it NEVER dedups impl `files_touched`. So it emits impl tasks targeting modules ALREADY COMMITTED in the (possibly external) target tree, silently overwriting them with NO oracle to catch the regression. Evidence: `67dc8d0` overwrote `ngv2/workers/report.py` already built by `8c5198c`. `_dedupe_oracles` is plan-internal (no repo_root) and operates only on `test_authoring` tasks; no current pass compares an impl's `files_touched` against on-disk / HEAD reality.

THE PRECISE BEHAVIORAL CONTRACT:

For each impl task (non-`test_authoring`), for each rel path in its `files_touched`, probe HEAD-existence in the resolved target root with `git cat-file -e HEAD:<rel>`:

- If the module does NOT exist at HEAD → it is a genuinely-NEW module → KEEP the impl (and its paired oracle).
- If the module EXISTS at HEAD:
  - AND this plan ALSO contains a paired `test_authoring` oracle that re-creates that same module (an oracle whose `_module_path(mutation_target)` matches one of the impl's HEAD-existing `files_touched`, OR whose `mutation_target` dotted module maps to that path) → this is a RE-BUILD CLOBBER: DROP the impl task AND that paired oracle, and surface the telemetry marker `duplicate_module_skipped`.
  - AND there is NO such paired re-creating oracle in the plan → this is a legitimate SAME-BRIEF FIX-FORWARD edit → KEEP the impl.

THE SAME-BRIEF FIX-FORWARD EXCEPTION (critical): `normalize_plan` only ever sees ONE brief's tasks (the plan wrapper carries a single `source_brief_path`). So the discriminator between a "different-brief clobber" and a "same-brief fix-forward" is the presence of a PAIRED re-creating `test_authoring` oracle for that module in THIS plan. A fix-forward edit arrives as an impl WITHOUT a paired oracle re-creating the module; it MUST be kept. Do NOT gate the drop on every touch of an existing file — only on (module-at-HEAD AND paired re-creating oracle).

TELEMETRY MARKER (exact string): `duplicate_module_skipped`. Surface it on the returned plan so it appears in `repr(plan)` — e.g. append to a plan-level list `plan.setdefault('normalizer_telemetry', []).append('duplicate_module_skipped:<rel>')` (or an equivalent plan-level field). The committed oracle asserts the literal substring `duplicate_module_skipped` is present in `repr(out)` after a drop, and ABSENT otherwise.

# Required plan shape

EXACTLY ONE impl task. Use this task_id VERBATIM (the operator decision file is keyed to it): `task_id`: `planner-committed-module-dedup-impl`. meta_task_type=`harness_self_fix`. priority: high. dependencies: []. SELF task (no per-task `working_dir` — this edits JM itself; `working_dir` for the BRIEF is the JM repo root `/home/xnihil0zer0/JanusMaskJR`). files_touched: `["harness/planner/plan_normalizer.py"]` ONLY. partial_edit semantics: a single `__JANUSMASK_PATCHES__` list. Because this adds a NEW top-level helper plus edits the existing `normalize_plan`, emit the NEW helper symbol(s) as extra node(s) placed BEFORE their anchor (R-ANCHOR: a new top-level function rides as an extra node placed immediately BEFORE its anchor — anchor it on `normalize_plan`), plus a `'symbol'` entry for `normalize_plan` reproduced BYTE-FOR-BYTE from the staged target with ONLY the one new call line added. Prefer minimal additive logic; one new helper is the only new top-level symbol.

verification_command (CWD-RELATIVE, NO `cd` prefix): `python -m pytest tests/planner/test_committed_module_dedup.py -q`.

The pre-committed RED oracle is the authoritative contract — make it all green; do NOT author new tests.

REQUIRED: at least THREE `edge_cases` in `test_spec`, mirrored by name into `regression_tests`:
  1. re-build clobber DROPPED: impl whose module exists at HEAD AND has a paired re-creating test_authoring oracle in the plan -> both dropped, `duplicate_module_skipped` surfaced.
  2. genuinely-NEW module (not at HEAD) -> impl + oracle KEPT.
  3. same-brief fix-forward EDIT (module at HEAD, NO paired re-creating oracle) -> impl KEPT.
  4. conservative no-op: `repo_root=None` -> no git/filesystem access, plan byte-identical (clobber survives because the guard cannot run); idempotent; KEEP on any exception.
  5. dependents of a dropped clobber-impl are rewired (dropped id removed from every other task's `dependencies`; no dangling reference or self-edge).
`minimum_test_count` must be >= 1.5 x len(functional_requirements).

# Non-Goals

- This is a behavior-only EDIT; end-to-end integration testing of the planner/daemon dispatch flow is OUT OF SCOPE (the integration-test requirement is EXCUSED — the pre-committed oracle file is the full contract).
- Does NOT change `_dedupe_oracles`'s existing plan-internal oracle dedupe (the `len(group) <= 1` guard stays) or `_drop_redundant_precommitted_oracles` — the impl-clobber drop is a SEPARATE conservative pass.
- Does NOT block a same-brief fix-forward EDIT of an existing module (impl with no paired re-creating oracle is always KEPT). Do NOT gate the drop on every touch of an existing file.
- Does NOT change `normalize_plan`'s SIGNATURE (`normalize_plan(plan, repo_root=None)`); only its body gains one new call line threading repo_root into the new pass.
- Does NOT drop anything when `repo_root is None` (strict no-op, no git/filesystem access — matches every other repo_root-aware pass in this module).
- Must be CONSERVATIVE: drop ONLY on a confident match (module at HEAD AND a paired re-creating oracle in the plan); when in doubt, KEEP.
- Does NOT touch `_enforce_module_first`, `_strip_unresolvable_dependencies`, `_sanitize_impl_verification_commands`, `_inject_oracle_sources`, `_force_smoke_gated_leaf_impl`, `_canonicalize_oracle_paths`, `_correct_meta_task_type_by_target`, `_inject_credential_naming_constraint`, or any file other than plan_normalizer.py.

# Inputs

- Authoritative contract (pre-committed RED oracle): `tests/planner/test_committed_module_dedup.py`. CONFIRMED RED today: 2 failed (`test_committed_module_rebuild_impl_and_paired_oracle_dropped`, `test_dependents_of_dropped_clobber_rewired`) / 3 passed (the KEEP and no-op invariants already hold because the guard is absent). After fix: 5/5 green. The tests call `normalize_plan(plan, repo_root=tmp_path)` — the REAL current signature (`def normalize_plan(plan, repo_root=None)`).
- HEAD-existence SEAM: the tests build a REAL git repo under `tmp_path` and COMMIT `pkg/mod.py` (a "different brief already built it"). Working-tree-only `pkg/other.py` is present but UNCOMMITTED, so the guard MUST probe HEAD membership (`git cat-file -e HEAD:<rel>` in the resolved target root), NOT mere working-tree `is_file()`. There is precedent for exactly this probe at `harness/orchestrator.py:2071`: `subprocess.run(['git','cat-file','-e', f'HEAD:{rel}'], cwd=str(worktree_root), capture_output=True, text=True, timeout=30)` and the impl SHOULD reuse that idiom (rc==0 means the path exists at HEAD).
- DROP scenario: impl `REBUILD_IMPL` (files_touched `pkg/mod.py`) + paired oracle `REBUILD_ORACLE` (mutation_target `pkg.mod`, files_touched `tests/pkg/test_mod_rebuild.py`). `pkg/mod.py` is committed at HEAD. Expected: BOTH dropped; `duplicate_module_skipped` in `repr(out)`.
- KEEP (new module): impl `NEW_IMPL` (files_touched `pkg/brand_new.py`) + oracle — `pkg/brand_new.py` NOT at HEAD -> both kept; no marker.
- KEEP (fix-forward): impl `FIXFWD_IMPL` (files_touched `pkg/mod.py`) with NO paired oracle in the plan -> kept (module at HEAD but no re-creating oracle); no marker.
- Existing reusable machinery in this module: `_module_path(mutation_target)` -> `mutation_target.replace('.', '/') + '.py'`; `_mutation_target(task)`; `_is_test_authoring(task)`; `_files_touched(task)`; `_task_id(task)`; the drop_map dependency-rewire loop in `_dedupe_oracles` (lines ~120-139) is the EXACT pattern to MIRROR for rewiring dependents of a dropped impl (remove the dropped id from every other task's `dependencies`, de-duplicated, no self-edge, no dangling ref).
- The staged read-only target is at `{WORK_DIR}/inbox/targets/harness/planner/plan_normalizer.py`.

# Deliverables

`harness/planner/plan_normalizer.py` with a new conservative pass that drops a committed-module-clobber impl plus its paired oracle. Implementation (keep it minimal and additive):

1. A NEW top-level helper, e.g. `_drop_committed_module_impls(plan, repo_root)` (operating on the PLAN so it can both edit `tasks` and append the telemetry marker), placed (R-ANCHOR) immediately BEFORE `normalize_plan`. It MUST:
   - return the plan unchanged when `repo_root is None` (strict no-op, no git/filesystem access). Deep-copy before mutating (consistent with sibling repo_root-aware passes that return a copy) OR mutate the already-deep-copied `normalized` in place — pick the convention that keeps the union green; the oracle only inspects the returned object.
   - for each impl (non-`test_authoring`) task, compute the set of its `files_touched` rel paths that EXIST at HEAD via `git cat-file -e HEAD:<rel>` (rc==0) run with `cwd=str(repo_root)`.
   - if any such path exists at HEAD, look for a PAIRED re-creating `test_authoring` oracle in the SAME plan whose `_module_path(_mutation_target(oracle))` equals one of those HEAD-existing paths. If found -> mark BOTH the impl and that oracle for dropping and record marker `duplicate_module_skipped` (e.g. on `plan['normalizer_telemetry']`). If NOT found -> KEEP the impl (same-brief fix-forward).
   - drop the matched ids and rewire dependents using the SAME drop_map pattern as `_dedupe_oracles` (remove the dropped ids from every other task's `dependencies`, de-duplicated, never introducing a self-edge or dangling reference).
   - operate conservatively and idempotently; KEEP on any exception (`TypeError`/`ValueError`/`OSError`/`subprocess.SubprocessError`).
2. Thread the new pass into `normalize_plan` AFTER the existing oracle-dedup lines (after `tasks = _drop_redundant_precommitted_oracles(tasks, repo_root)` and `normalized['tasks'] = tasks`), e.g.:
```python
    tasks = _dedupe_oracles(tasks)
    tasks = _drop_redundant_precommitted_oracles(tasks, repo_root)
    normalized['tasks'] = tasks
    normalized = _drop_committed_module_impls(normalized, repo_root)
```
Make `tests/planner/test_committed_module_dedup.py` 5/5 green. With `repo_root=None` the output is byte-identical to prior behavior; the KEEP scenarios (new module, fix-forward) are unchanged; only the confident DROP scenario removes the clobbering impl + its paired oracle and rewires dependents, surfacing `duplicate_module_skipped`. No other symbol in plan_normalizer.py is touched.

# COMMITTED ORACLE CONTRACT (authoritative; reproduced so the blind worker sees it — your code MUST make it pass)

The full source of `tests/planner/test_committed_module_dedup.py` is the contract; key assertions:
- `test_committed_module_rebuild_impl_and_paired_oracle_dropped`: `REBUILD_IMPL` and `REBUILD_ORACLE` both removed; `'duplicate_module_skipped' in repr(out)`.
- `test_new_module_not_in_head_is_kept`: `NEW_IMPL` and `NEW_ORACLE` kept; no marker.
- `test_fix_forward_edit_of_existing_module_is_kept`: `FIXFWD_IMPL` (no paired oracle) kept; no marker.
- `test_repo_root_none_is_strict_noop`: with `repo_root=None`, clobber impl + oracle survive; no marker.
- `test_dependents_of_dropped_clobber_rewired`: `DOWNSTREAM_IMPL` survives with `REBUILD_IMPL` removed from its `dependencies`.
