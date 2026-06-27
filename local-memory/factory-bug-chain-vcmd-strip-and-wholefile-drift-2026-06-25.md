---
name: factory-bug-chain-vcmd-strip-and-wholefile-drift-2026-06-25
description: Two factory bugs blocking NGv2 baseline producer + the empirically-verified fix chain (route harness_self_fix → partial-edit gate)
metadata: 
  node_type: memory
  type: project
  originSessionId: e5786102-b9ed-4e34-87c8-21604424714e
---

🔗 FACTORY BUG CHAIN (discovered+RESOLVED 2026-06-25, all adversarially verified + landed). ✅ALL THREE FIXED: files_touched strip (30e8e74), verification_command strip (29c98ad via patches path), whole_file_drift route fix (1dfc1a2 orchestrator.py:1468 now `or mtt=='harness_self_fix'`). baseline producer landed first-try on fresh re-run (cce869a). Record below kept for the mechanism. ORIGINAL (blocking) writeup:

**Bug 1 — decomposer strips `verification_command`** (sibling of the just-landed files_touched fix 30e8e74). `harness/task_decomposer.py` `Subtask` dataclass + all `Subtask(...)` ctors + `enqueue_subtasks` propagate `files_touched`/`mutation_target` but NOT `verification_command`. So any impl that fails first-try → decomposes via planner_review → sub-task gets `verification_command:None` → consumer `_resolve_verification_command` (orchestrator.py:2100) finds nothing (parent not in tasks/processed/) → `verification_missing` → `auto_commit_failed`. The baseline impl candidate is CORRECT (passes oracle 15/15) but was discarded at commit. Fix brief = `decomposer_propagate_verification_command` (tasks `decomposer-propagate-vcmd-{oracle,impl}`, 5-entry __JANUSMASK_PATCHES__). BLOCKED by Bug 2.

**Bug 2 (ROOT) — harness_self_fix whole_file_drift on >1 modified symbol.** Partial-edit dispatch gate `orchestrator.py:1468` requires `task.partial_edit or mtt in BYPASS_FUZZER_TYPES`; `harness_self_fix` is in NEITHER → agent never gets the __JANUSMASK_PATCHES__ prompt (recipe lands only as inert `spec.implementation_notes`) → naive whole-file → drift gate `git_integration.py:778` rejects (`len(changed)>1`). Same exclusion mirrored on validate path orchestrator.py:1693.

**FIX = `brief_hooks_route_harness_self_fix_partial_edit.md`** (already drafted, repo root; NOT yet ingested). Widens :1468 to `... or mtt=='harness_self_fix'`. LANDABLE despite editing orchestrator.py multi-... no — its impl edits only ONE symbol `prepare_task_prompt` via patch, which commits via the UNGATED patches path (`_save_final_output` :1847 writes .patches.json ungated; `commit_accepted_output`→`_commit_accepted_output_patches` git_integration.py:864 never calls the drift `_finalize_existing_py_target`, no drift cap). Needs operator decision file `state/control/decisions/route-harness-self-fix-partial-edit-impl.json` (orchestrator.py is _NEVER_AUTO_APPROVE trust-core). LOW risk (additive condition). Red-gate: probe in REAL bwrap jail (loopback up) not `unshare -n -r`.

**PATH:** ingest route fix (+decision file) → land → re-run vcmd fix (clear stale `state/output/decomposer-propagate-vcmd-impl.py` first) → land → daemon self-reloads → re-run baseline (decompose now safe). FAST baseline alt = parent fresh re-run (new module, no drift) but re-blocks if it fails first-try.

cP producers status: detect/jail/health/reachability LANDED+demonstrated (oracles pass on direct run); baseline = last one. Relates [[whole-file-drift-rootcause-and-patch-recipe]] [[ngv2-closure-program-active-2026-06-24]] [[pipeline-first-attempt-before-handedit]].
