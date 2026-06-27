---
name: dont-conflate-built-with-works
description: "Owner feedback (2026-06-12): a non-functional CORE capability is a blocker to stop on, not a footnote — don't equate 'all parts built + tests green' with 'the product works'"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 21fc43be-923d-4aed-9491-9aab1121b842
---

When I reported the NGv2 bounty epic, I framed "all 9 phases built, 1462 tests green, machinery runs end-to-end and parks safely" as DONE — and relegated "live run confirmed 0/5 real vulnerabilities" to a footnote + a 'next lever'. The owner pushed back: confirming a real, claimable PoC is the entire point of the product; 0 real confirms means the core capability does not work, and that should have been recognized as a BLOCKER to fix IMMEDIATELY, before declaring completion or proceeding.

**Why:** green oracles + landed modules prove the *scaffolding* exists; they do NOT prove the system does its job. The acceptance bar for this product is "produces a PoC that can actually be claimed," not "the pipeline ran without error and fail-closed." I optimized for the phase checklist instead of the end outcome.

**How to apply:** For any build, identify the ONE end-to-end outcome that defines success (here: a real confirmed, novel, claimable PoC) and treat anything short of it as unfinished — surface it as a blocker, stop, and fix it, rather than reporting per-phase greens as "complete." A live/integration result that is honest-but-negative on the core capability outranks any number of passing unit oracles. Don't let "withhold-and-check passed" (it parked safely) mask "the thing produces nothing of value." See [[real-bounty-machinery-handoff]] and the handoff `HANDOFF_poc_writer_real_claimable_pocs.md`.
