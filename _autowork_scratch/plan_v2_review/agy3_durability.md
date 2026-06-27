# Adversarial Review: Durability & Anti-Rewedge (Sub-Agent 3)

This review focuses on pipeline durability. It identifies the mechanisms required to prevent the factory from re-wedging once operational, including lock watchdogs, unified controls, clean retries, and standing safety/deadlock-breaker passes.

## Discrete Corrections

1. **LABEL:** `Auto Clear Stale Git Locks`
   - **Correction:** Implement a lock-clearing watchdog in the inactivity check inside [autowork_daemon.py:2846-2931](file:///home/xnihil0zer0/JanusMaskJR/harness/autowork_daemon.py#L2846-L2931) that deletes stale `git_commit.lock` files if the owning process is dead or inactive for over 10 minutes.
   - **Rationale:** Stale git locks are the primary cause of `daemon_inactivity_stuck` (30 events). Auto-clearing this lock prevents permanent scheduler blocks and watchdog restart loops.
   - **Ordering impact:** Moves to Step 1 (immediate action).

2. **LABEL:** `Unify Pause Primitive Channels`
   - **Correction:** Modify the legacy pause check in [control_gate.py:48-66](file:///home/xnihil0zer0/JanusMaskJR/harness/control_gate.py#L48-L66) to read from the existence of the single authoritative file path `state/control/autowork/pause` used by `_decide()` in [autowork_daemon.py:1773](file:///home/xnihil0zer0/JanusMaskJR/harness/autowork_daemon.py#L1773).
   - **Rationale:** Eliminates split-brain bugs where the orchestrator processes tasks while the daemon thinks it is paused, which leads to race conditions and clobbering.
   - **Ordering impact:** Moves to Step 2.

3. **LABEL:** `Purge Stale Sidecars Immediately`
   - **Correction:** Make the sidecar purge (A5) run automatically as a post-run cleanup hook in [planner/staging.py:86-92](file:///home/xnihil0zer0/JanusMaskJR/harness/planner/staging.py#L86-L92) whenever a task fails or aborts, clearing `state/sessions/*_<id>_*` and stale `.patches.json`.
   - **Rationale:** Prevents "retry poison" where subsequent attempts of a failed task are forced to reuse stale, corrupted patch metadata from prior runs.
   - **Ordering impact:** Moves to Step 3.

4. **LABEL:** `Standing Deadlock Breaker Passes`
   - **Correction:** Promote `brief-dep-deadlock-breaker` and `strip_unresolvable_deps` to default-on standing planner passes in [plan_normalizer.py:1013-1047](file:///home/xnihil0zer0/JanusMaskJR/harness/plan_normalizer.py#L1013-L1047).
   - **Rationale:** Prevents the planner from entering infinite planning loops (which caused 4 slugs to hit the 5/5 retry cap) due to unresolvable or hallucinated slug dependencies in briefs.
   - **Ordering impact:** Moves to Step 4.

5. **LABEL:** `Restore Blue Green Handoff`
   - **Correction:** Re-enable and generalize the staging worktree and process handover for all edits, and connect the shadow->enforce canary rollout ([hooks_equivalence.py](file:///home/xnihil0zer0/JanusMaskJR/harness/hooks_equivalence.py)) to trigger automatic rollbacks on integration smoke failure.
   - **Rationale:** Ensures that a faulty code promotion automatically rolls back using the existing `apply_rollback` primitive instead of leaving the repository in a wedged state.
   - **Ordering impact:** Moves to Step 5.

6. **LABEL:** `Enable Self Heal Auto Promote`
   - **Correction:** Turn `selfheal_auto_promote` ON in [selfheal.py:25-39](file:///home/xnihil0zer0/JanusMaskJR/harness/selfheal.py#L25-L39) but gate it on passing the local smoke tests and NobleGreedv2 contract checks.
   - **Rationale:** Closes the autonomous self-healing loop so the system can fix itself when transient errors occur, without needing human intervention.
   - **Ordering impact:** Moves to Step 6.

## PROPOSED ORDERED PLAN

1. **`Auto Clear Stale Git Locks`** (Prevents daemon loop starvation and stuck scheduling)
2. **`Unify Pause Primitive Channels`** (Prevents split-brain worker races and clobbers)
3. **`Purge Stale Sidecars Immediately`** (Prevents retry poisoning from previous failures)
4. **`Standing Deadlock Breaker Passes`** (Prevents planner dependency deadlocks)
5. **`Restore Blue Green Handoff`** (Enables safe hot-swaps and rollbacks for the self-building harness)
6. **`Enable Self Heal Auto Promote`** (Activates autonomous self-healing)
