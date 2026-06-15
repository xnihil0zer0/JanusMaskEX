---
interfaces: "harness/planner/plan_normalizer.py: add a new normalizer pass `_strip_stray_mutation_targets(tasks)` that deletes a stray `mutation_target` key from every task whose FINAL meta_task_type is NOT `test_authoring`, and CALL it as the last pass inside `normalize_plan` (right before `return normalized`). Pure/in-place over the tasks list; preserves `mutation_target` on genuine `test_authoring` oracles."
working_dir: "/home/xnihil0zer0/JanusMaskJR"
meta_task_type: harness_self_fix
---

# Title

Strip stray mutation_target from non-test_authoring tasks in normalize_plan

# Scope

EDIT the EXISTING file `harness/planner/plan_normalizer.py` (READ it first). Add ONE new pure module-level helper `_strip_stray_mutation_targets(tasks)` and wire it in as the FINAL pass of the existing `normalize_plan(plan, repo_root=None)` function. This closes a real defect: the blind planner reflexively attaches `mutation_target = "<module>.<function>"` to NEW-FILE *implementation*/`data_model` tasks (it correctly omits it for edit-tasks). Downstream, the orchestrator non-vacuity mutation gate TRIGGERS on that stray field for a non-test_authoring task, maps the dotted value to a path via `value.replace('.', '/') + '.py'` (e.g. `ngv2/source_localize/localize_source.py` — a path that does NOT exist; the real module is `ngv2/source_localize.py` and `localize_source` is a function inside it), and fail-closes the task with `mutation_gate_error`. The planner schema already mandates "Omit mutation_target for all non-test_authoring tasks"; this pass enforces that invariant deterministically.

# Inputs

The PRE-COMMITTED RED oracle `tests/planner/test_strip_stray_mutation_target.py` (committed on JM master at `db7a9ca`) is the source of truth — READ it and make it GREEN without regressing the existing normalizer suite. It pins:
- `normalize_plan` STRIPS `mutation_target` from an `implementation` task and from a `data_model` task.
- `normalize_plan` PRESERVES `mutation_target` on a `test_authoring` task.
- `normalize_plan` does not mutate its input, and the strip is idempotent (double-apply equal).

# VERIFIED FACTS (do not deviate)

- The file already defines `_is_test_authoring(task) -> bool` (around line 46) and `normalize_plan(plan, repo_root=None)` (around line 994). REUSE `_is_test_authoring`; do NOT reimplement it.
- `normalize_plan` is a pipeline of passes ending with `normalized = _inject_oracle_sources(normalized, repo_root)` then `return normalized`. Insert the new call AFTER `_inject_oracle_sources` and BEFORE `return normalized`, so the strip runs on the FINAL meta_task_type (after `_correct_meta_task_type_by_target` may have changed it).
- `normalize_plan` already deep-copies its input at the top (`normalized = copy.deepcopy(plan)`), so mutating `normalized['tasks']` in place does NOT mutate the caller's input — the idempotency/no-mutation oracle stays green.
- Exact helper to add (top-level, after the other small `_helpers`):
  ```python
  def _strip_stray_mutation_targets(tasks: List[Dict[str, Any]]) -> None:
      """Drop a stray ``mutation_target`` from any non-``test_authoring`` task.

      The planner schema requires omitting ``mutation_target`` for every
      non-test_authoring task, but the blind planner reflexively attaches one to
      NEW-FILE implementation/data_model tasks. A stray ``mutation_target``
      wrongly triggers the orchestrator non-vacuity mutation gate, which maps the
      dotted value to a path (``value.replace('.', '/') + '.py'``) and
      fail-closes when that path does not exist. Mutates ``tasks`` in place;
      genuine ``test_authoring`` oracles keep their ``mutation_target``.
      """
      for t in tasks:
          if isinstance(t, dict) and (not _is_test_authoring(t)) and ('mutation_target' in t):
              del t['mutation_target']
  ```
- Exact wiring inside `normalize_plan`, immediately before `return normalized`:
  ```python
      if isinstance(normalized.get('tasks'), list):
          _strip_stray_mutation_targets(normalized['tasks'])
      return normalized
  ```
- Pure & deterministic: no I/O, network, clock, randomness. `List` and `Dict` and `Any` are already imported at module top (`from typing import ...`) — do NOT add new imports.

# Non-Goals

INTEGRATION is out of scope — do not add wiring beyond the single call inside `normalize_plan`, do not author tests (the oracle is pre-committed), do not change the orchestrator mutation gate, the plan_validator, the blind_draft prompt, or any pass other than adding the one new helper and its single call site. Touch NO file other than `harness/planner/plan_normalizer.py`. Do not touch `mutations[]` handling — only the scalar `mutation_target` key.

# Required plan shape

Emit EXACTLY ONE task (do NOT decompose):
- meta_task_type: harness_self_fix
- files_touched: ["harness/planner/plan_normalizer.py"] (this EXISTING file ONLY)
- This is an EDIT of an existing file: emit a `__JANUSMASK_PATCHES__` symbol patch that MODIFIES `normalize_plan` (adding the single call line before `return normalized`) AND carries the NEW top-level function `_strip_stray_mutation_targets` as an additional (extra-node) symbol in the same patch. Do NOT rewrite unrelated functions.
- verification_command: `python -m pytest tests/planner/ -q`  (the new oracle PLUS the whole planner suite, to prove no regression)
- spec_author: null — the oracle is pre-committed at JM `db7a9ca`; author NO test.
- DO NOT emit a `mutation_target` field (OMIT it — this is a harness_self_fix EDIT task with a pre-committed oracle, not a test_authoring task).
- non_goals MUST contain the literal word `integration`.
- test_spec MUST carry >=2 `regression_tests` that reflect the edge cases (strip from `implementation` task; strip from `data_model` task; PRESERVE on `test_authoring` task; input-not-mutated + idempotent double-apply), and `minimum_test_count` >= 1.5 * len(functional_requirements). Keep `spec.edge_cases` and the regression_tests in sync so the plan_validator's `missing_edge_case_tests` / `insufficient_total_tests` rules pass (the pre-committed oracle already implements these cases — author NO new test).

# Deliverables

`harness/planner/plan_normalizer.py` with the new `_strip_stray_mutation_targets` helper wired as the final pass of `normalize_plan`, GREEN under `python -m pytest tests/planner/ -q` (the pre-committed oracle `tests/planner/test_strip_stray_mutation_target.py` passes and no existing planner test regresses).
