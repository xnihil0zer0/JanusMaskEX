---
name: issue-fix-via-pipeline-then-rerun
description: "Owner directive 2026-06-09 — on any issue, diagnose, fix the ROOT CAUSE through the pipeline, then rerun the failed task"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: f6771914-e763-41ad-a6ad-70004f695509
---

Owner directive (2026-06-09): "From now on, if you encounter an issue, diagnose, fix through the pipeline, and then rerun the previous task."

**Why:** per-task state-surgery workarounds (editing task JSON specs, re-staging) leave the underlying harness defect latent — the next epic trips over it again. The owner wants defects cured durably via the gated pipeline, not papered over.

**How to apply:** when a pipeline task fails on a harness defect: (1) diagnose the root cause precisely; (2) hand-author a RED oracle (sanctioned) + a `harness_self_fix` brief targeting the defective harness module, dispatch through the pipeline with the `state/control/decisions/<tid>.json` approval; (3) once the fix lands, re-stage/rerun the originally failed task unmodified. Workaround spec-edits are only a stopgap when the run would otherwise stall — the root-cause leaf must still follow. Boundary unchanged: `_NEVER_AUTO_APPROVE` files ([[never-hand-edit-production-outside-pipeline]]) still require explicit owner clearance first — pick fix seams OUTSIDE that set when possible.

Open defects this directive applies to (from [[autocompiler-phase-a-dispatch]]): (a) emission-format mis-routing — agents can emit patches/`__JANUSMASK_MANIFEST__` for a module-creating single-`.py` task and dead-end at auto-commit (patches can't create files, `git_integration.py:1400`); enforce whole-file at a non-NEVER seam (worker prompt/staging layer). (b) leaf planner copies non-target `config/**` registration files into `files_touched` → sensitive-glob auto-commit refusal; sanitize/reject at `plan_normalizer`/`plan_validator` (both pipeline-fixable with decision files).
