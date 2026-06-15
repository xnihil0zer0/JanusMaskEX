---
interfaces: "in-place EDIT of harness/planner/plan_validator.py — TWO existing module-level functions only. (A) _is_module_creating gains an OPTIONAL `working_dir=None` param and resolves relative files_touched paths against effective_target_root(working_dir) (imported from harness.paths) instead of the hardcoded JM repo_root; working_dir=None keeps the JM-self behavior byte-identical. (B) inside validate_plan, read `wd = plan.get('working_dir')` once and pass it to the existing _is_module_creating(task) call (-> _is_module_creating(task, working_dir=wd)); and, in the same per-task loop, emit a PlanViolation code 'cd_prefixed_verification_command' when the task's verification_command is a str matching a leading or embedded `cd ` re-root (INLINE — no new top-level helper). NO signature change to validate_plan; NO other symbol touched."
---

# Title

Fix planner validate_plan: external-build module-creating false positive plus cd-prefixed verification_command rejection (harness/planner/plan_validator.py EDIT, harness_self_fix)

# Scope

EDIT `harness/planner/plan_validator.py` (SENSITIVE path under `harness/**` — meta_task_type MUST be `harness_self_fix`; the operator decision file `state/control/decisions/fix-planner-validation-external-and-cd.json` authorizes the commit). This is ONE task editing TWO existing module-level functions in this single file: `_is_module_creating` and `validate_plan`. NO new top-level symbol.

THE TWO BUGS (both verified against current code at HEAD 4a80a0d):

FIX A — external-build false "module-creating". `_is_module_creating(task)` (currently lines ~31-62) resolves every relative `files_touched` path against the JM repo root only:
```python
    repo_root = Path(__file__).resolve().parents[2]
    for path in files_touched:
        ...
        p = Path(path)
        resolved = p if p.is_absolute() else (repo_root / p)
        if not resolved.exists():
            return True
    return False
```
For an EXTERNAL build (the plan has `working_dir` set to another repo, e.g. NobleGreedv2), an edit of an EXISTING external file like `noblegreed/adapter.py` resolves to `<JM root>/noblegreed/adapter.py`, which does not exist, so the function wrongly returns True. `validate_plan` then (line ~213) treats the leaf as module-creating and (line ~233-234) demands a `*_wired` oracle, emitting `missing_wiring_oracle` for a benign external EDIT. The plan-level `working_dir` IS available — `plan['working_dir']` is set in cli.py before validate_plan runs — and `effective_target_root(working_dir)` already exists in `harness/paths.py` (working-dir-aware; fail-safe to PROJECT_ROOT / JM root when `working_dir` is None/self).

FIX C — cd-prefixed verification_command. No plan-time check rejects a `verification_command` that begins with (or embeds via `&&` / `;` / `|`) a `cd ` that re-roots the shell. Such a vcmd overrides the worker's `cwd=staging_worktree` and runs verification against the live pre-merge tree → the merge silently fails (auto_commit_failed) with no diagnostic. This must be caught at plan time.

# Required plan shape

EXACTLY ONE impl task. Use this task_id VERBATIM (the operator decision file is keyed to it): `task_id`: `fix-planner-validation-external-and-cd`. meta_task_type=`harness_self_fix`. priority: high. dependencies: []. SELF task (no `working_dir` — this edits JM itself). files_touched: `["harness/planner/plan_validator.py"]` ONLY. partial_edit semantics: a single `__JANUSMASK_PATCHES__` list with EXACTLY TWO `'symbol'` entries — name `'_is_module_creating'` and name `'validate_plan'` — each reproduced BYTE-FOR-BYTE from the staged read-only target at `{WORK_DIR}/inbox/targets/harness/planner/plan_validator.py`, changing ONLY the lines described below. NO new top-level symbol (do NOT add a helper function). verification_command (CWD-RELATIVE, NO `cd` prefix): `python -m pytest tests/planner/test_module_creating_external_working_dir.py tests/planner/test_cd_prefixed_verification_command.py -q`. The two pre-committed RED oracles are the authoritative contract — make them all green; do NOT author new tests.

REQUIRED: at least TWO `edge_cases` in `test_spec`, mirrored by name into `regression_tests`. Name exactly these:
  1. external existing file with working_dir set -> NOT module-creating, no missing_wiring_oracle.
  2. external ABSENT file with working_dir set -> STILL module-creating, missing_wiring_oracle emitted.
  3. JM-self case (working_dir None) -> _is_module_creating behavior byte-identical (existing module False, absent module True).
  4. leading `cd ` vcmd -> cd_prefixed_verification_command emitted.
  5. embedded `; cd ` re-root vcmd -> cd_prefixed_verification_command emitted.
  6. benign `python -m pytest ... -q` vcmd -> cd_prefixed_verification_command NOT emitted.
`minimum_test_count` must be >= 1.5 x len(functional_requirements).

# Non-Goals

- This is a behavior-only EDIT; integration testing of the end-to-end planner/daemon dispatch flow is OUT OF SCOPE (the integration-test requirement is excused — the two pre-committed oracle files plus the JM-self invariant assertion are the full contract).
- Does NOT change the SIGNATURE of `validate_plan` (it stays `validate_plan(plan)`); only its body reads `plan.get('working_dir')` and adds the cd check inline.
- Does NOT add any new top-level symbol / helper function (a new top-level symbol is fragile for the patch path); the cd check is implemented INLINE inside validate_plan's existing per-task loop.
- Does NOT change `_is_module_creating`'s behavior when `working_dir` is None/absent (JM-self path MUST stay byte-identical).
- Does NOT touch any other symbol in plan_validator.py (_is_wiring_oracle, _valid_mutation_module, check_missing_fields, validate_epic_plan, the cycle DFS, validate_plan_wrapper, etc.) or any other file.

# Inputs

- Authoritative contracts (pre-committed RED oracles, confirmed RED at HEAD 0c79818):
  - `tests/planner/test_module_creating_external_working_dir.py` — RED today: 2 failed (`test_existing_external_file_not_module_creating` — _is_module_creating has no working_dir kwarg; `test_absent_external_file_still_module_creating`) / 1 passed (`test_jm_self_case_unchanged`). After fix: 3/3 green.
  - `tests/planner/test_cd_prefixed_verification_command.py` — RED today: 2 failed (`test_leading_cd_prefix_rejected`, `test_embedded_cd_reroot_rejected`) / 1 passed (`test_normal_vcmd_not_rejected`). After fix: 3/3 green.
- `effective_target_root(working_dir)` is defined in `harness/paths.py` (line ~175): returns `PROJECT_ROOT` when working_dir classifies as self/None, else `Path(working_dir).resolve()`. Import it at the module top of plan_validator.py via `from harness.paths import effective_target_root` IF NOT already imported (check the staged target's import block first — if absent, add this single import line; a module-top import of an existing function is the conventional way to wire a cross-module call and is NOT a new top-level symbol).
- `import re` is ALREADY present at the module top of plan_validator.py (line 3) — reuse it for the cd check; do NOT add a second import.
- The staged read-only target is at `{WORK_DIR}/inbox/targets/harness/planner/plan_validator.py` — reproduce both symbols verbatim from it.

# Deliverables

`harness/planner/plan_validator.py` edited as follows (transcribe; do not invent):

EDIT 1 — `_is_module_creating`: add an optional `working_dir=None` parameter and resolve relative paths against `effective_target_root(working_dir)` instead of the hardcoded JM repo_root. CURRENT (byte-for-byte) signature + resolution:
```python
def _is_module_creating(task: Any) -> bool:
    ...
    repo_root = Path(__file__).resolve().parents[2]
    for path in files_touched:
        if not isinstance(path, str) or not path.endswith('.py'):
            continue
        if 'tests/' in path.replace('\\', '/'):
            continue
        p = Path(path)
        resolved = p if p.is_absolute() else (repo_root / p)
        if not resolved.exists():
            return True
    return False
```
CHANGE TO (only the signature line + the `repo_root =` line change; everything else byte-identical, docstring preserved):
```python
def _is_module_creating(task: Any, working_dir=None) -> bool:
    ...
    repo_root = effective_target_root(working_dir)
    for path in files_touched:
        if not isinstance(path, str) or not path.endswith('.py'):
            continue
        if 'tests/' in path.replace('\\', '/'):
            continue
        p = Path(path)
        resolved = p if p.is_absolute() else (repo_root / p)
        if not resolved.exists():
            return True
    return False
```
(When `working_dir` is None, `effective_target_root(None)` returns PROJECT_ROOT — the JM root — so the JM-self path is byte-equivalent. Keep the full docstring verbatim.)

EDIT 2 — `validate_plan`: (a) read the plan working_dir ONCE near the top of the function body, after `tasks = plan.get('tasks', [])` and before the per-task loop, e.g.:
```python
    wd = plan.get('working_dir')
```
(b) change the existing module-creating check (currently `if _is_module_creating(task) and not _is_wiring_oracle(...)` at line ~213) to pass working_dir:
```python
        if _is_module_creating(task, working_dir=wd) and not _is_wiring_oracle(task.get('verification_command')):
```
(c) INLINE inside the same per-task loop (no new helper), after meta_task_type validation, add the cd-prefixed vcmd check:
```python
        vcmd = task.get('verification_command')
        if isinstance(vcmd, str) and (re.match(r'\s*cd\s', vcmd) or re.search(r'(?:^|&&|;|\|)\s*cd\s', vcmd)):
            violations.append(PlanViolation('cd_prefixed_verification_command', f'{path_prefix}.verification_command', "verification_command must not begin with or embed a 'cd ' that re-roots the shell — it would override the worker's staging-worktree cwd and verify against the live pre-merge tree (silent auto_commit_failed)"))
```
Make `tests/planner/test_module_creating_external_working_dir.py` and `tests/planner/test_cd_prefixed_verification_command.py` all green. Every other line of `_is_module_creating`, `validate_plan`, and `plan_validator.py` is byte-identical; the JM-self / benign-vcmd behavior is unchanged.
