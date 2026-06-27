---
name: never-hand-edit-production-outside-pipeline
description: Owner directive (2026-06-05) — NEVER hand-edit production/core harness files outside the pipeline; oracles/tests MAY be hand-authored; any unavoidable hand-edit must be cleared with the owner FIRST
metadata: 
  node_type: memory
  type: feedback
  originSessionId: d3ea034b-3dc5-4080-bdbc-08a57af5ad08
---

**HARD RULE (owner directive, 2026-06-05, after a violation):** Do NOT hand-edit
production or core `harness/**` files and `git commit` them directly. Route every
non-bootstrap code change THROUGH THE PIPELINE (planner.cli → stage → orchestrator
worker → auto-commit). For a `_NEVER_AUTO_APPROVE` deny-listed file, the proper
operator path is a `meta_task_type=harness_self_fix` dispatch + a
`state/control/decisions/<tid>.json` approve file — NOT a raw hand-edit. **If a hand
edit is absolutely unavoidable, CLEAR IT WITH THE OWNER FIRST.**

**Why:** the project's entire thesis is autonomous self-building through the pipeline
(dual-agent synthesis + AST gate + mutation/non-vacuity gate + apply-scope). A raw
hand-edit bypasses ALL of it and produces unverified code in exactly the files that
gate the system's safety. It also wastes the just-proven hands-off loop.

**What IS allowed to be hand-authored:** RED oracle / characterization TEST files.
The Phase-1 resume recipe explicitly says "operator HAND-AUTHORS the RED oracle test."
Oracles are not pipeline-synthesized. Updating stale test assertions / mutation
targets to the intended posture is also fine (test-debt alignment).

**The violation that produced this rule:** in session 2026-06-05 #3 I hand-edited
`harness/autowork_daemon.py` (ITEM1 commit-lock-reclaim, deny-listed CORE) and
hand-wrote `harness/planner/plan_normalizer.py` + `harness/planner/cli.py` (the
normalizer, NON-deny — which was the very thing meant to demonstrate the hands-off
pipeline loop) and committed both directly. Owner caught it; both were reverted
(`350aaba`/`c85073d`). The kept test commits were fine. See
[[phase2-autonomy-security-posture]] SESSION #3 for the full state.

**Mechanical default going forward:** before editing any `harness/**` file, ask "is
this a test/oracle?" If no → it goes through the pipeline. If it's deny-listed →
pipeline as `harness_self_fix` + decision file. If neither is possible → ask the owner.
