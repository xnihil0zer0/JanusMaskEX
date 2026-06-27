---
working_dir: "/home/xnihil0zer0/JanusMaskJR"
priority: high
required_task_ids:
  - difffuzz-w2-routing-oracle
  - difffuzz-w2-loosen-membership
  - difffuzz-w2-fix-readme-audit
  - difffuzz-w2-flip-policy
  - difffuzz-w2-architecture-contracts
interfaces: >
  Phase 4 wave 2 of restore-differential-fuzzing. Re-arm differential fuzzing for the TWO
  highest-volume meta_task_types (~88% of factory accepts) by flipping bypass_fuzzer
  True->False in harness/planner/taxonomies.py::META_TASK_POLICY: harness_self_fix and
  harness_plumbing. BYPASS_FUZZER_TYPES recomputes from the dict, so should_bypass_fuzzer
  (orchestrator.py:3795), the worker routing branch, and diff_fuzzer's FUZZ_BYPASS_META_TYPES
  re-arm with NO edit to the irreducible orchestrator.py. Each task edits exactly ONE file
  via a single-file __JANUSMASK_PATCHES__ SYMBOL patch (multi-file is FORCED onto the brittle
  verbatim whole-file manifest by _requires_verbatim_manifest, so one-file-per-task is
  mandatory). Ordering keeps every committed state's SCOPED gate green AND never bets wave
  completion on a fuzz outcome: every code/test edit runs while harness_self_fix is still
  bypassed (so none is fuzzed), and the only post-flip task is docs_writing (never fuzzed).
---

# Title
Phase 4 wave 2 — flip harness_self_fix and harness_plumbing out of BYPASS_FUZZER_TYPES so
the differential fuzzer re-routes the factory's highest-volume accepts, keeping every
committed doc-vs-code lock green and never gating wave completion on a fuzz verdict.

# Scope
FIVE single-file tasks. The one substantive change is a symbol patch flipping two flags in
META_TASK_POLICY. The rest keep the committed locks consistent without ever leaving a SCOPED
acceptance gate red. Each task edits exactly ONE file via a __JANUSMASK_PATCHES__ SYMBOL
patch (READ each target on disk first). No arrows; order is per-task `dependencies` only.

There is intentionally NO README.md task. Wave-1's difffuzz-w1-readme-table mangled the
self-encoding-manifest README (it no longer holds a §9 bypass_fuzzer TAXONOMY TABLE — the
remaining `harness_self_fix` mentions in README.md are unrelated scattered prose in §4.2/§12,
NOT a per-type bypass table), and the README audit test does NOT parse README.md; it compares
its own README_BYPASS_FUZZER dict against META_TASK_POLICY. The gated mirror is that dict
(fixed by difffuzz-w2-fix-readme-audit); the human-readable table is
docs/ARCHITECTURE_CONTRACTS.md §2.

# Inputs
RE-CONFIRM by reading each target before patching:
- harness/planner/taxonomies.py:1 — module-global annotated assignment
  `META_TASK_POLICY: dict[str, dict[str, bool]] = {...}`. Line 3 derives BYPASS_FUZZER_TYPES
  from it. Today `harness_self_fix` and `harness_plumbing` each carry `'bypass_fuzzer': True`.
  A SYMBOL patch on an AnnAssign target IS supported (git_integration._apply_symbol_patch
  locates a top-level Assign/AnnAssign by name; the new_block must be exactly one same-name
  assignment). The dict contains NO top-level function, so even if this task were fuzzed it
  fuzz-SKIPs (no patched FunctionDef / no primary function). It is NOT fuzzed regardless: it
  runs while harness_self_fix is still bypassed (its own flip is not yet committed).
- tests/adversarial/test_taxonomies.py — `test_known_bypass_values_are_in_bypass_set`
  parametrize list (:78-87) asserts BOTH flipped types (`harness_plumbing`, `harness_self_fix`)
  plus `hooks_integration` are IN bypass. Removing the two targets LOOSENS it to pass under
  both old and new policy.
- tests/harness/test_readme_audit_agent_d.py — `README_BYPASS_FUZZER` dict (:23-47):
  `harness_plumbing` (:29) and `harness_self_fix` (:46) are True; set both False so the mirror
  matches the flipped policy. `test_readme_taxonomy_bypass_fuzzer_matches_policy` cross-checks
  it vs policy and goes RED the instant the policy flips, so this MUST land before the flip.
- docs/ARCHITECTURE_CONTRACTS.md §2 table (:74-96) — `harness_plumbing` (:89) and
  `harness_self_fix` (:96) rows carry a ✓ in the bypass_fuzzer column; clear those two ✓.
  The "never narrow" invariant prose (:106-111) already records the wave-1 narrowing as
  sanctioned; extend its parenthetical exception to also name these two. No test parses this
  file, so it is non-gated.

# Non-Goals
- Do NOT edit harness/orchestrator.py or any _NEVER_AUTO_APPROVE file.
- Do NOT flip any entry other than harness_self_fix and harness_plumbing.
- Do NOT touch any skip_structural_decomp / skip_smoke_gates flag, or hand-edit the derived
  frozensets (they recompute).
- Do NOT add a README.md task (its §9 table no longer exists and is non-gated).

# Deliverables
Five tasks. Each TASK block is a single-file __JANUSMASK_PATCHES__ SYMBOL patch (or, for the
oracle, a whole test file). Every non_goals line below must contain the literal word
integration.

## TASK difffuzz-w2-routing-oracle
- meta_task_type: test_authoring
- dependencies: []
- mutation_target: harness.planner.taxonomies
- File: tests/harness/test_difffuzz_w2_routing.py
- Intent: a RED-on-HEAD behavioral oracle. Import `should_bypass_fuzzer` and the `Task`
  dataclass from `harness.orchestrator`. Assert `should_bypass_fuzzer(Task(task_id='t',
  meta_task_type=t))` is False for t in {harness_self_fix, harness_plumbing} (RED on HEAD where
  both still bypass; GREEN after the flip). Also assert CONTROLS that STAY True:
  `config_schema` and `mcp_plumbing` both still return True; and `test_authoring` still returns
  False. A real before/after routing assertion, not a tautology over the policy dict.
- test_spec: >=2 flipped-type asserts (is False) + >=3 control asserts.
- non_goals: must contain the literal word integration. Do not assert over META_TASK_POLICY
  directly; assert observable should_bypass_fuzzer behavior.
- verification_command: python -m pytest tests/harness/test_difffuzz_w2_routing.py -q

## TASK difffuzz-w2-loosen-membership
- meta_task_type: harness_self_fix
- dependencies: []
- File: tests/adversarial/test_taxonomies.py
- Vehicle: a __JANUSMASK_PATCHES__ SYMBOL patch on the parametrized
  `test_known_bypass_values_are_in_bypass_set` (replace that one test function). Remove
  `harness_plumbing` and `harness_self_fix` from its parametrize list; KEEP `hooks_integration`.
  This LOOSENS the lock so it passes under BOTH the current AND the flipped policy — so this
  task's own gate is GREEN before the flip and there is no red window. Do not touch any other
  function or weaken the derivation/subset invariants in this file (note
  `test_harness_self_fix_skips_smoke_gates` at :65 stays GREEN — the skip_smoke_gates flag is
  NOT being flipped).
- non_goals: must contain the literal word integration. This is a tests/** edit only; do NOT
  edit harness/**. This task runs while harness_self_fix is STILL bypassed, so it is not fuzzed.
- verification_command: python -m pytest tests/adversarial/test_taxonomies.py -q

## TASK difffuzz-w2-fix-readme-audit
- meta_task_type: harness_self_fix
- dependencies: [difffuzz-w2-loosen-membership]
- File: tests/harness/test_readme_audit_agent_d.py
- Vehicle: a __JANUSMASK_PATCHES__ SYMBOL patch on the module-global `README_BYPASS_FUZZER`
  dict assignment. Set `harness_plumbing` (:29) and `harness_self_fix` (:46) from True to False
  so the mirror PRE-MATCHES the flip. Change nothing else. CRITICAL ORDERING: this lands BEFORE
  difffuzz-w2-flip-policy. The instant the policy flips, the audit cross-check
  (test_readme_taxonomy_bypass_fuzzer_matches_policy) requires this dict to already read False;
  landing the dict first means: (a) before the flip, this dict (False) vs live policy (True) —
  but this task's SCOPED vcmd is the W2 ROUTING oracle, not the audit test, so its OWN gate is
  GREEN, and the audit test is not pulled in. (b) After the flip, dict and policy agree so the
  audit goes GREEN. This task still runs while harness_self_fix is bypassed (flip not yet
  committed), so it is NOT fuzzed.
- non_goals: must contain the literal word integration. This is a tests/** edit only; do NOT
  edit harness/**. Do NOT verify against the audit test here (it is transiently RED between this
  edit and the flip); verify against the routing oracle, which is GREEN once it exists.
- verification_command: python -m pytest tests/harness/test_difffuzz_w2_routing.py -q

## TASK difffuzz-w2-flip-policy
- meta_task_type: harness_self_fix
- dependencies: [difffuzz-w2-routing-oracle, difffuzz-w2-loosen-membership, difffuzz-w2-fix-readme-audit]
- File: harness/planner/taxonomies.py
- Vehicle: a single __JANUSMASK_PATCHES__ SYMBOL patch with name `META_TASK_POLICY` (the
  module-global annotated assignment). Reproduce the assignment verbatim EXCEPT flip ONLY these
  two entries' `bypass_fuzzer` True->False: `harness_self_fix` and `harness_plumbing`. Leave
  every other key/flag byte-identical; do NOT touch any skip_structural_decomp /
  skip_smoke_gates flag. The derived frozensets recompute; do not hand-edit them. This task is
  the LAST code/test edit; it runs while harness_self_fix is STILL bypassed (its own flip not
  yet committed) so it is NOT fuzzed. (Belt-and-suspenders: a META_TASK_POLICY symbol patch is
  a dict Assign with no FunctionDef, so the patched-symbol fuzzer SKIPs it even if armed.)
- non_goals: must contain the literal word integration. Do NOT edit orchestrator.py or any
  _NEVER_AUTO_APPROVE file; do NOT flip any entry other than harness_self_fix and harness_plumbing.
- verification_command: python -m pytest tests/harness/test_difffuzz_w2_routing.py tests/adversarial/test_taxonomies.py tests/harness/test_readme_audit_agent_d.py -q
- NOTE: this vcmd names the RED routing oracle (linking the red-pair so the RED oracle is
  accepted) PLUS the two doc-lock tests, which are all GREEN simultaneously ONLY after this
  flip — proving the flip closes every lock atomically. All three are import-only (no daemon).

## TASK difffuzz-w2-architecture-contracts
- meta_task_type: docs_writing
- dependencies: [difffuzz-w2-flip-policy]
- File: docs/ARCHITECTURE_CONTRACTS.md
- Intent: in the §2 enumeration table clear the bypass_fuzzer ✓ for the `harness_plumbing` (:89)
  and `harness_self_fix` (:96) rows (those two become blank in column 1); leave their
  skip_structural_decomp / skip_smoke_gates columns unchanged. THEN extend the §2 "never narrow
  BYPASS_FUZZER_TYPES" invariant prose (:106-111) so its sanctioned-narrowing exception ALSO
  names `harness_self_fix` and `harness_plumbing` as reviewed narrowings under the
  restore-differential-fuzzing program. No test parses this file, so it is non-gated; this is a
  docs_writing task and is NEVER differentially fuzzed.
- non_goals: must contain the literal word integration. Single file only; do NOT edit README.md
  or harness/** here.
- verification_command: python -m pytest tests/adversarial/test_taxonomies.py -q
