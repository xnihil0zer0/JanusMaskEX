---
name: pipeline-first-attempt-before-handedit
description: "Owner directive — attempt \"irreducible\" impure code through the pipeline ONCE (documented failure) before declaring hand-edit; owner-gated ≠ leave-it-not-working"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 5806b3a4-a81c-4bcd-bd94-332326f30802
---

🔁 OWNER DIRECTIVE (2026-06-24): No "irreducible-tier / impure" producer (the NGv2 P2.1 cP helpers: jailed venv-build, target service-start+loopback-bind, settrace benign-ping, jailed benign-run, any `poc_runner_live`-class side-effecting code) may be declared "requires owner hand-edit / not-pipeline-built" until it has been ATTEMPTED through the planner→stage→worker pipeline AT LEAST ONCE and that attempt FAILED with a documented, specific reason (e.g. a concrete `fuzz_error`). Pipeline-first is mandatory; hand-edit is the LAST resort, escalated to owner ONLY after a recorded pipeline failure.

**Why:** I had mis-framed cP as "build the pure gates, hand-author the impure helpers behind an owner gate" (per the OLD DECOMP §5 Q2 recommendation, now SUPERSEDED). Owner corrected: "BUILT≠WORKS" means *not done until demonstrated running live* — a HIGHER bar — NOT "build it but deliberately leave it not-quite-working / owner-gated so it doesn't run." Owner-gated never means "leave it built-but-not-working."

**How to apply:** When a leaf looks un-pipelineable, author a brief and run it through the factory anyway, augmenting the agents/planner THROUGH the pipeline as needed. Only a real, logged pipeline failure justifies escalating a SINGLE producer to a hand-edit owner decision — then still drive it to demonstrated-live. Plan docs already reframed (DECOMP §5 Q2/Q3, INTEGRATION_LEAF_TODO, both research docs carry the verbatim "★ POLICY — PIPELINE-FIRST IS MANDATORY" block). Sharpens [[spec-only-pipeline-augment-agents]], [[never-hand-edit-production-outside-pipeline]], [[done-means-observed-working-not-a-green-gate]], [[dont-conflate-built-with-works]].
