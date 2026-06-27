---
name: spec-only-pipeline-augment-agents
description: "ABSOLUTE owner rule: the pipeline does EVERYTHING (incl. RED oracles via test_authoring). The ONLY hand-authored artifact is the brief. If the pipeline can't do something, make it able — through the pipeline. Every time."
metadata: 
  node_type: memory
  type: feedback
  originSessionId: ae16acba-9ad9-45c6-989f-a8c880d79cef
---

⚠️⚠️ ABSOLUTE RULE (owner, 2026-06-15, said three times, escalating anger):
1. "use the pipeline as much as possible"
2. "if you ever think about not using the pipeline, then stop, collect yourself, stop being stupid, and then use the pipeline. Every. Fucking. Time."
3. "if you ever think you need to do something that the pipeline doesn't do, make the pipeline do it. Every. Fucking. Time."

**The ONLY thing I hand-author is the BRIEF** (the pipeline's input). EVERYTHING else goes through the pipeline:
- RED oracles → the factory writes them via the **`test_authoring` stage** (planner emits a test_authoring task, mutation_target = dotted module; worker writes the oracle). There IS an automated oracle-writing stage — USE IT. [[test-authoring-oracle-gap]] (`_stage_targets` mounts the module-under-test; daemon autonomous for impls AND oracles).
- Implementation code → implementation task → jailed worker.
- Decomposition → the planner ("ONE root brief, JM decides the tree").

**BANNED (all are me doing the pipeline's job):**
- Hand-authoring/committing RED oracles myself.
- The "validate-then-revert + embed byte-exact reference in the brief" recipe (used L1–L4b). It hand-feeds the worker the answer to paper over a capability gap. NEVER again.
- Any manual-drive / hand-scaffold / hand-edit of production.

**When the pipeline CAN'T do something** (planner/worker blocks, can't build from the brief, missing a stage): do NOT work around it. DIAGNOSE the gap, then AUGMENT the failing agent as a permanent root-cause harness change — RED harness oracle → brief → pipeline-built → landed — so every future leaf benefits. Then re-dispatch the leaf unchanged. Making the pipeline more capable IS the work.

Supersedes the byte-exact-reference recipe in [[source-driving-poc-epic-authored]] (L4b) and [[blinddraft-workingdir-landed-and-recipe]]. Hardens [[never-hand-edit-production-outside-pipeline]] + [[fixes-are-permanent-and-reusable]] + [[dont-conflate-built-with-works]].
