---
name: delegate-everything-preserve-oversight-context
description: "Owner directive — delegate ALL investigation/authoring/verification to sub-agents; my context is for oversight, keep it lean"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: c03fdb29-c511-46c5-a8df-c5c401fae776
---

⚠️ OWNER FEEDBACK (2026-06-21): "You should be delegating work to sub-agents, instead of investigating and writing things yourself. Your job is to preserve your context, so that you can provide oversight for as long as possible."

**Why:** Every inline Bash read, analytic script, pytest run, and file Read I do myself consumes the oversight context window. The longer my context stays lean, the longer I can orchestrate the campaign without compaction. Sub-agent token use is FREE to my context — only their final verdict returns.

**How to apply:**
- DELEGATE: codebase investigation, analytic/repro scripts, brief authoring, brief tightening, WORKS-gate verification, commit confirmation, state-schema tracing, oracle/impl diagnosis. Ask the agent to return ONLY a concise structured verdict (pass/fail + key facts + file:line), not dumps.
- KEEP INLINE (cheap, oversight-critical): operator actions that are quick and don't bloat context — `rm`/`touch` for state cleanup (pause/purge/unpause re-dispatch recipe), allowlist/decision/selfheal-marker edits, launching the oversight monitor, reading the monitor's one-line snapshot, memory updates, routing one agent's result to the next agent.
- Do NOT read large files, run pytest, or write analytic scripts myself when a sub-agent can return the answer. Do NOT author briefs myself — dispatch an authoring agent (pass it the redpair/import-clean/nested-closure mechanics in the prompt).
- Pattern: investigation agent → returns spec → authoring agent (gets spec + factory mechanics) → returns brief → I do the cheap re-dispatch ops → monitor → verification agent → verdict. I am the router/decider, not the executor.

Linked: [[spec-only-pipeline-augment-agents]], [[fork-pursues-dominant-context-task]] (use FRESH agents, not forks, for divergent sub-tasks), [[ngv2-closure-program-launch]].
