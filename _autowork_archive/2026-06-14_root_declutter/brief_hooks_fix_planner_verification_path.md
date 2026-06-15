---
interfaces: "in-place EDIT of harness/planner/plan_normalizer.py — ADD a NEW pure module-level helper _canonicalize_oracle_paths(plan, repo_root) (plus a one-line R-anchor constant _ORACLE_TESTS_SEGMENT) that repairs a reversed oracle test path in each task's verification_command (<pkg>/tests/... -> tests/<pkg>/... when the swap resolves under repo_root), and thread ONE call to it into the existing normalize_plan() pipeline AFTER _correct_meta_task_type_by_target and BEFORE _sanitize_impl_verification_commands. Deterministic, no LLM call. normalize_plan signature unchanged; behavior-additive; strict no-op for repo_root=None and for any token that resolves neither as-is nor swapped."
---

# Title

Deterministically canonicalize a reversed external oracle verification path in the planner normalizer (harness/planner/plan_normalizer.py EDIT — harness_self_fix)

# Scope

EDIT `harness/planner/plan_normalizer.py` (SENSITIVE path — meta_task_type MUST be `harness_self_fix`; an operator decision file authorizes the commit).

THE BUG (observed repeatedly across NGv2 epics): when the JM planner decomposes an external (NobleGreedv2, working_dir=/home/xnihil0zer0/NobleGreedv2) multi-leaf brief, a blind draft sometimes emits a leaf's `verification_command` with the test path order REVERSED — `pytest ngv2/tests/test_<x>_wired.py` — when the real oracle file lives at `tests/ngv2/test_<x>_wired.py` (repo-root `tests/` package, `ngv2` subdir). The reconciliation/normalization pipeline (`harness/planner/plan_normalizer.py::normalize_plan`) has NO pass that canonicalizes the path order, so the reversed token survives into the staged task. pytest then exits 4 ("file or directory not found" / "no tests ran") → `verification_failed` → `auto_commit_failed`, blocking the leaf. The instability across leaves is which draft token wins reconciliation: Epic A's 5 leaves got the correct `tests/ngv2/...`; Epic B's B2/B4 and Epic C's C1/C2 got the reversed `ngv2/tests/...`; the briefs' plan-shape example is the CORRECT order in every epic, so the planner is inferring/transforming the path unstably with no deterministic backstop. ROOT CAUSE (file:line): `harness/planner/plan_normalizer.py::normalize_plan` (the pass list at lines ~578-586) wires `_dedupe_oracles`, `_enforce_module_first`, `_strip_unresolvable_dependencies`, `_correct_meta_task_type_by_target`, `_sanitize_impl_verification_commands`, `_force_smoke_gated_leaf_impl`, `_inject_credential_naming_constraint`, `_inject_oracle_sources` — NONE of which repairs a reversed `verification_command` path. The downstream oracle-resolving passes (`_sanitize_impl_verification_commands` ~257 `root.glob('tests/**/...')`, `_force_smoke_gated_leaf_impl::_oracle_set` ~395 `(root / tok).is_file()`, `_inject_oracle_sources` ~325 `path.is_file()`) all SKIP a token that does not resolve under repo_root — so a reversed path is silently left wrong AND its oracle source is never injected.

THE FIX (deterministic, no LLM): ADD a new pure pass `_canonicalize_oracle_paths(plan, repo_root)` and thread ONE call to it into `normalize_plan` AFTER `_correct_meta_task_type_by_target` and BEFORE `_sanitize_impl_verification_commands` (so the repaired path feeds every downstream oracle-resolving pass). For each task's `verification_command`, for each whitespace `.py` token that does NOT start with `-`: if it already resolves under `repo_root` (`(root/tok).is_file()`), leave it (idempotent); else compute the `<pkg>/tests/... <-> tests/<pkg>/...` swap and, ONLY if the swapped path resolves to an existing file under `repo_root`, replace the token. A token that resolves neither as-is nor swapped is left unchanged (a genuinely-missing oracle is never silently rewritten). Strict no-op when `repo_root is None` (no filesystem to resolve) or `plan` is not a dict. This is safe for SELF/JM tasks: a `tests/test_bar.py` token that already resolves is left as-is, and the swap of `tests/test_bar.py` (only 2 parts) is not attempted; the swap fires only on a 3+-segment `<pkg>/tests/<rest>` or `tests/<pkg>/<rest>` shape whose swapped form ALSO exists on disk.

# Required plan shape

EXACTLY ONE impl task. Use this task_id VERBATIM (the operator decision file is keyed to it): `task_id`: `fix-planner-verification-path`. meta_task_type=`harness_self_fix`. priority: high. dependencies: []. SELF task (NO `working_dir` — this edits JM itself). files_touched: `["harness/planner/plan_normalizer.py"]` ONLY (no other file). partial_edit semantics (single `__JANUSMASK_PATCHES__` list — see LOUD DISPATCH DIRECTIVE). verification_command: `pytest tests/test_planner_verification_path_normalization_wired.py tests/planner/test_plan_normalizer.py tests/planner/test_plan_normalizer_vcmd_sanitize.py tests/planner/test_force_smoke_gated_leaf_impl.py tests/planner/test_sanitize_vcmd_repo_mapping.py` (the new RED oracle PLUS the existing plan_normalizer test modules, so the symbol-patch reproduction of `normalize_plan` is caught if it drifts). The leaf's `non_goals` MUST carry the literal word `integration`. The pre-committed RED oracle `tests/test_planner_verification_path_normalization_wired.py` (committed at a8c9c705 on JM master) is the authoritative contract — make it 8/8 green; do NOT author new tests.

REQUIRED: at least TWO `edge_cases` in `test_spec`, mirrored into `regression_tests` (and/or `property_tests`) — name exactly these two:
  1. reversed-external-path → repaired: `_canonicalize_oracle_paths({'tasks':[{...,'verification_command':'pytest ngv2/tests/test_foo_wired.py'}]}, repo_root=<root with tests/ngv2/test_foo_wired.py>)` returns a plan whose command is `pytest tests/ngv2/test_foo_wired.py`.
  2. self/correct-path → unchanged (idempotent + fail-safe): an already-correct `tests/ngv2/test_foo_wired.py` command and a SELF `tests/test_bar.py` command are both returned byte-identical, and a token that resolves neither as-is nor swapped is left unchanged.
A third (repo_root=None → strict no-op) MAY be included. `minimum_test_count` must be >= 1.5 × functional_requirements.

# Non-Goals

- Does NOT call any LLM, agent, or network resource — the repair is a pure deterministic filesystem-resolved string swap.
- Does NOT change the signature of `normalize_plan` or any other existing function, and does NOT alter the body of any existing pass (`_sanitize_impl_verification_commands`, `_force_smoke_gated_leaf_impl`, `_inject_oracle_sources`, `_correct_meta_task_type_by_target`, `_dedupe_oracles`, `_enforce_module_first`, `_strip_unresolvable_dependencies`, `_inject_credential_naming_constraint`) beyond inserting the single new call line into `normalize_plan`.
- Does NOT rewrite a token that resolves neither as-is nor swapped (never guesses a missing oracle into existence).
- Does NOT touch any file other than `harness/planner/plan_normalizer.py`.
- Out of scope: integration testing of the end-to-end external epic plan→stage→worker flow; this leaf is a behavior-only unit fix verified by the pre-committed oracle plus the existing normalizer regression modules.

# Inputs

- Authoritative contract: the pre-committed RED oracle `tests/test_planner_verification_path_normalization_wired.py` (JM master commit a8c9c705). All 7 contract cases are RED today because `_canonicalize_oracle_paths` does not exist (ImportError) and `normalize_plan` does not repair the reversed path; the 8th (`repo_root=None` no-op) already holds and must stay green.
- The current `normalize_plan` body to reproduce faithfully (read it byte-for-byte from the read-only staged target at `{WORK_DIR}/inbox/targets/harness/planner/plan_normalizer.py` — it spans roughly lines 559-587). The ONLY change to it is inserting one new line; the current pass list is:

```python
    tasks = _dedupe_oracles(tasks)
    normalized['tasks'] = tasks
    _enforce_module_first(tasks)
    _strip_unresolvable_dependencies(tasks)
    normalized = _correct_meta_task_type_by_target(normalized)
    normalized = _sanitize_impl_verification_commands(normalized, repo_root)
    normalized = _force_smoke_gated_leaf_impl(normalized, repo_root)
    normalized = _inject_credential_naming_constraint(normalized, repo_root)
    normalized = _inject_oracle_sources(normalized, repo_root)
    return normalized
```

REPLACE that pass list WITH EXACTLY (insert the one canonicalize line after `_correct_meta_task_type_by_target`, everything else byte-identical):

```python
    tasks = _dedupe_oracles(tasks)
    normalized['tasks'] = tasks
    _enforce_module_first(tasks)
    _strip_unresolvable_dependencies(tasks)
    normalized = _correct_meta_task_type_by_target(normalized)
    normalized = _canonicalize_oracle_paths(normalized, repo_root)
    normalized = _sanitize_impl_verification_commands(normalized, repo_root)
    normalized = _force_smoke_gated_leaf_impl(normalized, repo_root)
    normalized = _inject_credential_naming_constraint(normalized, repo_root)
    normalized = _inject_oracle_sources(normalized, repo_root)
    return normalized
```

- The NEW helper + R-anchor constant to ADD (verbatim). Add the one-line constant `_ORACLE_TESTS_SEGMENT` FIRST (it is the reliable R-anchor for the new function) immediately before the new function, and place both immediately before the existing `def normalize_plan(...)`:

```python
# Segment that distinguishes the canonical repo-root oracle layout
# (``tests/<pkg>/...``) from the reversed ``<pkg>/tests/...`` form an LLM draft
# sometimes emits; used by _canonicalize_oracle_paths as the R-anchor constant.
_ORACLE_TESTS_SEGMENT = '/tests/'

def _canonicalize_oracle_paths(plan: Dict[str, Any], repo_root: Optional[Any]=None) -> Dict[str, Any]:
    """Repair a reversed oracle test path in each task's verification_command.

    A blind planner draft sometimes emits an external leaf's
    ``verification_command`` with the test path order REVERSED -- e.g.
    ``pytest ngv2/tests/test_x_wired.py`` when the real oracle is at
    ``tests/ngv2/test_x_wired.py`` -- which pytest cannot collect (exit 4),
    blocking the leaf. This deterministic pass rewrites every whitespace
    ``.py`` token in a command that does NOT resolve under ``repo_root`` but
    whose ``<pkg>/tests/...`` <-> ``tests/<pkg>/...`` swap DOES resolve to an
    existing file, so the canonical on-disk path is used regardless of how the
    LLM phrased it.

    Strictly deterministic and pure (deep copy, no mutation of the input).
    Strict no-op when ``repo_root`` is None (no filesystem to resolve against),
    when ``plan`` is not a dict, and for any token that resolves neither as-is
    nor swapped (a genuinely-missing oracle is never silently rewritten).
    Idempotent: an already-correct token resolves as-is and is left unchanged.
    """
    from pathlib import Path
    if repo_root is None or not isinstance(plan, dict):
        return plan
    result = copy.deepcopy(plan)
    tasks = result.get('tasks')
    if not isinstance(tasks, list):
        return result
    try:
        root = Path(repo_root)
    except (TypeError, ValueError):
        return result

    def _swap(rel: str) -> Optional[str]:
        # ``<pkg>/tests/<rest>`` -> ``tests/<pkg>/<rest>`` and the inverse.
        parts = rel.split('/')
        if len(parts) >= 3 and parts[1] == 'tests' and parts[0] != 'tests':
            return '/'.join(['tests', parts[0]] + parts[2:])
        if len(parts) >= 3 and parts[0] == 'tests' and parts[2:]:
            return '/'.join([parts[1], 'tests'] + parts[2:])
        return None

    def _resolves(rel: str) -> bool:
        try:
            return (root / rel).is_file()
        except (TypeError, ValueError, OSError):
            return False

    for t in tasks:
        if not isinstance(t, dict):
            continue
        vcmd = t.get('verification_command')
        if not isinstance(vcmd, str) or not vcmd:
            continue
        tokens = vcmd.split()
        changed = False
        for i, tok in enumerate(tokens):
            if tok.startswith('-') or not tok.endswith('.py'):
                continue
            if _resolves(tok):
                continue  # already correct -> idempotent no-op
            swapped = _swap(tok)
            if swapped is not None and _resolves(swapped):
                tokens[i] = swapped
                changed = True
        if changed:
            t['verification_command'] = ' '.join(tokens)
    return result
```

# Deliverables

`harness/planner/plan_normalizer.py` with: (a) a NEW one-line module-level constant `_ORACLE_TESTS_SEGMENT = '/tests/'` (R-anchor); (b) a NEW pure module-level helper `_canonicalize_oracle_paths(plan, repo_root)` immediately after it; (c) `normalize_plan` calling that helper exactly once, after `_correct_meta_task_type_by_target` and before `_sanitize_impl_verification_commands`, with every other line of `normalize_plan` and every other function in the module preserved byte-for-byte. Turns `tests/test_planner_verification_path_normalization_wired.py` 8/8 GREEN while keeping the existing plan_normalizer test modules green. EXTERNAL multi-leaf plans whose blind draft reversed the oracle path (`ngv2/tests/...`) are now deterministically canonicalized to the on-disk `tests/ngv2/...` form before staging, so the leaf's verification resolves instead of exiting 4; already-correct and SELF/JM commands are untouched.

LOUD DISPATCH DIRECTIVE — PATCH FORMAT (`harness/planner/plan_normalizer.py` is a LARGE ~587-line file; this MUST be a partial edit, NOT a whole-file rewrite): emit a single top-level `__JANUSMASK_PATCHES__` list. The AST-merge applies node-by-node keyed by top-level symbol name (matched names REPLACE, new names APPEND). Emit:
  - ONE entry kind `'symbol'`, name `'normalize_plan'`, whose `code` is the FULL corrected `def normalize_plan(...)` — reproduce the ENTIRE current function byte-for-byte from the read-only staged target, changing ONLY the single inserted `normalized = _canonicalize_oracle_paths(normalized, repo_root)` line in the pass list. Do NOT alter the docstring or any other statement.
  - ONE entry kind `'symbol'`, name `'_ORACLE_TESTS_SEGMENT'`, whose `code` is the constant assignment (with its leading comment). This one-line module-level constant is the reliable R-anchor.
  - ONE entry kind `'symbol'`, name `'_canonicalize_oracle_paths'`, whose `code` is the full new function shown above. (If your patch schema requires a R-ANCHOR for a new symbol, anchor it on the NEW one-line constant `_ORACLE_TESTS_SEGMENT = '/tests/'` — agents reproduce a one-line constant anchor reliably, a function unreliably.)
Read each modified/added symbol's CURRENT on-disk content from the read-only staged target at `{WORK_DIR}/inbox/targets/harness/planner/plan_normalizer.py`. Do NOT emit a `__JANUSMASK_MANIFEST__`, do NOT emit a whole-file rewrite, do NOT touch `_sanitize_impl_verification_commands`, `_force_smoke_gated_leaf_impl`, `_inject_oracle_sources`, `_correct_meta_task_type_by_target`, `_dedupe_oracles`, `_enforce_module_first`, `_strip_unresolvable_dependencies`, `_inject_credential_naming_constraint`, or any other symbol.
