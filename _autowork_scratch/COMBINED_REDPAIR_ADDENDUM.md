# Combined existing-module red-pair — ADDENDUM (supersedes the split pattern for B1–B8)

**Why:** the split (separate `*_oracle` + impl briefs) FAILS for an EXISTING-module RED oracle. The
orchestrator accept gate (`orchestrator.py:2978`) rejects a RED `test_authoring` verify unless
`is_fix_forward_redpair` fires, which requires a SIBLING impl task discovered via DEPENDENCY EDGES
(`redpair_acceptance.py::load_sibling_tasks` scans `dependencies`, not plan membership). Two separate
plans have no edge → no sibling → rejection. Fix: ONE brief shaping BOTH tasks in ONE plan.

**Mechanical chain that MUST hold (all verified in code) for the RED oracle to be accepted:**
1. Oracle task: `meta_task_type: test_authoring`, `mutation_target: <bare.dotted.module>` (its file
   EXISTS on disk), non-empty `files_touched: [<test file>]`, `dependencies: []`.
2. Impl task: NON-test_authoring (`harness_self_fix`), `files_touched: [<module file>]` where
   `<module file> == mutation_target.replace('.','/') + '.py'`, `dependencies: [<oracle task_id>]`,
   and its `verification_command` **substring-contains the oracle's own test file path**.
3. Both tasks share the SAME `verification_command` (the pytest over the oracle's test file). The
   impl makes it GREEN-after; the oracle is accepted RED because the impl sibling is found.

## Required combined-brief shape (ONE brief per fix, replaces the 2 split briefs)

Frontmatter:
```yaml
---
title: "<short title>"
working_dir: /home/xnihil0zer0/JanusMaskJR
required_task_ids:
  - <base>-oracle
  - <base>-impl
dependencies: [<cross-fix sibling brief slugs, underscore form>]   # omit if none
---
```
- `required_task_ids` lists BOTH task ids so the plan validator rejects any plan that drops one
  (protects the oracle from being dropped).
- `dependencies` = cross-fix brief-level deps ONLY (held until the sibling COMBINED brief is fully
  accepted). NOT the intra-plan oracle→impl edge (that lives in the impl task's `dependencies`).

Five bare headings (`# Title # Scope # Inputs # Non-Goals # Deliverables`) + `# Required plan shape`.
`non_goals` MUST contain the literal word `integration`. Keep the rich `# Inputs` (verbatim current
source) and the explicit oracle assertions from the two source briefs.

`# Required plan shape` — Emit EXACTLY TWO tasks, in this order:

```
1. task_id: <base>-oracle
   - meta_task_type: test_authoring
   - mutation_target: <bare.dotted.module>     (its .py EXISTS — existing-module red-pair)
   - files_touched: ["<test file>"]
   - dependencies: []
   - spec_author: null
   - verification_command: <pytest over the test file(s)>
   - Authors the RED oracle: RED on HEAD (asserts desired post-fix behavior), GREEN after the impl.

2. task_id: <base>-impl
   - meta_task_type: harness_self_fix
   - files_touched: ["<module file>"]          (== mutation_target as a path + .py)
   - OMIT mutation_target
   - dependencies: ["<base>-oracle"]            (the edge that makes load_sibling_tasks find it)
   - spec_author: null
   - verification_command: <SAME pytest over the oracle's test file(s)>   (MUST name the test file)
   - Emit a `__JANUSMASK_PATCHES__` SYMBOL patch (or R-ANCHOR additive for a brand-new top-level
     symbol). regression_tests >= 2.
```

NOTE for a UNION-vcmd fix (B5, B6): the oracle authors several test files; both tasks' vcmd is the
SAME union pytest invocation, and the impl's vcmd must substring-contain at least one of the oracle's
own test files (it does — they're the same command). Keep all union test files in `files_touched` of
the oracle task and in the shared vcmd.

Read `brief_hooks_multifile_additive_patch_bundle.md` at the repo root as the concrete landed
template for this exact 2-task structure.
