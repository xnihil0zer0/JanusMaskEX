---
interfaces: "in-place EDIT of harness/orchestrator.py::prepare_task_prompt — resolve files_touched existence against effective_target_root(working_dir) instead of PROJECT_DIR so EXTERNAL EDIT targets get the partial-edit (__JANUSMASK_PATCHES__) prompt; behavior-only, signature unchanged"
---

# Title

Fix prepare_task_prompt partial-edit gate for EXTERNAL targets (harness/orchestrator.py EDIT — harness_self_fix)

# Scope

EDIT `harness/orchestrator.py` (SENSITIVE path — meta_task_type MUST be `harness_self_fix`; an operator decision file authorizes the commit). Inside `prepare_task_prompt(task)` the partial-edit prompt gate computes whether the targets in `files_touched` already exist, but it resolves them against `PROJECT_DIR` (the JanusMask repo root). For an EXTERNAL task (`task['working_dir']` points outside JM, e.g. a NobleGreedv2 checkout) an existing target like `ngv2/debate_router.py` lives under the EXTERNAL root, not under `PROJECT_DIR` — so the existence check is False, the agent receives the WHOLE-FILE prompt instead of the PARTIAL-EDIT (`__JANUSMASK_PATCHES__`) prompt, emits a whole-file rewrite that cosmetically alters existing top-level symbols, and `commit_accepted_output`'s `whole_file_drift` guard (harness/git_integration.py) rejects it with "modified N existing top-level symbols ... use partial-edit". The commit path resolves the target against the external staging worktree, so prompt-path and commit-path disagree on whether the target exists.

THE FIX (additive / in-place, exactly two source lines changed): resolve the existence check against the task's EFFECTIVE target root using the existing helper `harness.paths.effective_target_root(working_dir)` (it returns `PROJECT_ROOT` for self/None tasks and the resolved external path otherwise — verified). Import it LAZILY in the function body (matching the existing in-body import idiom at orchestrator.py:441 `from harness.paths import _target_is_self, effective_target_root`). Do NOT add a new module-level import. Preserve every other byte of `prepare_task_prompt` and of the file.

VERBATIM CURRENT LINES being replaced (orchestrator.py ~1519-1522 — the blind worker must locate exactly this anchor inside `prepare_task_prompt`):

```python
    use_manifest = _requires_verbatim_manifest(files_touched)
    _pe_candidates = files_touched if isinstance(files_touched, list) else [files_touched]
    _targets_exist = bool(_pe_candidates) and all(
        isinstance(p, str) and (Path(PROJECT_DIR) / p).exists() for p in _pe_candidates)
```

REPLACE WITH EXACTLY (keep `use_manifest`/`_pe_candidates` lines byte-identical; only change the existence computation, adding the lazy import + the `_target_root` resolution):

```python
    use_manifest = _requires_verbatim_manifest(files_touched)
    _pe_candidates = files_touched if isinstance(files_touched, list) else [files_touched]
    from harness.paths import effective_target_root
    _target_root = effective_target_root(task.get('working_dir'))
    _targets_exist = bool(_pe_candidates) and all(
        isinstance(p, str) and (_target_root / p).exists() for p in _pe_candidates)
```

The NEW-FILE GUARD is PRESERVED: a target genuinely absent in the external root still yields `_targets_exist=False` and therefore still gets the whole-file prompt (patches cannot create files). The `Path` symbol is still imported at module scope and remains in use elsewhere — do NOT remove it.

meta_task_type=`harness_self_fix`. verification_command: `pytest tests/test_prepare_task_prompt_external_partial_edit_wired.py`.

LOUD DISPATCH DIRECTIVE: `harness/orchestrator.py` is a LARGE file, so this MUST be a partial edit — emit a single top-level `__JANUSMASK_PATCHES__` list with EXACTLY ONE entry of kind `'symbol'`, name `'prepare_task_prompt'`, whose `code` is the FULL corrected `def prepare_task_prompt(...)` (the entire function, with ONLY the four-line existence block changed as above and every other line of the function preserved byte-for-byte, including its long docstring and the `prompt += ...` blocks). Read the function's CURRENT on-disk content from the read-only staged target at `{WORK_DIR}/inbox/targets/harness/orchestrator.py`. Do NOT emit a `__JANUSMASK_MANIFEST__`, do NOT emit a whole-file rewrite, and do NOT touch any other symbol in the file.

# Required plan shape

EXACTLY ONE impl task. Use this task_id VERBATIM (the operator decision file is keyed to it): `task_id`: `fix-external-partial-edit-prompt`. meta_task_type=`harness_self_fix`. priority: high. dependencies: []. files_touched: `["harness/orchestrator.py"]` ONLY (no other file). partial_edit semantics (single `__JANUSMASK_PATCHES__` symbol entry for `prepare_task_prompt`). verification_command: `pytest tests/test_prepare_task_prompt_external_partial_edit_wired.py`. The leaf's `non_goals` MUST carry the literal word `integration` (out of scope is integration testing). The pre-committed RED oracle `tests/test_prepare_task_prompt_external_partial_edit_wired.py` (committed at b833f58 on JM master) is the authoritative contract — make it 3/3 green; do NOT author new tests.

REQUIRED: at least TWO `edge_cases` in `test_spec`, mirrored into `regression_tests` (and/or `property_tests`) — name exactly these two:
  1. external-EDIT-exists → partial-edit-prompt: an EXTERNAL task (`working_dir` outside the repo) whose `files_touched` target EXISTS under that external root yields a prompt CONTAINING `PARTIAL-EDIT DISPATCH` and `__JANUSMASK_PATCHES__`.
  2. external-NEW-absent → whole-file-prompt: an EXTERNAL task whose `files_touched` target is ABSENT under the external root yields a prompt that does NOT contain `PARTIAL-EDIT DISPATCH` (NEW-FILE GUARD preserved).
A third (self-EDIT-exists → partial-edit-prompt) MAY be included to lock the self path. `minimum_test_count` must be >= 1.5 × functional_requirements.

# Non-Goals

- Does NOT change the commit-path `whole_file_drift` guard in `harness/git_integration.py`.
- Does NOT touch any file other than `harness/orchestrator.py`.
- Does NOT alter the NEW-FILE GUARD semantics (absent external targets still get the whole-file prompt).
- Does NOT change the signature of `prepare_task_prompt` or any other symbol in the file.
- Does NOT add a module-level import (the `effective_target_root` import is lazy / in-body).
- Out of scope: integration testing of the end-to-end external commit flow; this leaf is a behavior-only unit fix verified by the pre-committed oracle.

# Inputs

- Authoritative contract: the pre-committed RED oracle `tests/test_prepare_task_prompt_external_partial_edit_wired.py` (JM master commit b833f58). Case (a) external-EDIT-exists is RED today; cases (b)/(c) are green and lock the NEW-FILE GUARD and the self path.
- The helper to use: `harness.paths.effective_target_root(working_dir)` — returns `PROJECT_ROOT` when `working_dir` classifies as self (None/inside-repo), else `Path(working_dir).resolve()`. Verified: an external tmp dir resolves correctly and relative `files_touched` join cleanly under it.
- The existing in-body import idiom precedent: orchestrator.py:441 `from harness.paths import _target_is_self, effective_target_root`.
- The VERBATIM anchor lines and replacement are embedded in `# Scope` above.

# Deliverables

`harness/orchestrator.py` with `prepare_task_prompt` resolving `files_touched` existence against `effective_target_root(task.get('working_dir'))` (lazy in-body import) instead of `PROJECT_DIR`, every other byte of the function and file preserved. Turns `tests/test_prepare_task_prompt_external_partial_edit_wired.py` 3/3 GREEN. EXTERNAL EDIT tasks whose existing targets live under an external root now receive the partial-edit (`__JANUSMASK_PATCHES__`) prompt, so they emit a patch instead of a drift-rejected whole-file rewrite; absent external targets and self targets behave exactly as before.
