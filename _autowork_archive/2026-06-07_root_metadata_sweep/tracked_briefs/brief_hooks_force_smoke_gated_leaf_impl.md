---
interfaces: "adds a NEW pure helper `harness.planner.plan_normalizer._force_smoke_gated_leaf_impl(plan, repo_root)` and wires ONE call to it into the existing `normalize_plan` chain (after `_sanitize_impl_verification_commands`, before `_inject_oracle_sources`); no signature change to `normalize_plan`"
---

# Title

gap#2b: force external-build leaf plans to a single smoke-gated (data_model) IMPL task in plan_normalizer

# Scope

The auto-planner stamps EXTERNAL-build leaf tasks (working_dir outside
PROJECT_ROOT, e.g. the NobleGreedv2 `ngv2/*` modules) with fuzz-routed
meta_task_types — `io_adapter`/`refactor`/`algorithm` route through the
diff-fuzzer, `state_machine` routes through stateful-fuzz — and sometimes
over-decomposes one leaf into several tasks (impl + verify-oracle +
conformance-gate). The diff-fuzzer CANNOT resolve external `ngv2.*` imports
(gap#2b) and the stateful-fuzz path DIVERGES, so these correct builds fail their
gate (`fuzz_error_r1` / `stateful_fuzz_divergence`). Empirically: z3_bridge
(io_adapter) built by luck, ast_verifier (refactor) failed fuzz_error, backtrack
(4 tasks; state_machine) failed stateful_fuzz_divergence.

Fix: a NEW pure deterministic helper
`_force_smoke_gated_leaf_impl(plan, repo_root)` that, for EXTERNAL leaf plans,
collapses each leaf to a SINGLE `data_model` IMPL task (`data_model` is
bypass_fuzzer + smoke-gated per `harness/planner/taxonomies.py` META_TASK_POLICY).
It mirrors the existing `_inject_oracle_sources` precedent in the same file
(pure, deep-copy, idempotent, strict no-op when inert). The helper is added as a
NEW top-level def and ANCHORED as a trailing definition rendered with the
single-symbol patch on `normalize_plan` (the same R-anchor technique used to land
`_inject_oracle_sources` on the `normalize_plan` patch), and `normalize_plan`
gains exactly ONE new call to it, placed AFTER
`_sanitize_impl_verification_commands(...)` and BEFORE
`_inject_oracle_sources(...)`.

EXACT helper behaviour (reproduce precisely; the committed oracle
`tests/planner/test_force_smoke_gated_leaf_impl.py` is authoritative):

1. Strict no-op returning the input unchanged when: `repo_root is None`; `plan`
   is not a dict; `plan.get('child_slugs')` is truthy (an epic plan); or
   `Path(repo_root).resolve() == Path(PROJECT_ROOT).resolve()` (a JM-INTERNAL
   self-fix plan — it MUST NEVER be retyped, or every harness self-fix breaks).
   Import `from harness.paths import PROJECT_ROOT`. Guard the `.resolve()` calls
   so a bad `repo_root` (TypeError/ValueError/OSError) returns the input
   unchanged.
2. Otherwise deep-copy the plan. If `tasks` is not a non-empty list, return the
   copy unchanged.
3. For each task, compute its oracle-test set = the set of whitespace tokens in
   its `verification_command` that end in `.py`, do not start with `-`, AND
   resolve to an existing file under `repo_root` (`(Path(repo_root) / tok).is_file()`).
   Tasks whose oracle set is empty are NOT grouped (left untouched). Group the
   remaining tasks by their (frozenset) oracle set.
4. For each group: the impl candidates are the group's tasks whose
   `meta_task_type` is NOT in
   `{'test_authoring','test_acceptance','test_unit','test_integration','test_e2e','validation'}`.
   If there are no impl candidates, leave that group untouched (do NOT retype an
   oracle-authoring group). Otherwise keep the impl candidate with the
   lexicographically-smallest `task_id` (stable), set its
   `meta_task_type = 'data_model'`, and mark every OTHER task in the group for
   removal.
5. Remove all marked tasks from `plan['tasks']`, and from every surviving task's
   `dependencies` list strip any id that was removed (rewire dangling deps).
6. Return the modified copy. The pass is idempotent (a single already-data_model
   task per group is kept and re-set to data_model with nothing to drop).

# Required plan shape

EXACTLY ONE task. `meta_task_type: planner_tooling` (the target
`harness/planner/plan_normalizer.py` is NOT on the `_NEVER_AUTO_APPROVE`
deny-list, so this auto-commits on the worker path with NO operator decision
file). A single-symbol partial edit of `normalize_plan` that inserts the one new
call AND renders the new `_force_smoke_gated_leaf_impl` def as a trailing
definition anchored on that same patch (NEVER whole-file edit the module; do NOT
add `_force_smoke_gated_leaf_impl` as its own separate patch entry). No
test-authoring task (oracle already committed). `verification_command:
python -m pytest tests/planner/test_force_smoke_gated_leaf_impl.py tests/planner/test_inject_oracle_sources.py tests/planner/test_sanitize_vcmd_repo_mapping.py tests/planner/test_plan_normalizer.py -q`
(the new oracle PLUS the three existing plan_normalizer suites, to prove no
regression). Do NOT glob `tests/planner/`.

# Non-Goals

Do NOT change the `normalize_plan` signature or the order of the existing
`_dedupe_oracles` / `_enforce_module_first` / `_sanitize_impl_verification_commands`
/ `_inject_oracle_sources` steps (only INSERT the new call between sanitize and
inject). Do NOT retype JM-internal plans (`repo_root` None or PROJECT_ROOT) —
that is a hard invariant pinned by the oracle. Do NOT touch any other module or
the daemon. Do NOT add a config flag. Do NOT whole-file edit
`plan_normalizer.py`. Keep the helper pure (deep copy, no mutation of the input,
no I/O beyond the `is_file()` existence checks under `repo_root`).

# Inputs

`harness/planner/plan_normalizer.py`: the existing `normalize_plan` (chains
`_dedupe_oracles` -> `_enforce_module_first` -> `_sanitize_impl_verification_commands`
-> `_inject_oracle_sources`; insert the new call between the last two), and the
`_inject_oracle_sources` helper as the structural template (pure, deep-copy,
repo_root guard, idempotent). `harness/planner/taxonomies.py` META_TASK_POLICY
confirms `data_model` is `bypass_fuzzer: True` (and not `stateful_fuzz`), i.e.
smoke-gated. `harness/paths.PROJECT_ROOT` is the JM repo root used to distinguish
internal from external plans. The committed RED oracle
`tests/planner/test_force_smoke_gated_leaf_impl.py` pins the exact contract.

# Deliverables

The new `_force_smoke_gated_leaf_impl` helper + the single inserted call in
`normalize_plan`, landing green against the committed oracle and the three named
regression suites. IMPLEMENTATION CONSTRAINTS to emit as implementation_notes:
meta_task_type planner_tooling (non-deny -> auto-commit, no decision file);
oracle-first (already committed); single-symbol partial edit of `normalize_plan`
with the new def R-anchored as a trailing node on that patch (the
`_inject_oracle_sources` precedent); verification_command names the four test
files explicitly (no glob, no network, no pip).
