---
slug: difffuzz_taxonomy_wave2b
priority: high
working_dir: /home/xnihil0zer0/JanusMaskJR
required_task_ids:
  - difffuzz-w2b-flip-policy
  - difffuzz-w2b-fix-readme-audit
  - difffuzz-w2b-architecture-contracts
---

# Title

difffuzz taxonomy wave 2b — flip harness_self_fix and harness_plumbing out of the fuzzer bypass set, in the correct task order.

# Scope

Continuation of `difffuzz_taxonomy_wave2` (retired for a task-ordering design bug). The RED
routing oracle (`tests/harness/test_difffuzz_w2_routing.py`) and the loosened membership test
(`tests/adversarial/test_taxonomies.py`) ALREADY LANDED on HEAD. This brief does ONLY the
remaining work, in the CORRECT order: the policy flip lands first; the README-audit dict edit
and the docs edit both depend on it. Three single-file tasks. Each task edits exactly ONE file
via a `__JANUSMASK_PATCHES__` SYMBOL patch. Read each target on disk first.

# Non-Goals

- Do NOT touch `skip_structural_decomp`, `skip_smoke_gates`, or any key in `META_TASK_POLICY`
  rows other than the `bypass_fuzzer` boolean for the two named types.
- Do NOT modify the routing oracle or the loosen-membership test (already landed).
- Do NOT change `should_bypass_fuzzer` or any fuzzer-dispatch code.
- Do NOT edit `harness/orchestrator.py` or any `_NEVER_AUTO_APPROVE` file.
- No cross-component integration of new modules; no new entrypoints. These are in-place edits
  to existing, already-wired symbols.

# Inputs

RE-CONFIRM by reading each target before patching:

- `harness/planner/taxonomies.py:1` — `META_TASK_POLICY: dict[str, dict[str, bool]] = {...}`
  (23-key dict literal). `BYPASS_FUZZER_TYPES` and the other derived frozensets recompute from
  it automatically. Today `harness_self_fix` and `harness_plumbing` each carry
  `'bypass_fuzzer': True`. A SYMBOL patch on this AnnAssign is supported.
- `tests/harness/test_readme_audit_agent_d.py` — module-global `README_BYPASS_FUZZER` dict
  (line 23). `test_readme_taxonomy_bypass_fuzzer_matches_policy` cross-checks it against
  `META_TASK_POLICY[...]['bypass_fuzzer']`.
- `tests/harness/test_difffuzz_w2_routing.py` — LANDED routing oracle (12 tests).
- `tests/adversarial/test_taxonomies.py` — LANDED loosened membership (12 tests).
- `docs/ARCHITECTURE_CONTRACTS.md` — §2 taxonomy table + the "never narrow" invariant prose.

# Deliverables

Three tasks. Each TASK block is a single-file `__JANUSMASK_PATCHES__` SYMBOL patch. Every
`non_goals` line below MUST contain the literal word `integration`, and each task MUST declare
at least one edge_case reflected in a regression_test.

## TASK difffuzz-w2b-flip-policy

- meta_task_type: harness_self_fix
- dependencies: []
- file: `harness/planner/taxonomies.py`
- priority: high
- Vehicle: a single `__JANUSMASK_PATCHES__` SYMBOL patch named `META_TASK_POLICY`. Reproduce
  the full 23-key dict EXACTLY as it is at HEAD, changing ONLY `harness_self_fix` and
  `harness_plumbing` `'bypass_fuzzer': True` -> `False`. Leave every other key/flag
  byte-identical; preserve the `META_TASK_POLICY: dict[str, dict[str, bool]]` annotation. Do
  not hand-edit the derived frozensets (they recompute). This task runs while harness_self_fix
  is still bypassed (its own flip not yet committed), and a dict Assign has no FunctionDef, so
  it is NOT differentially fuzzed.
- non_goals: must contain the literal word integration. Flip ONLY the `bypass_fuzzer` boolean
  for `harness_self_fix` and `harness_plumbing`; touch no other value and no derived frozenset.
- verification_command: `python -m pytest tests/harness/test_difffuzz_w2_routing.py -q`
  (expect 12 passed). The committed routing oracle is RED on HEAD and goes GREEN inside this
  task's own staging once the flip applies — a normal fix (no sibling oracle needed). deps are
  `[]` because the oracle and loosen-membership are already on HEAD.

## TASK difffuzz-w2b-fix-readme-audit

- meta_task_type: harness_self_fix
- dependencies: [difffuzz-w2b-flip-policy]
- file: `tests/harness/test_readme_audit_agent_d.py`
- priority: high
- Vehicle: a single `__JANUSMASK_PATCHES__` SYMBOL patch on the module-global
  `README_BYPASS_FUZZER` dict assignment. Reproduce the dict verbatim, changing ONLY
  `'harness_plumbing': True` -> `False` and `'harness_self_fix': True` -> `False`. This dict is
  a module-level assignment (no FunctionDef), so the patched-symbol fuzz selection returns None
  and the task accepts cleanly even running post-flip.
- non_goals: must contain the literal word integration. Edit ONLY the `harness_plumbing` and
  `harness_self_fix` entries (True -> False); touch no other entry, test function, or import.
- verification_command: `python -m pytest tests/harness/test_readme_audit_agent_d.py -q`
  (expect 9 passed). GREEN only POST-flip: the cross-check compares the dict to
  `META_TASK_POLICY[...]['bypass_fuzzer']`, now False for both.

## TASK difffuzz-w2b-architecture-contracts

- meta_task_type: docs_writing
- dependencies: [difffuzz-w2b-flip-policy]
- file: `docs/ARCHITECTURE_CONTRACTS.md`
- priority: high
- Edits: (1) in the §2 taxonomy table, clear the `bypass_fuzzer` ✓ for the `harness_plumbing`
  and `harness_self_fix` rows (leave their `skip_structural_decomp` / `skip_smoke_gates` ✓
  intact); (2) amend the "never narrow `BYPASS_FUZZER_TYPES`" invariant prose to record this
  sanctioned narrowing, adding `harness_self_fix` and `harness_plumbing` to the reviewed
  narrowings under the restore-differential-fuzzing program. Documentation only; no test parses
  this file and docs_writing is never differentially fuzzed.
- non_goals: must contain the literal word integration. Edit ONLY the two §2 rows and the
  invariant prose; do not touch any other table row, section, or code.
- verification_command: `python -m pytest tests/adversarial/test_taxonomies.py -q`
  (expect 12 passed). Stays green (membership was already loosened on HEAD); this gate confirms
  the docs edit broke nothing in the taxonomy contract.

# Test-count gate

- `difffuzz-w2b-flip-policy`: `tests/harness/test_difffuzz_w2_routing.py` -> 12 passed, 0 failed.
- `difffuzz-w2b-fix-readme-audit`: `tests/harness/test_readme_audit_agent_d.py` -> 9 passed, 0 failed.
- `difffuzz-w2b-architecture-contracts`: `tests/adversarial/test_taxonomies.py` -> 12 passed, 0 failed.
