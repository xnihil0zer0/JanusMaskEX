# hierarchical_planner_design/

Design artifacts for the **hierarchical planner / epic plan-decomposition** feature
in JanusMaskJR. Produced 2026-06-05 via a 4-area Gemini panel (`agy`) + 4 Claude
adversarial reviewers. Hand off `PHASE1_BRIEF_SEQUENCE.md` to the next session.

## Start here
- **`PHASE1_BRIEF_SEQUENCE.md`** ← THE DELIVERABLE. 17-brief ordered Phase-1 (Level 1)
  implementation sequence with anchors, viability tags, dependency graph, and the
  "first light" / security-gated markers.

## Authoritative analysis (use these, not the raw drafts)
- `area_A_verified.md` — brief ingestion & planner front-end / schema
- `area_B_verified.md` — the decomposer core (dual-model differential decomposition)
- `area_C_verified.md` — dispatch, staging, execution & completion roll-up
- `area_D_verified.md` — Level-2 cross-cutting state (symbol ledger, failure prop, recursion)

Each ends with a §9 "Adversarial Review Findings" listing what was corrected vs the raw
Gemini draft and at what confidence.

## Raw / provenance (kept for audit; superseded by the verified versions)
- `gemini_area_{A,B,C,D}_*.md` — first-pass Gemini 3.5 Flash drafts
- `AGY_MASTER_PROMPT.txt` / `AGY_MASTER_PROMPT_v2.txt` — the prompt driving `agy`
  (v2 adds the print-mode synchronous-execution directive)
- `_exec_directive.txt` — the execution-mode preamble prepended in v2
- `agy_run.log` — `agy` run log (shows the sequential fallback)

## Key takeaways (if you read nothing else)
1. The dual-model decomposition is blocked until a **child-brief validator + mode
   threading** lands (`validate_plan` silently drops brief-shaped drafts) — Briefs 5-6.
2. Child briefs are **planless markdown re-planned by the daemon**, not pre-synthesized.
3. **Everything default-off** behind `hierarchical_planning.enabled`; only the allowlist
   auto-admission (Brief 15) needs owner security sign-off.
4. No class-method red zone, but the large hosts (`cli.main`, `validate_plan`,
   `_auto_promote`, `_auto_commit_accepted`) must be touched only via **new-helper +
   one-line call**, never body rewrites.
