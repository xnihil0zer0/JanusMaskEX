# Adversarial Review: Cut & Compound (Sub-Agent 4)

This review acts as the editor, identifying the minimal compounding set of changes. It cuts or defers all one-off, non-compounding, or purely administrative tasks, and evaluates whether the big-ticket Universal Edit Path (UEP) and blue-green staging/swap are worth the cost.

## Discrete Corrections

1. **LABEL:** `Bootstrap Verbatim Block Apply`
   - **Correction:** Implement the verbatim block-manifest apply mode (Tier 0) immediately. Do not attempt to fix the fragile AST-merge path first.
   - **Rationale:** The AST-merge path is structurally fragile (truncation, class method issues) and requires constant one-off patching. Verbatim block-manifest apply is a bulletproof edit channel that handles multi-file, non-Python, and large file edits, making it the core compounding capability that is highly worth its cost.
   - **Ordering impact:** Retained as the central capability in Step 2.

2. **LABEL:** `Restore Blue Green Handoff`
   - **Correction:** Un-neuter the existing blue-green staging-worktree handoff and process handover. Do not write a third staging/apply mechanism.
   - **Rationale:** Reusing the existing `create_staging_worktree` and `perform_process_handover` primitives avoids accreting new architecture and keeps the code footprint minimal.
   - **Ordering impact:** Moves to Step 3.

3. **LABEL:** `Defer Tier Four Guardrails`
   - **Correction:** Cut and defer the entirety of Tier 4 (D1-D4: pre-commit guards, verification passes, and allowlist scoping commands).
   - **Rationale:** These tasks are administrative guardrails that do not contribute to the pipeline's compounding build capability. They add complexity and should be deferred until the loop is stable.
   - **Ordering impact:** Removed from the active sequence.

4. **LABEL:** `Purge Stale Sidecars Immediately`
   - **Correction:** Retain and prioritize A5 (purging stale sidecars and resetting retry budgets) but implement it as a simple inline cleanup function in [planner/staging.py:47-146](file:///home/xnihil0zer0/JanusMaskJR/harness/planner/staging.py#L47-L146).
   - **Rationale:** This is the highest-leverage, lowest-code fix to prevent tasks from remaining permanently wedged on retry.
   - **Ordering impact:** Moves to Step 1.

5. **LABEL:** `Inject Oracle Source Stage`
   - **Correction:** Automatically embed the test oracle source into the worker prompt at stage time in [planner/staging.py](file:///home/xnihil0zer0/JanusMaskJR/harness/planner/staging.py).
   - **Rationale:** This single change eliminates the need for the complex manual-drive script (`drive_leaf.py`) and manual intervention during worker execution.
   - **Ordering impact:** Moves to Step 4.

6. **LABEL:** `Thread External Working Dir`
   - **Correction:** Implement C1 (`working_dir` threading) in the worker environment and git integration.
   - **Rationale:** Since the factory must build into the sibling repo (`NobleGreedv2`), end-to-end `working_dir` threading is the minimum required capability to make cross-repo operations fully autonomous.
   - **Ordering impact:** Moves to Step 5.

7. **LABEL:** `Enable Self Heal Auto Promote`
   - **Correction:** Enable `selfheal_auto_promote` to automate recovery of failed leaves.
   - **Rationale:** Without auto-promotion, the self-heal loop is a dead end that relies on a human supervisor to apply fixes, preventing true compounding.
   - **Ordering impact:** Moves to Step 6.

## PROPOSED ORDERED PLAN

1. **`Purge Stale Sidecars Immediately`** (Minimal state cleanup)
2. **`Bootstrap Verbatim Block Apply`** (Minimal bulletproof edit primitive)
3. **`Restore Blue Green Handoff`** (Reuses existing hot-swap substrate)
4. **`Inject Oracle Source Stage`** (Eliminates custom driver script)
5. **`Thread External Working Dir`** (Enables NobleGreedv2 target resolution)
6. **`Enable Self Heal Auto Promote`** (Closes the compounding build-and-heal loop)
