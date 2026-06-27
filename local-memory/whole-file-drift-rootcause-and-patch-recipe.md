---
name: whole-file-drift-rootcause-and-patch-recipe
description: harness_self_fix editing an existing .py with >1 modified symbol gets NO partial-edit prompt → naive whole-file submission → whole_file_drift reject loop; fix = brief must carry an explicit __JANUSMASK_PATCHES__ recipe (one symbol entry per modified symbol; R-anchor any new top-level symbol)
metadata: 
  node_type: memory
  type: project
  originSessionId: 5806b3a4-a81c-4bcd-bd94-332326f30802
---

🪝 ROOT CAUSE (found 2026-06-25; retention + decomposer harness fixes both hit it): a `harness_self_fix` (or any task) editing an EXISTING `.py` file that modifies MORE THAN ONE top-level symbol naively submits a whole-file rewrite, which `_finalize_existing_py_target` (harness/git_integration.py:778) REJECTS as `whole_file_drift` ("legacy whole-file submission modified N existing top-level symbols") → `reject_rollback` → re-blocked → re-planned → infinite retry loop (NO auto-fallback to patches). WHY: `prepare_task_prompt` (harness/orchestrator.py:~1468) emits the rich PARTIAL-EDIT/R-ANCHOR dispatch prompt ONLY when `task.partial_edit` is truthy OR `meta_task_type in BYPASS_FUZZER_TYPES`; `harness_self_fix` is in NEITHER and the planner sets no `partial_edit`, so it never gets patch-format guidance.

**Band-aid (brief-level, until the root fix lands) — make the impl-task spec carry an explicit `__JANUSMASK_PATCHES__` recipe:**
- Modifies >1 existing symbol → whole-file is rejected by whole_file_drift (allows ≤1) → submit `__JANUSMASK_PATCHES__` with ONE `kind:"symbol"` entry per modified symbol, each `code` = the FULL replacement def.
- For any NEW top-level symbol: do NOT give it its own entry (KeyError — name doesn't exist yet). R-ANCHOR it — embed its full `def` as an extra top-level node INSIDE an existing anchor symbol's `code` (entry `name` stays the existing symbol); the patcher inserts extras just before the anchor. [[new-symbol-needs-r-anchor-or-autocommit-fails]]
- Keep the recipe concise — verbose code blocks break the planner draft.

PROVEN: retention (1 new symbol + 3 modified → needs R-anchor) landed impl 22e1131; decomposer fix (~7 modified, NO new symbol → simpler, no anchor) landing via this recipe.

**Root fix in flight (2026-06-25, brief held/being-authored):** route `harness_self_fix` / existing-file multi-symbol edits through the PARTIAL-EDIT/R-ANCHOR prompt (or have the planner set `partial_edit:true`) so the band-aid is unneeded. [[turn-recurring-failures-into-pipeline-fixes]]

**Co-discovered planner CYCLE deadlock:** `_enforce_module_first` (harness/planner/plan_normalizer.py:146) fix-forward red-pair exception (`continue` ~:168 when impl's vcmd names the oracle's test file) returns WITHOUT stripping a pre-existing oracle→impl edge; with non-deterministic draft dep-direction the daemon stages oracle.deps=['impl'] AND impl.deps=['oracle'] from different runs → cycle → 0 dispatchable (deadlock; the validate_plan cycle check at plan_validator.py:280 does NOT gate incremental staging). Manual break: re-stage BOTH tasks atomically from ONE consistent validated plan. Root-fix brief also in flight.
