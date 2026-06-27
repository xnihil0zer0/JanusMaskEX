---
name: new-symbol-needs-r-anchor-or-autocommit-fails
description: Adding a BRAND-NEW top-level symbol via a standalone kind:symbol patch fails patch-apply (KeyError) and surfaces only as opaque auto_commit_failed; must use the R-ANCHOR additive pattern (anchor on an existing symbol)
metadata: 
  node_type: memory
  type: feedback
  originSessionId: ac57c0e0-1dc8-4930-b4ef-f690107be1f4
---

A `__JANUSMASK_PATCHES__` `kind:symbol` patch can ONLY **replace** a top-level def/async-def/class that **already exists** in the target file. Naming a symbol that does NOT yet exist fails the patch-apply path with `KeyError` → no edit applies → the task is rejected with the **opaque `auto_commit_failed`** outcome (NO `verification_failed` row; `decode_check ok=false`). Proven 2026-06-19: the `state_reconcile_disable` impl emitted a standalone `{'kind':'symbol','name':'_state_reconcile_disabled',...}` for a brand-new helper and got TWO `auto_commit_failed` rejections before I parsed the submission and found `_state_reconcile_disabled` did not exist in the file (anchor-exists check = False).

**Why:** the orchestrator dispatch prompt (`harness/orchestrator.py:~1411`, "ADDING A NEW TOP-LEVEL SYMBOL (R-ANCHOR)") already documents this, but the worker sometimes ignores it, and the failure telemetry does not say "symbol X not found" — it just says `auto_commit_failed`, which masks the real cause.

**How to apply:** when a brief adds a brand-new top-level symbol via partial-edit patches, SPELL OUT the R-ANCHOR ADDITIVE pattern in the brief: pick an EXISTING adjacent top-level symbol as the `name` anchor (a tiny one is ideal, e.g. `_auto_promote_disabled`), and have `code` reproduce the NEW symbol(s) immediately FOLLOWED BY the anchor reproduced VERBATIM. The harness inserts the new symbol(s) before the anchor and preserves the rest of the file.

★DIAGNOSIS IS NOW EASY (root-cause fix LANDED 2026-06-19 `fec90f0`, brief `commit_fail_symbol_telemetry`): `_commit_accepted_output_patches` now emits an **`auto_commit_patch_failed`** row to `state/impl_progress.jsonl` carrying the symbol-bearing `reason` (`patch apply failed for <file>: '<symbol>'`) whenever a patch apply raises KeyError/ValueError. So a `auto_commit_failed` with no `verification_failed` row → `grep auto_commit_patch_failed state/impl_progress.jsonl` shows the exact missing symbol directly (no more parsing `state/sessions/<agent>_round1_<task>_submission.json` by hand). The old manual method still works: `harness.git_integration._parse_patches(submission['code'])` + `ast.parse` top-level check. This closed the "Candidate ROOT-CAUSE pipeline fix" noted here previously (turn-recurring-failures-into-pipeline-fixes). See [[spec-only-pipeline-augment-agents]], [[backup-detach-fixes-systemic-autocommit]], [[doc-verify-and-reconciler-hardening-2026-06-19]].
