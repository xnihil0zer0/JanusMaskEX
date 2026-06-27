---
working_dir: "/home/xnihil0zer0/JanusMaskJR"
required_task_ids:
  - reduce-bypass-flip-mcp-plumbing-policy
  - reduce-bypass-update-readme-audit-contract
  - reduce-bypass-update-readme-taxonomy-table
  - reduce-bypass-update-architecture-contracts-table
interfaces: >
  Reduce how often bypass_fuzzer fires by flipping the ONE meta_task_type that is
  both unpinned by any regression contract AND retains its inner smoke/embedded/
  narrow gates: mcp_plumbing (bypass_fuzzer True->False). Then keep the THREE
  documentation surfaces that lock the policy in agreement so the doc-vs-code
  audit stays green. FOUR tasks, each editing exactly ONE file via a
  __JANUSMASK_PATCHES__ SYMBOL patch (no whole-file manifest, no multi-file task):

  (1) reduce-bypass-flip-mcp-plumbing-policy -> harness/planner/taxonomies.py:
      flip ONLY mcp_plumbing's bypass_fuzzer flag True->False in the module-global
      META_TASK_POLICY dict. mcp_plumbing keeps skip_structural_decomp:True, so it
      stays in SIDE_EFFECT_META_TYPES; it is NOT in SKIP_SMOKE_GATE_TYPES, so the
      subset invariant SKIP_SMOKE_GATE_TYPES <= BYPASS_FUZZER_TYPES is untouched.
      BYPASS_FUZZER_TYPES (and its alias FUZZ_BYPASS_META_TYPES in diff_fuzzer.py)
      recompute from the dict, so both worker entry points re-arm at once.
      meta_task_type: harness_self_fix (harness/** edit).

  (2) reduce-bypass-update-readme-audit-contract ->
      tests/harness/test_readme_audit_agent_d.py: update the verbatim
      README_BYPASS_FUZZER dict literal so mcp_plumbing maps to False, keeping the
      doc-vs-code lock test test_readme_taxonomy_bypass_fuzzer_matches_policy green.
      This is an EXISTING adversarial contract test that pins the documented table
      against live policy; it MUST be updated in lock-step with the flip.
      meta_task_type: harness_self_fix? NO -- this is a tests/ file, NOT under
      harness/**, so it is meta_task_type: test_unit (see Required plan shape).

  (3) reduce-bypass-update-readme-taxonomy-table -> README.md: change the
      mcp_plumbing row's bypass_fuzzer column from "yes" to "no" in the section-9
      taxonomy table so README.md matches code. meta_task_type: docs_writing.

  (4) reduce-bypass-update-architecture-contracts-table ->
      docs/ARCHITECTURE_CONTRACTS.md: change the mcp_plumbing row's bypass_fuzzer
      cell from a check to blank in the section-2 enumeration table, and amend the
      "never narrow BYPASS_FUZZER_TYPES" invariant prose to record that this flip
      is a SANCTIONED, reviewed narrowing (mcp_plumbing) so the doc no longer reads
      as an absolute prohibition that this very change violates.
      meta_task_type: docs_writing.
---

# Title
Reduce bypass_fuzzer firing: flip the one SAFE-TO-FLIP meta_task_type
(mcp_plumbing) so differential fuzzing re-arms for it, and keep the three
documentation surfaces (README audit contract test, README section 9 table,
ARCHITECTURE_CONTRACTS section 2 table + invariant) in agreement with code.

# Scope
FOUR tasks. Each edits exactly ONE existing file via a `__JANUSMASK_PATCHES__`
SYMBOL patch (READ each file first). The single substantive change is one flag
flip in `META_TASK_POLICY`; the other three tasks are the doc/contract follow
that the doc-vs-code audit REQUIRES so nothing goes RED.

1. `reduce-bypass-flip-mcp-plumbing-policy` edits `harness/planner/taxonomies.py`.
   Flip ONLY the `mcp_plumbing` entry's `bypass_fuzzer` flag from `True` to
   `False` in the module-global `META_TASK_POLICY` dict. Change NOTHING else in
   that dict and no other line in the file. `BYPASS_FUZZER_TYPES`,
   `SIDE_EFFECT_META_TYPES`, `SKIP_SMOKE_GATE_TYPES`, `META_TASK_TYPES`,
   `META_TASK_TAXONOMY_VERSION`, and `is_test_prefixed` are derived/unchanged and
   MUST be left exactly as written (they recompute automatically).

2. `reduce-bypass-update-readme-audit-contract` edits
   `tests/harness/test_readme_audit_agent_d.py`. Update the module-level
   `README_BYPASS_FUZZER` dict literal so the `'mcp_plumbing'` value is `False`.
   Touch no other entry and no other symbol in that test module.

3. `reduce-bypass-update-readme-taxonomy-table` edits `README.md`. In the section-9
   taxonomy table, change the `mcp_plumbing` row's `bypass_fuzzer` column from
   `yes` to `no`. Touch no other row.

4. `reduce-bypass-update-architecture-contracts-table` edits
   `docs/ARCHITECTURE_CONTRACTS.md`. In the section-2 enumeration table, change the
   `mcp_plumbing` row's `bypass_fuzzer` cell from the check mark to blank, AND amend
   the "Invariant: never narrow BYPASS_FUZZER_TYPES" sentence to note that the
   `mcp_plumbing` flip is a sanctioned, reviewed exception so the doc no longer
   self-contradicts.

`harness/planner/taxonomies.py` is under `harness/**`, so TASK 1 is
`harness_self_fix`. It is NOT in the irreducible `_NEVER_AUTO_APPROVE` set
(`taxonomies.py` is not among `orchestrator.py` / `agent_jail.py` / `paths.py` /
`git_integration.py` / `interceptors.py` / `selfheal.py` / `autowork_daemon.py` /
`dbus_proxy.py` / `services/**`), so it is an auto-approve-eligible `harness/**`
edit and needs no operator decision file. TASKS 2-4 edit `tests/**` and docs,
NOT sensitive paths, so they are not `harness_self_fix` and need no decision file.

# Background — why only mcp_plumbing, and why the doc edits are mandatory
The factory verifies generated code two ways: a pre-committed pytest oracle (the
gameable one) and differential fuzzing of two independently-synthesized
candidates. 17 `meta_task_type`s currently `bypass_fuzzer` and so get only the
oracle plus, for the non-`skip_smoke_gates` types, a smoke/embedded/narrow
pre-gate (`harness/orchestrator_worker.py:641-694`). The owner wants to reduce
how often bypass fires.

`META_TASK_POLICY` lives at `harness/planner/taxonomies.py:1`;
`BYPASS_FUZZER_TYPES = frozenset(k for k,v in META_TASK_POLICY.items() if
v['bypass_fuzzer'])` at line 3 RECOMPUTES from it. `harness/diff_fuzzer.py:231`
imports it as the alias `FUZZ_BYPASS_META_TYPES`, and `harness/orchestrator.py:
3801 should_bypass_fuzzer` returns `task.meta_task_type in BYPASS_FUZZER_TYPES`,
so a single flag flip re-arms BOTH worker entry points and the fuzzer's own skip
logic at once.

A 4-vector forensic study (git history + test-pinning + two runtime simulations)
established that of the 16 bypassed types other than `data_model`, exactly ONE is
SAFE-TO-FLIP today: `mcp_plumbing`. The reasoning, with evidence:

NO ORIGINAL RATIONALE EXISTS. `harness/planner/taxonomies.py` was born already
collapsed to one line, fully populated, in a single bulk import commit `d1fcce0`
("Align harness, config, tests, tools, samples, and scripts with parent"); the
17th type `epic_planning` was added by auto-commit `e8e6982`. No commit message,
comment, or docstring states WHY any type bypasses. `docs/ARCHITECTURE_CONTRACTS.md`
section 2 documents the flag SEMANTICS and a "never narrow BYPASS_FUZZER_TYPES"
invariant, but no per-type behavioral justification. So the bypass flags are
status-quo data, not a reasoned design — which is exactly the owner's concern.

THE PINNED SET (9 types CANNOT be flipped without rewriting a load-bearing
behavioral regression contract, not merely a literal): `sandbox_infra`,
`data_model`, `orchestration`, `harness_plumbing`, `planner_tooling`,
`hooks_integration`, `validation`, `harness_self_fix`, `epic_planning`. Evidence:
  - `tests/adversarial/test_taxonomies.py:78-91` parametrizes `planner_tooling,
    orchestration, harness_plumbing, sandbox_infra, hooks_integration, validation,
    harness_self_fix` and asserts each `in BYPASS_FUZZER_TYPES`.
  - `tests/adversarial/test_B3_F2_bypass_adversarial.py:142-152` and `:453-484`
    assert `planner_tooling/orchestration/harness_plumbing/sandbox_infra in
    FUZZ_BYPASS_META_TYPES` AND that a bypass-type task with the target function
    ABSENT from both candidates is a clean SKIP (not an error). This is the
    `stab_005` regression: flipping these makes the SKIP become an ERROR-and-REJECT
    (`fuzz_error_r1`) and BLOCKS legitimate work whose candidate carries no clean
    fuzzable top-level def.
  - `tests/adversarial/test_md_policy.py:34` pins `sandbox_infra` bypass True.
  - `tests/adversarial/test_narrow_fuzz_path1_integration_adversarial.py:57` pins
    `validation in BYPASS_FUZZER_TYPES`, and `test_flag2_embedded_fuzz.py:113` uses
    `validation` as the vehicle to exercise the bypass-branch smoke/embedded/narrow
    gate. `data_model` is pinned by
    `tests/planner/test_correct_meta_task_type_by_target.py:71-74`. `epic_planning`
    by `tests/planner/test_taxonomy_epic_planning.py:28,36`. `harness_self_fix` by
    several (`test_harness_self_fix_smoke_bypass_adversarial.py:38-66`,
    `test_site2_routing_mirror.py:35,47-49`, `test_taxonomy_epic_planning.py:46`).

THE SUBSET-INVARIANT CONSTRAINT. Seven of the eight "not directly pinned as
bypass" types (`config_schema, mcp_server_change, docs_writing,
test_unit/integration/e2e/acceptance`) are in `SKIP_SMOKE_GATE_TYPES`. Two tests
enforce `SKIP_SMOKE_GATE_TYPES <= BYPASS_FUZZER_TYPES`
(`tests/adversarial/test_taxonomies.py:61-62`,
`tests/adversarial/test_harness_self_fix_smoke_bypass_adversarial.py:69-72`), and
`test_harness_self_fix_smoke_bypass_adversarial.py:51-66` pins the EXACT skip-smoke
set. Flipping any of these to `bypass_fuzzer:False` while it stays in skip-smoke
violates the subset invariant; removing its skip-smoke flag breaks the exact-set
test. So they are not freely flippable, AND they are genuinely class-B anyway
(tests are their own oracle; docs are prose; config_schema declares shape not
behavior).

WHY mcp_plumbing IS THE SAFE FLIP. `mcp_plumbing` is the ONLY type of the 17 that
is (a) NOT pinned as bypass by any test -- the sole test naming it
(`test_taxonomies.py:94-109` parametrize, `test_B3_F4_precedence_adversarial.py`)
pins it in `SIDE_EFFECT_META_TYPES` (`skip_structural_decomp`), which is
INDEPENDENT of `bypass_fuzzer`; (b) NOT in `SKIP_SMOKE_GATE_TYPES`, so the subset
invariant is untouched AND its inner smoke/embedded/narrow gates STILL run on the
bypass-removed path (it routes to differential fuzz, and an absent-target case is
handled by the fuzzer's own logic); and (c) a thin-but-real callable surface (MCP
registration/dispatch glue) for which a differential A/B comparison of two
candidates is meaningful when both define the changed callable. A live simulation
confirmed: after the flip, `BYPASS_FUZZER_TYPES` drops `mcp_plumbing`,
`SIDE_EFFECT_META_TYPES` keeps it, the subset invariant holds, and
`tests/adversarial/test_taxonomies.py` stays 26/26 green.

THE DOC-LOCK COUPLING (why TASKS 2-4 are mandatory, not optional). Flipping the
flag alone turns three doc-vs-code locks RED:
  - `tests/harness/test_readme_audit_agent_d.py` carries a VERBATIM
    `README_BYPASS_FUZZER` dict (`mcp_plumbing: True`) and
    `test_readme_taxonomy_bypass_fuzzer_matches_policy` asserts it equals live
    policy. The flip makes live policy `False` -> test RED unless the literal is
    updated (TASK 2).
  - `README.md` section-9 table row `| mcp_plumbing | yes | ...` is the source the
    audit test transcribes; it must read `no` (TASK 3).
  - `docs/ARCHITECTURE_CONTRACTS.md` section-2 table marks `mcp_plumbing` bypass,
    and its "never narrow BYPASS_FUZZER_TYPES" invariant prose would otherwise
    contradict this very (sanctioned) narrowing (TASK 4).

# Inputs
READ these files FIRST in `/home/xnihil0zer0/JanusMaskJR`:

- `harness/planner/taxonomies.py` (TASK 1). VERIFIED current state: line 1 is the
  module-global `META_TASK_POLICY: dict[str, dict[str, bool]] = {...}` literal. The
  `mcp_plumbing` entry is EXACTLY
  `'mcp_plumbing': {'bypass_fuzzer': True, 'skip_structural_decomp': True}`. Line 3
  `BYPASS_FUZZER_TYPES = frozenset((k for k, v in META_TASK_POLICY.items() if
  v['bypass_fuzzer']))` recomputes from the dict; the ONLY edit needed is the one
  flag inside the `mcp_plumbing` entry. Do NOT touch any other entry. Every other
  currently-bypassed type (`sandbox_infra, mcp_server_change, config_schema,
  data_model, test_unit, test_integration, test_e2e, test_acceptance, docs_writing,
  orchestration, harness_plumbing, planner_tooling, hooks_integration, validation,
  harness_self_fix, epic_planning`) MUST keep `bypass_fuzzer:True`; ONLY
  `mcp_plumbing` flips.

- `tests/harness/test_readme_audit_agent_d.py` (TASK 2). VERIFIED current state:
  module-level `README_BYPASS_FUZZER = { ... 'mcp_plumbing': True, ... }`. The
  function `test_readme_taxonomy_bypass_fuzzer_matches_policy` iterates it and
  asserts `META_TASK_POLICY[mtt]['bypass_fuzzer'] == doc`. `test_derived_sets_
  consistent_with_policy` and `test_readme_documents_every_policy_type` also live
  here and MUST stay green (they recompute from policy; flipping the literal keeps
  them green).

- `README.md` (TASK 3). VERIFIED: section-9 table row near line 498 reads
  `| \`mcp_plumbing\` | yes | skip decomp | MCP glue |`. Change `yes` -> `no`.

- `docs/ARCHITECTURE_CONTRACTS.md` (TASK 4). VERIFIED: section-2 table near line 93
  reads `| mcp_plumbing | ✓ | ✓ |   |` (columns bypass_fuzzer / skip_structural_
  decomp / skip_smoke_gates). Change the first `✓` to blank: `| mcp_plumbing |   |
  ✓ |   |`. The invariant sentence near line 105 reads "**Invariant:** never narrow
  `BYPASS_FUZZER_TYPES` ...". Amend it to record the sanctioned `mcp_plumbing`
  exception.

- `harness/diff_fuzzer.py` and `harness/orchestrator_worker.py` and
  `harness/orchestrator.py` — DO NOT EDIT (read for context only). They consume
  `BYPASS_FUZZER_TYPES`; the flip re-arms them with no code edit:
  `diff_fuzzer.py:231` aliases it; `orchestrator_worker.py:641` branches on it;
  `orchestrator.py:3801 should_bypass_fuzzer` returns membership.

# Per-meta_task_type bypass decision table (this brief flips ONLY mcp_plumbing)
Classification of every currently-bypassed type (excluding `data_model`, handled
by the in-flight `restore_differential_fuzzing` brief) into SAFE-TO-FLIP /
NEEDS-FALLBACK / MUST-BYPASS, with evidence.

| meta_task_type | class | this brief | evidence |
|---|---|---|---|
| mcp_plumbing | SAFE-TO-FLIP | FLIP->False | thin callable glue, differential meaningful when both candidates define the symbol; NOT pinned as bypass (only SIDE_EFFECT-pinned, orthogonal); NOT in SKIP_SMOKE so subset invariant untouched + inner gates retained. THE FLIP. |
| orchestration | NEEDS-FALLBACK | keep True | class-A callable, SHOULD fuzz, but pinned SKIP-on-absent-target by test_B3_F2:146/290-304/457 + test_taxonomies:90; flipping turns SKIP into ERROR-and-REJECT (proven by simulation). Fallback brief. |
| planner_tooling | NEEDS-FALLBACK | keep True | same; pinned by the bulk of test_B3_F2 behavioral suite + test_taxonomies:90 + test_P5. |
| harness_plumbing | NEEDS-FALLBACK | keep True | same; pinned by test_B3_F2:148/458, test_rebuild_robustness:67-68, test_prompt_newfile_guard:26, test_taxonomies:90. |
| sandbox_infra | NEEDS-FALLBACK | keep True | same; pinned by test_md_policy:34, test_B3_F2:151/454-459, test_taxonomies:90. |
| validation | NEEDS-FALLBACK | keep True | class-A validator, ALREADY has a single-candidate narrow-fuzz (harness/narrow_fuzz/validation.py); pinned bypass by test_narrow_fuzz_path1:57 + test_flag2_embedded_fuzz:113 + test_taxonomies:90. Fallback brief. |
| config_schema | MUST-BYPASS | keep True | declares schema, not behavior -- no callable interface to fuzz; in SKIP_SMOKE (subset invariant). |
| mcp_server_change | MUST-BYPASS | keep True | server wiring; in SKIP_SMOKE (subset invariant); no reliable in-proc callable. |
| hooks_integration | MUST-BYPASS | keep True | shell/hook glue; pinned by test_taxonomies:90; in SKIP_SMOKE. |
| docs_writing | MUST-BYPASS | keep True | docs/prose, no behavior; in SKIP_SMOKE (subset invariant). |
| test_unit/integration/e2e/acceptance | MUST-BYPASS | keep True | tests are the oracle, not fuzzed against themselves; in SKIP_SMOKE (subset invariant). |
| harness_self_fix | MUST-BYPASS | keep True | meta edits to the harness, gated by the scoped vcmd RED-before/GREEN-after, not interface fuzz; pinned by many tests; in SKIP_SMOKE. |
| epic_planning | MUST-BYPASS | keep True | planning artifact, no callable; pinned by test_taxonomy_epic_planning; in SKIP_SMOKE. |
| data_model | (out of scope) | NOT flipped here | flipped by the in-flight `restore_differential_fuzzing` brief; do NOT touch. |

# Non-Goals
Integration is out of scope (the literal word `integration` MUST appear in this
section and in EACH task's `non_goals` to excuse the integration-test requirement).
Specifically OUT OF SCOPE for this brief:

- Editing `harness/diff_fuzzer.py`, `harness/orchestrator_worker.py`, or
  `harness/orchestrator.py`. The flip re-arms BOTH worker paths and the fuzzer's
  skip logic via the shared `taxonomies.py` policy with no code edit.

- Flipping `data_model`. It is owned by the in-flight
  `brief_hooks_restore_differential_fuzzing.md` (allowlisted slug
  `restore_differential_fuzzing`). Do NOT touch `data_model` -- leave it to that
  brief.

- Flipping the NEEDS-FALLBACK class-A types (`orchestration`, `planner_tooling`,
  `harness_plumbing`, `sandbox_infra`, `validation`). These DO produce callable
  interfaces worth differentially fuzzing, but they are hard-pinned into the bypass
  set by behavioral contracts that assert "target-function-absent-from-candidate ->
  clean SKIP" (`tests/adversarial/test_B3_F2_bypass_adversarial.py`,
  `tests/adversarial/test_narrow_fuzz_path1_integration_adversarial.py`,
  `tests/adversarial/test_flag2_embedded_fuzz.py`,
  `tests/adversarial/test_md_policy.py`). A runtime simulation proved that flipping
  them turns that SKIP into a hard `fuzz_error_r1` REJECT and BLOCKS legitimate work
  whose candidate carries no clean fuzzable top-level def. Re-arming them correctly
  requires FIRST decoupling the "absent-target fail-soft skip" from the bypass
  policy set inside `harness/diff_fuzzer.py::fuzz_from_task`
  (lines ~1164-1176) and a metamorphic/property fallback for the
  candidate-has-no-comparable-callable case -- a separate, larger follow-up brief
  (it overlaps `harness/diff_fuzzer.py`, serialized behind the in-flight
  `restore_differential_fuzzing` edit by the file-overlap dispatch veto). This
  brief deliberately scopes to the single unpinned, gate-retaining flip.

- The MUST-BYPASS / class-B types (`config_schema`, `mcp_server_change`,
  `hooks_integration`, `docs_writing`, the `test_*` family, `harness_self_fix`,
  `epic_planning`). Differential A/B fuzz is not meaningful for these (tests are
  their own oracle, docs are prose, config_schema declares shape not behavior,
  harness_self_fix is gated by the scoped RED/GREEN vcmd, planning emits briefs not
  code) AND seven of them are bound by the `SKIP_SMOKE_GATE_TYPES <=
  BYPASS_FUZZER_TYPES` subset invariant. They stay bypassed.

- Decoupling the absent-target fail-soft skip, adding a metamorphic/property
  fallback, or a held-out SPEC reference oracle. Those are the
  `restore_differential_fuzzing` / `report02_fuzzable_surface` follow-ups.

# Deliverables

## TASK 1 — reduce-bypass-flip-mcp-plumbing-policy (harness/planner/taxonomies.py)

IMPLEMENTATION NOTES (LOAD-BEARING — GENERAL correct behavior, NOT fixture-matching):

1. PATCH SHAPE: emit a `__JANUSMASK_PATCHES__` SYMBOL patch keyed on the
   module-global `META_TASK_POLICY` (a top-level assignment — patchable directly).
   Reproduce the ENTIRE `META_TASK_POLICY` dict literal VERBATIM with the SINGLE
   change being the `mcp_plumbing` entry's `bypass_fuzzer` value `True -> False`:
       'mcp_plumbing': {'bypass_fuzzer': False, 'skip_structural_decomp': True}
   Every other key/value in the dict stays byte-identical. Do NOT emit
   `__JANUSMASK_MANIFEST__` (single existing symbol -> patches, not whole-file).

2. Do NOT edit `BYPASS_FUZZER_TYPES`, `SIDE_EFFECT_META_TYPES`,
   `SKIP_SMOKE_GATE_TYPES`, `META_TASK_TYPES`, `META_TASK_TAXONOMY_VERSION`, or
   `is_test_prefixed`. They are comprehensions over `META_TASK_POLICY` and recompute
   automatically — flipping the dict flag is the GENERAL fix (not a hardcoded set
   membership edit).

3. The change must remain CORRECT for every other type: after the patch,
   `'mcp_plumbing' not in BYPASS_FUZZER_TYPES`, BUT `'mcp_plumbing' in
   SIDE_EFFECT_META_TYPES` STILL holds (skip_structural_decomp stays True), and
   `'mcp_plumbing' not in SKIP_SMOKE_GATE_TYPES` (unchanged). Every currently-
   bypassed type OTHER than mcp_plumbing STILL `in BYPASS_FUZZER_TYPES`, and the
   subset invariant `SKIP_SMOKE_GATE_TYPES <= BYPASS_FUZZER_TYPES` STILL holds.

ANTI-GAMING ORACLE REQUIREMENT (TASK 1) — the test_authoring stage MUST write a RED
oracle that asserts STRUCTURAL/BEHAVIORAL policy properties and is NOT satisfiable
by hardcoding a literal expected value. The oracle MUST:
  - assert `'mcp_plumbing' not in BYPASS_FUZZER_TYPES` (the membership flips), AND
    `META_TASK_POLICY['mcp_plumbing']['bypass_fuzzer'] is False` — i.e. the FLAG,
    not just the frozenset, is correct;
  - assert `'mcp_plumbing' in SIDE_EFFECT_META_TYPES` (skip_structural_decomp
    unchanged) AND `'mcp_plumbing' not in SKIP_SMOKE_GATE_TYPES` (so the flip is
    surgical — only bypass_fuzzer moved);
  - assert the DERIVATION invariant holds GENERICALLY:
    `BYPASS_FUZZER_TYPES == frozenset(k for k, v in META_TASK_POLICY.items() if
    v['bypass_fuzzer'])` (so a worker cannot satisfy the test by hand-editing the
    frozenset literal while leaving the dict flag True — the two must AGREE);
  - assert the DON'T-OVER-FLIP guard: a representative set of types that MUST stay
    bypassed is STILL bypassed, e.g.
    `{'validation','orchestration','harness_self_fix','sandbox_infra',
    'planner_tooling','harness_plumbing','epic_planning'} <= BYPASS_FUZZER_TYPES`,
    and the subset invariant `SKIP_SMOKE_GATE_TYPES <= BYPASS_FUZZER_TYPES` still
    holds, so the flip did not blanket-disable bypass;
  - assert end-to-end via the orchestrator's own decision:
    `should_bypass_fuzzer(Task(task_id='t', meta_task_type='mcp_plumbing'))` (from
    `harness.orchestrator`) returns `False` — the policy change actually changes the
    orchestrator's bypass decision (behavioral), NOT merely a dict literal — AND
    `should_bypass_fuzzer(Task(task_id='t', meta_task_type='orchestration'))`
    returns `True` (a still-bypassed control stays bypassed).
  The oracle MUST derive its expectations from the policy semantics, NOT compare
  against a frozen copy of the whole expected set (that would be gameable by pasting
  the same literal into both the test and the impl). NO answer-key / held-out
  literals.

`non_goals` MUST contain the literal word `integration`. `regression_tests >= 2`.

- `task_id: reduce-bypass-flip-mcp-plumbing-policy`
- `priority: high`
- `meta_task_type: harness_self_fix`
- `files_touched: ["harness/planner/taxonomies.py"]`
- `dependencies: []`
- OMIT `mutation_target`. `spec_author: null` if the oracle is pre-committed, else
  let the test_authoring sibling author it per the anti-gaming notes above.
- Emit a `__JANUSMASK_PATCHES__` SYMBOL patch for `META_TASK_POLICY`.
- `verification_command:` a SCOPED, non-vacuous pytest selecting the new oracle AND
  the existing policy-derivation test that must stay green, e.g.
  `python -m pytest tests/harness/test_reduce_bypass_flip_mcp_plumbing_policy.py tests/adversarial/test_taxonomies.py -q`
  (the SECOND path is the load-bearing derivation-invariant + subset-invariant
  guard; do NOT use a broad `pytest tests/adversarial/ -q` vcmd — it is non-hermetic
  and flaky-blocks). Run the EXACT vcmd yourself before dispatch and confirm
  `N passed` with N>=2.

## TASK 2 — reduce-bypass-update-readme-audit-contract (tests/harness/test_readme_audit_agent_d.py)

IMPLEMENTATION NOTES (LOAD-BEARING):

1. PATCH SHAPE: emit a `__JANUSMASK_PATCHES__` SYMBOL patch keyed on the
   module-global `README_BYPASS_FUZZER` (a top-level assignment — patchable
   directly). Reproduce the ENTIRE `README_BYPASS_FUZZER` dict literal VERBATIM with
   the SINGLE change being `'mcp_plumbing': True -> 'mcp_plumbing': False`. Every
   other key/value stays byte-identical. Do NOT emit `__JANUSMASK_MANIFEST__`.

2. This file IS the documentation-vs-code lock; updating it in lock-step with TASK 1
   is what keeps `test_readme_taxonomy_bypass_fuzzer_matches_policy` green. Do NOT
   edit any other symbol, test function, or import in the module.

3. GENERALITY: change exactly the one dict value; do not special-case, do not add a
   conditional. The literal must agree with the post-flip policy
   (`mcp_plumbing -> False`).

ANTI-GAMING ORACLE REQUIREMENT (TASK 2) — the test_authoring stage MUST write a RED
oracle that asserts the lock is consistent, NOT a frozen literal. The oracle MUST:
  - assert `README_BYPASS_FUZZER['mcp_plumbing'] is False` (the literal flipped);
  - assert the lock CONSISTENCY generically: for every key, `README_BYPASS_FUZZER[k]
    == META_TASK_POLICY[k]['bypass_fuzzer']` (this is the property the existing
    `test_readme_taxonomy_bypass_fuzzer_matches_policy` enforces — re-asserting it
    here proves the audit contract is honored AND it FAILS on today's pre-flip
    literal once policy has flipped);
  - assert `set(README_BYPASS_FUZZER) == set(META_TASK_POLICY)` (no key dropped or
    added — the audit's coverage contract);
  - assert a representative still-bypassed control is STILL `True` in the literal
    (e.g. `README_BYPASS_FUZZER['orchestration'] is True`) so the change is
    surgical, not a blanket edit.
  The oracle MUST import the live `META_TASK_POLICY` and compare against it (so it
  derives expectations from code, not a pasted answer key). NO held-out literals.

`non_goals` MUST contain the literal word `integration`. `regression_tests >= 2`.

- `task_id: reduce-bypass-update-readme-audit-contract`
- `priority: high`
- `meta_task_type: test_unit`  (edits a `tests/**` file; NOT a `harness/**` write,
  so NOT `harness_self_fix`. It is test code; `test_unit` is the canonical type.)
- `files_touched: ["tests/harness/test_readme_audit_agent_d.py"]`
- `dependencies: [reduce-bypass-flip-mcp-plumbing-policy]`  (the consistency oracle
  can only pass once the policy flag has flipped).
- OMIT `mutation_target`. `spec_author: null` if pre-committed.
- Emit a `__JANUSMASK_PATCHES__` SYMBOL patch keyed on `README_BYPASS_FUZZER`.
- `verification_command:` a SCOPED pytest running the updated audit module's
  doc-vs-code locks plus the new oracle, e.g.
  `python -m pytest tests/harness/test_readme_audit_agent_d.py tests/harness/test_reduce_bypass_update_readme_audit_contract.py -q`
  (do NOT use a broad `pytest tests/adversarial/ -q`). Run the EXACT vcmd yourself
  before dispatch and confirm `N passed` with N>=2 and that the existing
  `test_readme_audit_agent_d.py` locks are GREEN against the flipped policy.

## TASK 3 — reduce-bypass-update-readme-taxonomy-table (README.md)

IMPLEMENTATION NOTES (LOAD-BEARING):

1. PATCH SHAPE: `README.md` is a non-`.py` documentation file. Emit a SINGLE-FILE
   WHOLE-FILE submission for `README.md` (literal markdown content), reproducing the
   file byte-for-byte with the ONLY change being the `mcp_plumbing` row's
   `bypass_fuzzer` column in the section-9 taxonomy table:
   `| \`mcp_plumbing\` | yes | skip decomp | MCP glue |` ->
   `| \`mcp_plumbing\` | no | skip decomp | MCP glue |`.
   Do NOT use `__JANUSMASK_PATCHES__` (symbol patches are for `.py` top-level
   symbols; markdown has none). Do NOT change any other line, row, heading, or the
   surrounding prose.

2. The change must be EXACT and minimal: only the single table cell `yes -> no`.
   This keeps `tests/harness/test_readme_audit_agent_d.py` (which transcribes this
   column) in agreement with the flipped policy and TASK 2's updated literal.

ANTI-GAMING ORACLE REQUIREMENT (TASK 3) — the test_authoring stage MUST write a RED
oracle that PARSES the README section-9 table and asserts it agrees with live
policy, NOT a frozen blob. The oracle MUST:
  - read `README.md`, locate the section-9 taxonomy table, parse the `mcp_plumbing`
    row, and assert its `bypass_fuzzer` column is `no` (FAILS on today's `yes`);
  - assert the parsed README bypass column for EVERY documented row agrees with
    `META_TASK_POLICY[type]['bypass_fuzzer']` (yes<->True, no<->False) — the same
    doc-vs-code consistency the audit test enforces, derived from live code;
  - assert a still-bypassed control row (e.g. `orchestration`) is STILL `yes` so the
    edit is surgical.
  The oracle MUST derive expectations from the live `META_TASK_POLICY` import, NOT
  hardcode the whole expected table. NO held-out literals.

`non_goals` MUST contain the literal word `integration`. `regression_tests >= 2`.

- `task_id: reduce-bypass-update-readme-taxonomy-table`
- `priority: medium`
- `meta_task_type: docs_writing`  (a `README.md` documentation edit).
- `files_touched: ["README.md"]`
- `dependencies: [reduce-bypass-flip-mcp-plumbing-policy]`
- OMIT `mutation_target`. `spec_author: null` if pre-committed.
- Emit a SINGLE-FILE whole-file `README.md` submission (literal content), NOT a
  manifest, NOT `__JANUSMASK_PATCHES__`.
- `verification_command:` a SCOPED pytest running the README-parse oracle plus the
  existing audit lock, e.g.
  `python -m pytest tests/harness/test_reduce_bypass_update_readme_taxonomy_table.py tests/harness/test_readme_audit_agent_d.py -q`
  (do NOT use a broad `pytest tests/adversarial/ -q`). Run the EXACT vcmd yourself
  before dispatch and confirm `N passed` with N>=2.

## TASK 4 — reduce-bypass-update-architecture-contracts-table (docs/ARCHITECTURE_CONTRACTS.md)

IMPLEMENTATION NOTES (LOAD-BEARING):

1. PATCH SHAPE: `docs/ARCHITECTURE_CONTRACTS.md` is a non-`.py` documentation file.
   Emit a SINGLE-FILE WHOLE-FILE submission (literal markdown), reproducing the file
   byte-for-byte with TWO minimal changes, both in section 2:
   (a) the `mcp_plumbing` enumeration-table row's `bypass_fuzzer` cell: change the
       leading check mark to blank, i.e. `| mcp_plumbing | ✓ | ✓ |   |` ->
       `| mcp_plumbing |   | ✓ |   |` (keep skip_structural_decomp's ✓);
   (b) the "**Invariant:** never narrow `BYPASS_FUZZER_TYPES` ..." sentence: amend it
       to record that narrowing IS permitted via a reviewed, test-updated brief, and
       that `mcp_plumbing` was so removed — so the doc no longer reads as an absolute
       prohibition that this change violates. Keep the rest of the invariant
       (the post-spawn-audit / do-NOT-by-default posture) intact.
   Do NOT use `__JANUSMASK_PATCHES__`. Do NOT change any other row or section.

2. The change must keep the section-2 table's derived-set summary line internally
   consistent: the prose "`BYPASS_FUZZER_TYPES` = every row with ✓ in column 1 (all
   but `cli_tooling`, `refactor`, `logging_observability`, `io_adapter`)" must be
   updated to ALSO exclude `mcp_plumbing` (add it to that exclusion list), or the
   doc will self-contradict the table. Make that prose edit too.

ANTI-GAMING ORACLE REQUIREMENT (TASK 4) — the test_authoring stage MUST write a RED
oracle that PARSES the section-2 table and asserts agreement with live policy. The
oracle MUST:
  - read `docs/ARCHITECTURE_CONTRACTS.md`, parse the section-2 enumeration table,
    and assert the `mcp_plumbing` row's `bypass_fuzzer` cell is BLANK (FAILS on
    today's ✓);
  - assert the parsed bypass column for EVERY documented row agrees with
    `META_TASK_POLICY[type]['bypass_fuzzer']` (✓<->True, blank<->False) — derived
    from live code;
  - assert a still-bypassed control row (e.g. `orchestration`) STILL carries ✓ so
    the edit is surgical;
  - assert the derived-set summary prose now lists `mcp_plumbing` among the
    non-bypass exclusions (so the prose and table agree).
  The oracle MUST derive expectations from the live `META_TASK_POLICY` import, NOT
  hardcode the whole expected table. NO held-out literals.

`non_goals` MUST contain the literal word `integration`. `regression_tests >= 2`.

- `task_id: reduce-bypass-update-architecture-contracts-table`
- `priority: medium`
- `meta_task_type: docs_writing`
- `files_touched: ["docs/ARCHITECTURE_CONTRACTS.md"]`
- `dependencies: [reduce-bypass-flip-mcp-plumbing-policy]`
- OMIT `mutation_target`. `spec_author: null` if pre-committed.
- Emit a SINGLE-FILE whole-file `docs/ARCHITECTURE_CONTRACTS.md` submission (literal
  content), NOT a manifest, NOT `__JANUSMASK_PATCHES__`.
- `verification_command:` a SCOPED pytest running the section-2 parse oracle, e.g.
  `python -m pytest tests/harness/test_reduce_bypass_update_architecture_contracts_table.py -q`
  (do NOT use a broad `pytest tests/adversarial/ -q`). Run the EXACT vcmd yourself
  before dispatch and confirm `N passed` with N>=2.

# Required plan shape
Emit EXACTLY FOUR tasks (pin via
`required_task_ids: [reduce-bypass-flip-mcp-plumbing-policy,
reduce-bypass-update-readme-audit-contract,
reduce-bypass-update-readme-taxonomy-table,
reduce-bypass-update-architecture-contracts-table]`).
PRIORITY MUST be canonical lowercase (`high`/`medium`, NEVER P0/P1/ints/
Capitalized). TASK 1 is `harness_self_fix` (the one `harness/**` write); TASK 2 is
`test_unit` (a `tests/**` edit); TASKS 3-4 are `docs_writing` (markdown edits).
TASK 1 emits a `__JANUSMASK_PATCHES__` SYMBOL patch; TASK 2 emits a
`__JANUSMASK_PATCHES__` SYMBOL patch; TASKS 3-4 emit single-file whole-file literal
submissions (markdown has no `.py` symbols to patch). Each task's `non_goals` MUST
contain the literal word `integration`; each `regression_tests >= 2`. TASKS 2-4
declare `dependencies: [reduce-bypass-flip-mcp-plumbing-policy]` so their
consistency oracles run against the flipped policy. Do NOT add any task touching a
file other than the one its `files_touched` declares; do NOT add a task editing
`harness/diff_fuzzer.py`, `harness/orchestrator_worker.py`, or
`harness/orchestrator.py`; do NOT flip any policy entry other than `mcp_plumbing`.

`harness/planner/taxonomies.py` is not in the irreducible `_NEVER_AUTO_APPROVE`
set, so no `state/control/decisions/<task_id>.json` file is required for TASK 1; the
auto-approve-sensitive-harness path covers it. TASKS 2-4 are not sensitive-path
edits and need no decision file.
