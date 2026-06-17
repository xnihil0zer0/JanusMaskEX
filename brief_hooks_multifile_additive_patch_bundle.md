---
title: Multi-file additive patch bundles — never force a whole-file rewrite of a large existing file
meta_task_type: harness_self_fix
working_dir: /home/xnihil0zer0/JanusMaskJR
required_task_ids:
  - oracle_multifile_patch_bundle
  - git_integration_newfile_patch
  - orchestrator_patch_routing_validation
files_touched:
  - harness/git_integration.py
  - harness/orchestrator.py
  - tests/adversarial/test_multifile_additive_patch_bundle.py
verification_command: python -m pytest tests/adversarial/test_multifile_additive_patch_bundle.py -q
---

# Title

Multi-file additive patch bundles: a task that additively edits a large existing
`.py` file must NEVER be forced to reproduce that whole file just because it is
bundled with another file (e.g. a new test file).

# Scope

When a task edits a large existing `.py` file additively (add a few top-level
symbols, extend a list/dict) AND also touches a second file (e.g. a brand-new
test file), the harness today forces the WHOLE bundle onto the verbatim
`__JANUSMASK_MANIFEST__` path, which requires reproducing the entire large file
byte-for-byte. That is fragile, truncation-prone, and clobber-prone — it is the
failure mode that rewrote a 720-line file just to append five functions.

This is a routing gap, not a property of the edit. The `__JANUSMASK_PATCHES__`
partial-edit path (with the R-ANCHOR additive pattern) already exists and is
exactly right for additive edits to large files, and the patch APPLY/COMMIT
machinery is ALREADY multi-file-capable and atomic
(`_commit_accepted_output_patches` groups patch entries by their `'file'` key
and commits all files in one revision). The only reasons a multi-file additive
bundle cannot use it today:

1. Routing: `_requires_verbatim_manifest` (harness/orchestrator.py:1346-1363)
   forces the manifest prompt for any `len(files_touched) > 1`, even when every
   target is `.py`.
2. New-file creation: the patch applier `read_text()`s every target
   (harness/git_integration.py:1402), so it cannot CREATE the new test file —
   there is no patch entry kind that writes a whole new file.

Close BOTH so an additive edit to a large existing file is never forced into a
whole-file reproduction merely because it is bundled with another file — for any
task (human-authored brief or planner-decomposed leaf). This is a structural
guarantee, not a per-task workaround.

The capability to build, by component:

C1 — New `newfile` patch kind (harness/git_integration.py). Add a third
`__JANUSMASK_PATCHES__` entry kind alongside `symbol` and `region`:
`{'file': '<rel>', 'kind': 'newfile', 'code': r'''<whole file source>'''}`.
- Parser `_parse_patches` (git_integration.py:1008-1070): extend the per-entry
  validation (the `kind not in (...)` check at 1062 and per-kind key checks at
  1064-1067) to accept `kind == 'newfile'`, which requires `'file'` and `'code'`
  (no `'name'`, no `'marker'`). Unknown kinds still return None; keep the
  None-on-malformed discipline.
- Applier `_commit_accepted_output_patches`, the per-file apply loop
  (git_integration.py:1399-1426): when a `rel`'s entries are a single `newfile`
  entry, the target MUST NOT already exist on disk (refuse with an error — never
  clobber an existing file via `newfile`); skip the `read_text` at 1402 for that
  rel and write `entry['code']` as the whole new file. A `rel` that already
  exists keeps the `symbol`/`region` path unchanged. A single `rel` is either
  all existing-file patches OR exactly one `newfile` entry (never mixed).
- Atomicity: compute every file's final text FIRST (read+apply, or newfile
  content) and only AFTER every entry applies successfully perform the on-disk
  `write_text`s, then stage+commit — so a mid-loop apply failure (e.g. a bad
  symbol name on a LATER file) leaves ZERO files written to the worktree.

C2 — Route `.py`-only multi-file bundles to the patch path
(harness/orchestrator.py). `_requires_verbatim_manifest` (1346-1363) must return
True ONLY when some target is not `.py` (manifest stays the route for non-.py).
An all-`.py` `files_touched` returns False regardless of length. Update the
now-stale docstring. In `prepare_task_prompt` (the partial-edit/patches block
gated at 1408), emit the patch-bundle prompt for a multi-`.py` bundle even when
SOME targets do not yet exist (the new test file): adjust the `_targets_exist`
gate so the patches prompt fires when the bundle is all-`.py` and the EXISTING
targets are present; document the `newfile` kind in that prompt text.

C3 — Validate multi-file patch submissions (harness/orchestrator.py). In
`_validate_submission` (the patches branch at 1605-1626), a parseable
`__JANUSMASK_PATCHES__` list spanning multiple files (including `newfile`
entries) must validate and return success BEFORE the `manifest_missing` guard
(1631). `newfile` entries carry whole-file `.py` source — validate it parses.
The existing rule that a WHOLE-FILE single submission on a multi-file task is
rejected (`manifest_missing`) stays intact (it only fires when neither a
`__JANUSMASK_PATCHES__` nor a `__JANUSMASK_MANIFEST__` block is present).

# Non-Goals

- Not an integration test of the live daemon — unit/adversarial oracles against
  the patch/manifest routing and apply seams are sufficient (this is an
  integration-excused scope).
- Does NOT remove or weaken the `__JANUSMASK_MANIFEST__` path; manifest remains
  the route for any non-`.py` target.
- Does NOT change the planner, brief schema, or meta_task_type taxonomy.

# Inputs

Exact code anchors (already verified on HEAD):
- harness/git_integration.py:1008-1070 — `_parse_patches` (per-entry kind/key
  validation at 1059-1067).
- harness/git_integration.py:1072-1255 — `_apply_symbol_patch` (R-ANCHOR
  additive insertion already implemented).
- harness/git_integration.py:1292-1451 — `_commit_accepted_output_patches`
  (already groups by `'file'`, atomic single commit; apply loop 1399-1426;
  per-target `read_text` at 1402).
- harness/orchestrator.py:1346-1363 — `_requires_verbatim_manifest` (size-blind
  count/`.py` routing; its docstring incorrectly claims one-file-at-a-time).
- harness/orchestrator.py:1365-1416 — `prepare_task_prompt` (patches block gated
  `not use_manifest` at 1408; manifest block at 1412).
- harness/orchestrator.py:1478-1656 — `_validate_submission` (patches branch
  1605-1626; `manifest_missing` guard 1631-1636).

# Deliverables

1. The C1/C2/C3 harness changes above, landed via the partial-edit/R-ANCHOR path
   (do NOT reproduce orchestrator.py or git_integration.py whole).

2. A pipeline-authored RED oracle file
   `tests/adversarial/test_multifile_additive_patch_bundle.py` (test_authoring)
   — each test FAILS on current HEAD and PASSES after the fix:
   - `_parse_patches` accepts a `newfile` entry (`file`+`code`, no name/marker)
     and returns None for an unknown kind and for a `newfile` missing `code`.
   - `_commit_accepted_output_patches` on a bundle
     `[{existing.py: R-anchor symbol patch adding a new top-level fn},
       {brand-new.py: newfile}]` lands BOTH in ONE commit: existing file keeps
     every untouched byte and gains the new symbol; new file is created.
   - `newfile` whose target already exists is REFUSED (`committed == False`,
     no clobber).
   - Atomicity: a bundle whose SECOND entry fails to apply leaves the FIRST
     file's bytes UNCHANGED on disk and `committed == False`.
   - `_requires_verbatim_manifest` returns False for a multi-`.py`
     `files_touched`, True for a bundle containing a non-`.py` target.
   - `prepare_task_prompt` for a multi-`.py` bundle (one existing large file +
     one absent new `.py`) emits the `__JANUSMASK_PATCHES__` prompt mentioning
     `newfile`, NOT the `__JANUSMASK_MANIFEST__` whole-file prompt.
   - `_validate_submission` accepts a multi-file `__JANUSMASK_PATCHES__`
     submission and still rejects a whole-file SINGLE submission on a multi-file
     task (`manifest_missing`).

3. Anti-seesaw — the fix MUST keep ALL of these existing oracles green (they pin
   invariants the change preserves: non-`.py`→manifest, single-`.py`→patches,
   manifest accepted for multifile, whole-file-single rejected, .patches.json
   precedence over .files.json):
   - tests/adversarial/test_aw10d_patches_contract.py
   - tests/adversarial/test_patches_apply_adversarial.py
   - tests/adversarial/test_r_anchored_patch_extra_nodes.py
   - tests/adversarial/test_patch_allow_toplevel_assign.py
   - tests/adversarial/test_punb1_annassign_target.py
   - tests/adversarial/test_punb2a_committer_precedence_adversarial.py
   - tests/adversarial/test_punb2b_validator_encoding_adversarial.py
   - tests/adversarial/test_nonpy_manifest_routing.py
   - tests/adversarial/test_orchestrator_manifest_required.py
   - tests/test_symbol_patch_indented_method.py
   - tests/test_partial_edit_prompt_r_anchor_wired.py
   - tests/test_prepare_task_prompt_external_partial_edit_wired.py

# Required plan shape

Decompose into EXACTLY these three leaves, using these EXACT task_ids (they are
declared in frontmatter `required_task_ids`; validate_plan rejects the plan with
`missing_required_task` if any is absent). This is a deliberate fix-forward
red-pair: the RED `test_authoring` oracle for the EXISTING modules is accepted
through the acceptance gate because each impl leaf's verification_command runs
the oracle's OWN authored test file.

1. task_id: oracle_multifile_patch_bundle
   - meta_task_type: test_authoring
   - files_touched: [tests/adversarial/test_multifile_additive_patch_bundle.py]
   - mutation_target: harness.git_integration   (bare dotted module-under-test;
     its file harness/git_integration.py EXISTS — this is the existing-module
     red-pair, NOT a new module)
   - verification_command: python -m pytest tests/adversarial/test_multifile_additive_patch_bundle.py -q
   - dependencies: []
   - Authors the RED oracle of deliverable 2; RED on current HEAD, GREEN after
     the two impls land. spec_author: null.

2. task_id: git_integration_newfile_patch
   - meta_task_type: harness_self_fix
   - files_touched: [harness/git_integration.py]
   - verification_command: python -m pytest tests/adversarial/test_multifile_additive_patch_bundle.py -q
   - dependencies: [oracle_multifile_patch_bundle]
   - Implements C1 (newfile patch kind in _parse_patches + atomic applier in
     _commit_accepted_output_patches). Edit additively via the R-ANCHOR/symbol
     patches path; do NOT reproduce git_integration.py whole.

3. task_id: orchestrator_patch_routing_validation
   - meta_task_type: harness_self_fix
   - files_touched: [harness/orchestrator.py]
   - verification_command: python -m pytest tests/adversarial/test_multifile_additive_patch_bundle.py -q
   - dependencies: [oracle_multifile_patch_bundle]
   - Implements C2 (_requires_verbatim_manifest + prepare_task_prompt) and C3
     (_validate_submission). Edit additively via the R-ANCHOR/symbol patches
     path; do NOT reproduce orchestrator.py whole.

Each leaf's `non_goals` MUST contain the word "integration" (integration-excused
scope — see Non-Goals; the planner's `missing_integration_test` gate at
plan_validator.py:250-256 is excused only when a non_goal contains "integration").
Each leaf's `test_spec.regression_tests` MUST contain >= 2 entries.

Pairing rationale (do not change): the oracle declares NO dependencies; both
impls depend on the oracle. load_sibling_tasks (redpair_acceptance.py) then finds
both impls as the oracle's siblings via the reverse-dependency scan.
is_fix_forward_redpair returns True because git_integration_newfile_patch's
files_touched contains harness/git_integration.py (== mutation_target path) and
its verification_command substring-contains the oracle's own test file. The same
vcmd substring keeps the oracle alive through the planner's keystone red-pair
KEEP guards in plan_normalizer.py.
