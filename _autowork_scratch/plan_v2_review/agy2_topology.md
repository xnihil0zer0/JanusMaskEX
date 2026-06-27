# Adversarial Review: Dependency Topology (Sub-Agent 2)

This review analyzes the topological dependencies of the intervention plan. It identifies critical circular dependencies and bootstrapping traps where steps require capabilities that are built later in the plan.

## Discrete Corrections

1. **LABEL:** `Bootstrap Verbatim Block Apply`
   - **Correction:** Implement the verbatim block-manifest apply mode (Tier 0) in [orchestrator_worker.py](file:///home/xnihil0zer0/JanusMaskJR/harness/orchestrator_worker.py) and [git_integration.py](file:///home/xnihil0zer0/JanusMaskJR/harness/git_integration.py) *before* trying to land the Tier 1 planner normalizers (A1-A7) through the pipeline.
   - **Rationale:** The current AST-merge path is broken, resulting in `incomplete_ast` errors and clobbered code. Landing A1-A7 via the pipeline is topologically impossible until a reliable verbatim-apply path is bootstrapped.
   - **Ordering impact:** Moves to Step 2, displacing Tier 1 to a later stage.

2. **LABEL:** `Restore Blue Green Handoff`
   - **Correction:** Restore and generalize the blue-green staging-worktree handoff ([git_integration.py:1453](file:///home/xnihil0zer0/JanusMaskJR/harness/git_integration.py#L1453), [git_integration.py:1668](file:///home/xnihil0zer0/JanusMaskJR/harness/git_integration.py#L1668)) and process handover ([orchestrator.py:2005](file:///home/xnihil0zer0/JanusMaskJR/harness/orchestrator.py#L2005)) *before* landing any self-modifying harness changes.
   - **Rationale:** The running harness cannot safely edit its own files without the staging worktree and hot-swap process handover. Un-neutering this substrate is a strict topological dependency for landing A1-A7 and Tier 2/3 changes.
   - **Ordering impact:** Moves to Step 3, immediately following the verbatim-apply bootstrap.

3. **LABEL:** `Thread External Working Dir`
   - **Correction:** Implement end-to-end `working_dir` threading (C1) in [autowork_daemon.py](file:///home/xnihil0zer0/JanusMaskJR/harness/autowork_daemon.py) and [planner/staging.py](file:///home/xnihil0zer0/JanusMaskJR/harness/planner/staging.py) *before* pointing UEP (Tier 0) or self-healing promotion (C3) at the external `/home/xnihil0zer0/NobleGreedv2` target.
   - **Rationale:** Verbatim-apply and self-healing cannot resolve target file paths or execute verification test suites for NobleGreedv2 without `working_dir` properly threaded to the worker environment and git integration.
   - **Ordering impact:** Moves to Step 4, preceding Tier 3 and UEP external deployments.

4. **LABEL:** `Purge Stale Sidecars Immediately`
   - **Correction:** Implement the sidecar purge and retry budget reset (A5) in [planner/staging.py:86-92](file:///home/xnihil0zer0/JanusMaskJR/harness/planner/staging.py#L86-L92) *before* enabling the `daemon drive` (B1) or `daemon --reset-task` (B2) commands.
   - **Rationale:** The daemon drive and task reset verbs depend on the existence of a clean, programmatic method to purge stale `.patches.json`/`.files.json` and session state.
   - **Ordering impact:** Moves to Step 1, before any daemon interface modifications.

5. **LABEL:** `Inject Oracle Source Stage`
   - **Correction:** Implement A1 (inject committed oracle source into the worker prompt) *before* or concurrently with A3 (upgrading weak vcmds to pytest gates).
   - **Rationale:** A3 forces the worker to pass a strict pytest gate. Without the test oracle source injected into the prompt (A1), the worker lacks the specification needed to pass the gate, causing immediate task failures.
   - **Ordering impact:** Group A1 and A3 together in Step 5.

6. **LABEL:** `Enable Self Heal Auto Promote`
   - **Correction:** Enable `selfheal_auto_promote` in [selfheal.py:25-39](file:///home/xnihil0zer0/JanusMaskJR/harness/selfheal.py#L25-L39) *only after* landing B3 (auto-retry commit failures by class) and A5 (sidecar purge).
   - **Rationale:** Enabling auto-promotion before the self-heal loop has the capability to retry AST failures with alternative strategies will lead to repeated task failures, budget exhaustion, and pipeline re-wedges.
   - **Ordering impact:** Moves to Step 6, at the end of the core sequence.

## PROPOSED ORDERED PLAN

1. **`Purge Stale Sidecars Immediately`** (Clears state corruption before code changes begin)
2. **`Bootstrap Verbatim Block Apply`** (Resolves the pipeline edit dependency)
3. **`Restore Blue Green Handoff`** (Resolves self-update hot-swap dependency)
4. **`Thread External Working Dir`** (Resolves path resolution and testing dependencies for NobleGreedv2)
5. **`Inject Oracle Source Stage`** (Resolves worker prompt instruction dependency)
6. **`Enable Self Heal Auto Promote`** (Enables autonomous pipeline self-healing)
