# Title

Exempt a module-creating impl leaf from the `missing_wiring_oracle` plan-validation rule
when the SAME plan carries a paired `test_authoring` oracle whose `mutation_target` resolves
to the module the impl creates.

# Scope

A single surgical edit to the existing module `harness/planner/plan_validator.py`. This is a
`harness_self_fix`: route through the pipeline; the committed RED oracle
`tests/planner/test_paired_auto_oracle_wired.py` is authoritative and must go GREEN.

Today `validate_plan` rejects any module-creating leaf whose `verification_command` does not
name a `*_wired` test, with a `missing_wiring_oracle` violation. But the auto-oracle flow is
impl-first: the normalizer's `_enforce_module_first` makes a `test_authoring` oracle depend on
the impl that creates its module, because the oracle's non-vacuity (mutation) gate must mutate
a module that already exists. That makes it structurally impossible for the impl's
`verification_command` to name the not-yet-authored `*_wired` test. When such a paired oracle
exists in the plan, IT is the module's wiring/contract proof, so the impl must be exempt.

# The fix (authoritative implementation)

In `harness/planner/plan_validator.py`, inside `validate_plan`'s per-task loop, the existing
check is:

```python
if _is_module_creating(task) and not _is_wiring_oracle(task.get('verification_command')):
    violations.append(PlanViolation('missing_wiring_oracle', f'{path_prefix}.verification_command', '...'))
```

Add a paired-auto-oracle exemption guard so the violation is suppressed when another task in
the SAME `tasks` list is a `test_authoring` oracle whose `mutation_target`, converted to a
module file path (`dotted.replace('.', '/') + '.py'`), equals one of THIS task's non-test
`files_touched` `.py` paths. Implement the exemption INLINE within the loop (do NOT add a new
top-level function/symbol). Concretely, only append the `missing_wiring_oracle` violation when
the task is module-creating AND lacks a `*_wired` verification AND has NO such paired oracle:

```python
if _is_module_creating(task) and not _is_wiring_oracle(task.get('verification_command')):
    _created = {
        str(p).replace('\\', '/')
        for p in (task.get('files_touched') or [])
        if isinstance(p, str) and p.endswith('.py') and 'tests/' not in str(p).replace('\\', '/')
    }
    _has_paired_oracle = any(
        isinstance(o, dict)
        and o.get('meta_task_type') == 'test_authoring'
        and isinstance(o.get('mutation_target'), str)
        and o.get('mutation_target')
        and (o['mutation_target'].replace('.', '/') + '.py') in _created
        for o in tasks
    )
    if not _has_paired_oracle:
        violations.append(PlanViolation('missing_wiring_oracle', f'{path_prefix}.verification_command', 'a leaf that creates a new module must declare a wiring oracle (a *_wired test named in its verification_command) so the module is proven reachable from a live importer'))
```

Preserve the existing violation message text verbatim. Change ONLY this block; touch nothing
else in the file.

# Required plan shape

EXACTLY ONE task: `meta_task_type: "harness_self_fix"`, `files_touched: ["harness/planner/plan_validator.py"]`,
`verification_command: "python -m pytest tests/planner/test_paired_auto_oracle_wired.py tests/planner/test_missing_wiring_oracle.py -q"`
(the new RED oracle plus the existing wiring-oracle oracle, to prove no regression). Symbol
patch to the existing `validate_plan` function only — no new top-level symbol, no whole-file
rewrite.

# Non-Goals

No change to `_is_module_creating`, `_is_wiring_oracle`, the accept-time `_run_wire_up_gate`,
or `harness/wire_up.py`. No new top-level function/symbol. No change to the violation message
or any other validation rule. No edits outside `harness/planner/plan_validator.py`. This is an
integration-level guard on an existing validation function; broad re-architecture of the
wiring rule is out of scope.

# Inputs

`harness/planner/plan_validator.py` — the existing `validate_plan(plan)` function and its
per-task loop (which already has the `tasks` list and `task`/`path_prefix`/`violations` in
scope), the helpers `_is_module_creating(task)` and `_is_wiring_oracle(verification_command)`,
and the `PlanViolation` dataclass. The committed RED oracle
`tests/planner/test_paired_auto_oracle_wired.py` pins the exact contract (exempt when paired,
still reject when unpaired or when the paired oracle targets a different module, and the
explicit-`*_wired` path is unchanged).

# Deliverables

The edited `harness/planner/plan_validator.py` with the inline paired-auto-oracle exemption in
`validate_plan`, verified GREEN with
`python -m pytest tests/planner/test_paired_auto_oracle_wired.py tests/planner/test_missing_wiring_oracle.py -q`.
