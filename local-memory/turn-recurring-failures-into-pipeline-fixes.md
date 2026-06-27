---
name: turn-recurring-failures-into-pipeline-fixes
description: "Owner directive (2026-06-12): when you recognize a REPEATING failure pattern, submit a brief to fix the root cause so it can't recur — don't just work around it again"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 58835951-ec27-4443-9595-c4b7d49b1eab
---

When I recognize a pattern in HOW builds/pipeline runs repeatedly fail (a gotcha worked around more than once across sessions), I should submit a brief to fix the ROOT CAUSE so the pattern is structurally prevented going forward — not keep hand-working-around it each time.

**Why:** working around a recurring failure burns wall-clock + context every recurrence and leaves the trap for the next session; a one-time pipeline fix removes the whole class. This is the same principle as the rest of the repo (correctness by withholding+checking, not by repeated manual care) applied to the harness's own friction.

**How to apply:**
- Recurring root causes in SENSITIVE-but-not-irreducible paths (`harness/planner/**`, most of `harness/**`) → fix via a `harness_self_fix` leaf with a hand-authored RED oracle (auto-approves under current `auto_approve_sensitive_harness: true`). See [[issue-fix-via-pipeline-then-rerun]].
- Recurring root causes in the IRREDUCIBLE set (`git_integration.py`, `orchestrator.py`, `autowork_daemon.py`, `agent_jail.py`, `paths.py`, `interceptors.py`, `selfheal.py`, `services/**`) → CANNOT pipeline; flag to owner for hand-edit clearance per [[never-hand-edit-production-outside-pipeline]].
- VERIFY the root cause in current code before authoring (memory can be stale).
- Candidate recurring patterns standing as of 2026-06-12 (verify each): (1) `plan_validator._is_module_creating` resolves `files_touched` vs JM root not `working_dir` → every external ngv2 leaf forced to name a `*_wired` oracle [planner, fixable]; (2) redundant `test_authoring` sibling auto-emitted even when the oracle is pre-committed → ~7min churn per leaf, trips runaway_ceiling [planner, fixable]; (3) `cd`-prefixed `verification_command` silently overrides `cwd=staging_worktree` → tests the wrong tree, new-symbol EDIT fails [planner validation, fixable]; (4) stale `git_commit.lock` (dead PID) wedges daemon after os.execv self-commit [git_integration/daemon, OWNER-ONLY]; (5) daemon has no brief-level dep gating → child importing sibling staged first → smoke_failed [autowork_daemon, OWNER-ONLY].
