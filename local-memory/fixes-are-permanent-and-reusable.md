---
name: fixes-are-permanent-and-reusable
description: "Owner principle — every fix must be a permanent root-cause harness change, hence reusable by definition; never a one-off workaround"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: ae16acba-9ad9-45c6-989f-a8c880d79cef
---

Owner (2026-06-14): "all fixes should be reusable, because they are permanent."

**Why:** A correct fix lands in the harness/factory as a permanent root-cause change, so it automatically benefits every future case — reusability is not a bonus to call out, it is the definition of a real fix. Framing a fix as "also reusable" implies the default is a one-off, which is the failure mode to avoid. A workaround that unblocks only the case in front of me (a latent patch, a brief-prose nudge, a manual drive) is NOT a fix.

**How to apply:** When I hit a defect, fix the ROOT in the permanent machinery (planner/orchestrator/gates/normalizer) via the pipeline so it can never recur for ANY leaf — don't narrate "this also helps other leaves" as if optional. Reinforces [[issue-fix-via-pipeline-then-rerun]] (diagnose → harness_self_fix leaf w/ RED oracle → rerun, no latent workarounds) and [[dont-conflate-built-with-works]]. Concrete example: the planner attaching a stray `mutation_target` to new-file impl tasks was fixed by a permanent `_strip_stray_mutation_targets` normalizer pass, NOT by hand-tuning one brief (see [[srcdrive-epic-leaf1-and-muttarget-gate-bug]]).
