# Adversarial Review: Critical Path & Throughput (Sub-Agent 1)

This review identifies the minimum ordered set of changes required to get the JanusMask factory scheduling and successfully dispatching leaves again. It focuses on removing active scheduling blockers immediately and delaying non-operational/administrative overhead.

## Discrete Corrections

1. **LABEL:** `Auto Clear Stale Git Locks`
   - **Correction:** Add a lock-clearing check at the beginning of the daemon iteration in [autowork_daemon.py:1890-2050](file:///home/xnihil0zer0/JanusMaskJR/harness/autowork_daemon.py#L1890-L2050) and modify the inactivity watchdog in [autowork_daemon.py:2846-2931](file:///home/xnihil0zer0/JanusMaskJR/harness/autowork_daemon.py#L2846-L2931) to automatically remove `git_commit.lock` if its owning PID is dead or if it has been idle for more than 10 minutes.
   - **Rationale:** Stale git commit locks are the primary cause of `daemon_inactivity_stuck` (30 events), which repeatedly wedges the scheduling loop. Automatically clearing them restores scheduling throughput without manual daemon restarts.
   - **Ordering impact:** Moves to Step 1 (immediate action).

2. **LABEL:** `Purge Stale Sidecars Immediately`
   - **Correction:** Execute the stale sidecar purge and task budget reset (A5/B2) inside [planner/staging.py:47-146](file:///home/xnihil0zer0/JanusMaskJR/harness/planner/staging.py#L47-L146) immediately upon staging or task re-dispatch. Clear `state/sessions/*_<id>_*` and `state/tasks/<id>.json`.
   - **Rationale:** Stale `.patches.json` and `.files.json` sidecar files from previous failed runs poison subsequent attempts. Purging them immediately is required to unwedge the 18 blocked tasks without manual intervention.
   - **Ordering impact:** Moves to Step 2, preceding all planner/worker edits.

3. **LABEL:** `Bootstrap Verbatim Block Apply`
   - **Correction:** Implement the verbatim block-manifest apply mode (Tier 0) in [orchestrator_worker.py](file:///home/xnihil0zer0/JanusMaskJR/harness/orchestrator_worker.py) and [git_integration.py](file:///home/xnihil0zer0/JanusMaskJR/harness/git_integration.py) as a direct-apply mechanism before building other features.
   - **Rationale:** The current AST-merge path is broken (resulting in `incomplete_ast` and patch failures). Establishing a reliable block-manifest direct-apply path ensures that subsequent pipeline modifications can actually be applied to the harness itself without failing.
   - **Ordering impact:** Moves to Step 3, before Tier 1 passes.

4. **LABEL:** `Inject Oracle Source Stage`
   - **Correction:** Automatically resolve the leaf's test file under `tests/` and embed its raw source code under a fixed header in the worker's `implementation_notes` inside [planner/staging.py:47-146](file:///home/xnihil0zer0/JanusMaskJR/harness/planner/staging.py#L47-L146).
   - **Rationale:** Directly injects the test specification contract into the worker prompt. This drastically reduces the worker failure rate, making task dispatching successful on the first attempt.
   - **Ordering impact:** Moves to Step 4, alongside upgrading verification commands.

5. **LABEL:** `Thread External Working Dir`
   - **Correction:** Complete end-to-end threading of the `working_dir` parameter from plan validation through staging to the worker environment in [autowork_daemon.py](file:///home/xnihil0zer0/JanusMaskJR/harness/autowork_daemon.py) and [planner/staging.py](file:///home/xnihil0zer0/JanusMaskJR/harness/planner/staging.py).
   - **Rationale:** Enables tasks targeting the sibling repository `/home/xnihil0zer0/NobleGreedv2` to be resolved and executed through the pipeline without manual path patching.
   - **Ordering impact:** Moves to Step 5, before enabling self-healing or UEP for external roots.

6. **LABEL:** `Enable Self Heal Auto Promote`
   - **Correction:** Flip `selfheal_auto_promote` to ON in [selfheal.py:25-39](file:///home/xnihil0zer0/JanusMaskJR/harness/selfheal.py#L25-L39) to allow the self-heal loop to apply diagnoses automatically.
   - **Rationale:** The self-heal loop can currently only diagnose but not apply. Activating this flag closes the loop for autonomous recovery.
   - **Ordering impact:** Moves to Step 6, after the edit/apply path is proven stable.

7. **LABEL:** `Defer Tier Four Guardrails`
   - **Correction:** Defer all Tier 4 governance and administrative tasks (D1-D4) including pre-commit guards, verification passes, and allowlist scoping commands.
   - **Rationale:** These tasks add complexity and protect the code from manual edits but do not restore build throughput. They are non-critical for un-wedging the factory.
   - **Ordering impact:** Defer to the post-operational phase, completely removing them from the active restore sequence.

## PROPOSED ORDERED PLAN

1. **`Auto Clear Stale Git Locks`** (Unblocks daemon loop immediately)
2. **`Purge Stale Sidecars Immediately`** (Clears state corruption and resets budgets for wedged tasks)
3. **`Bootstrap Verbatim Block Apply`** (Establishes the reliable edit/synthesis channel)
4. **`Inject Oracle Source Stage`** (Increases worker correctness and success rate)
5. **`Thread External Working Dir`** (Enables cross-repo builds to NobleGreedv2)
6. **`Enable Self Heal Auto Promote`** (Activates automated self-healing for the operational loop)
