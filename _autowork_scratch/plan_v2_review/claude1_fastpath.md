# Adversary 1 — Fastest Path to Factory-Operational

Lens: critical path to **first-green-leaf**, then keep-it-green. I read the plan and
all four lanes, then verified the LIVE wedge state. The §5 ordering is optimized for
*total leverage* (build UEP, the keystone) but is **mis-ordered for time-to-operational**:
it front-loads planner normalizers that do not unblock the actual stuck tasks, and
buries the two things that are literally blocking the daemon right now (a dead-PID
lock + the AST-merge failure mode) at steps 3 and never.

## Live-state evidence (verified, not from memory)

- `state/control/autowork/git_commit.lock` holds **PID 3731840 which is DEAD**. The
  live daemon (PID 3684794) is alive but cannot commit. This is B7, and it is the #1
  self-heal signature (`daemon_inactivity_stuck` ×30). **Nothing dispatches until this
  is cleared.** §5 puts B7 in step 6 ("in parallel").
- TWO pause channels are both set: `state/control/autowork/pause` exists AND
  `orchestrator.flag=="paused"` (B6 hazard is live right now). Resume requires
  clearing both — the contradiction the plan flags but sequences last.
- `state/tasks/blocked/`: 41 entries. **23 `.exhausted`** (retry budget zero — these
  do NOT re-dispatch on resume, they need A5 budget-reset). Dominant `.retry.json`
  outcomes: `synthesis_or_ast_failed` and `auto_commit_failed` — the AST-merge family.
- The FRESHEST blocker, `integration_smoke_accept_gate.json` (Jun 14 22:07), has a
  **well-formed objective and a real `python3 -m pytest` vcmd** — it failed
  `synthesis_or_ast_failed`, NOT empty-objective/weak-vcmd. So A1/A2/A3 (the planner
  normalizers §5 lands FIRST) would not have unblocked it. The block-manifest apply
  core (UEP primitive) is what it needs — buried at §5 step 3.
- Queue is otherwise empty: 0 top-level tasks, 0 briefs, 0 plans, 0 running. So
  "operational" = (a) unwedge the daemon, (b) re-admit the blocked backlog with reset
  budgets, (c) make re-dispatched leaves actually merge.

---

## DISCRETE CORRECTIONS

1. **LABEL: Dead-lock clear is step zero**
   **Correction:** Before anything else, clear the stale `git_commit.lock` (dead PID
   3731840) and land B7 (auto-clear lock when owning PID dead + idle) as the very first
   harness change.
   **Rationale:** The live daemon physically cannot commit a leaf while this lock is
   held; it is the most-fired wedge (30 events). No planner fix matters until commits
   can happen. This is a one-line `os.kill(pid,0)`-check delete — minutes, not an epic.
   **Ordering impact:** Moves B7 from §5 step 6 → step 1. Displaces nothing valuable;
   it gates everything.

2. **LABEL: Unify-and-clear the pause primitive next**
   **Correction:** Land B6 (single authoritative pause channel = pause-file existence
   per daemon.py:1773) and clear BOTH live pause signals as the second action.
   **Rationale:** Resume is meaningless if a second stale channel re-pauses, and the
   dual-channel contradiction is the documented blind-clobber hazard (17 interventions).
   Doing it now also means the very first re-dispatch is safe.
   **Ordering impact:** Moves B6 from §5 step 6 → step 2.

3. **LABEL: AST-merge core precedes planner passes**
   **Correction:** Build the UEP **verbatim block-manifest apply primitive** (Tier 0
   core) and B3 (auto-retry `auto_commit_failed` by class) BEFORE the A1–A4 planner
   normalizers. The block-manifest apply is the root-cause fix for both
   `synthesis_or_ast_failed` and `auto_commit_failed`.
   **Rationale:** Verified: the backlog is dominated by AST/commit-merge failures, not
   empty-objective/weak-vcmd. A1–A3 fix planner OUTPUT defects; the stuck tasks fail at
   APPLY. First-green-leaf comes from fixing apply, not from re-shaping plans the
   pipeline already accepted. The plan even says UEP "retires the AST-fragility blocker
   family" — that is the critical path, so it cannot be step 3 behind two non-blocking tiers.
   **Ordering impact:** Promote the block-manifest apply-mode + B3 from §5 step 3 → step 3
   (immediately after unwedge), demote A1/A4 to follow it.

4. **LABEL: Budget-reset to re-admit exhausted backlog**
   **Correction:** Land A5 (terminal-outcome sidecar purge + retry-budget reset on
   dispatch) and run it across the **23 `.exhausted` blocked tasks** so they re-enter the
   dispatch loop on resume.
   **Rationale:** 23 of 41 blocked tasks have ZERO retry budget — resuming the daemon
   will NOT pick them up; they sit dead. A5 is the only thing that converts the existing
   backlog into dispatchable work, which is the fastest source of green leaves (no new
   planning needed). Without it, "operational" yields an empty queue.
   **Ordering impact:** A5 moves up to step 4, paired with the apply fix (so re-admitted
   tasks hit the now-working apply path). It is genuinely high-leverage and belongs in
   Tier 1, but it is wasted if dispatched before #3.

5. **LABEL: Then the recurring planner cluster (A1–A4)**
   **Correction:** Land A1 (oracle-source injection), A2 (mutation_target module-only),
   A3 (weak-vcmd upgrade), A4 (multifile split) as the standing normalize passes —
   AFTER the backlog is unwedged and merging.
   **Rationale:** These are real and prevent the *next* epic's defects, but they are
   keep-it-operational, not restore-to-operational. None of them unblock a currently
   dead-PID-locked daemon or an AST-merge failure. Front-loading them (current §5 step 1)
   delays first-green-leaf with no payoff against today's backlog. Note A2's own evidence:
   `strip_stray_muttarget` is already an active allowlist entry — partly handled already.
   **Ordering impact:** A1–A4 move from §5 step 1 → step 5. They keep their normalize-pass
   seam (S1) and the "run the whole planner suite" caveat.

6. **LABEL: Defer Tier 0b substrate restoration**
   **Correction:** Do NOT block restore on un-neutering the blue-green handoff,
   shadow→enforce canary, `agy_pool`, or `antigravity_mode`. Build the apply primitive
   directly; restore/unify the staging-worktree substrate as a follow-on hardening pass.
   **Rationale:** §5 step 2 makes "restore the handoff substrate" a prerequisite for UEP.
   But the verbatim apply primitive (uniqueness-checked literal replacement) does not
   *require* the worktree-swap/os.execv machinery to produce a green leaf — it requires a
   safe apply + the existing gate/commit path (which works once the lock is cleared).
   Coupling restore to a multi-component substrate-unification is the single biggest
   schedule risk in the plan. `archive_spent_briefs` (A6) is a trivial flag flip and can
   ride along; the rest is hardening.
   **Ordering impact:** Tier 0b substrate work moves from §5 step 2 → step 7 (post-first-green).
   Only the A6 flag flip stays early.

7. **LABEL: Defer the daemon-edit verb (B1/B2/UEP verb)**
   **Correction:** Ship the apply-mode as a worker capability the daemon uses
   automatically; defer the operator-facing `daemon edit` / `daemon drive` verbs (B1/B2)
   until after first-green-leaf.
   **Rationale:** The verbs absorb *operator* manual drives (a keep-operational efficiency
   win), but the GOAL is the daemon dispatching successful leaves autonomously — that needs
   the apply primitive in the worker path, not a new CLI verb. The verb is downstream of
   the primitive and not on the restore critical path.
   **Ordering impact:** B1/B2/verb move from §5 step 4 → step 8.

8. **LABEL: NGv2-boundary (C1–C3) stays late but gate-checked**
   **Correction:** Keep Tier 3 after the JM-internal restore, but explicitly confirm that
   the current blocked backlog's first-green targets are JM-internal (they are:
   `integration_smoke_*` touch `harness/orchestrator.py`), so C1 is NOT on the
   first-green critical path.
   **Rationale:** Lane 4 verified zero runtime `ngv2.*` import — JM-internal restore can
   reach green without C1. C1 only gates editing files UNDER NobleGreedv2. Several blocked
   NGv2 leaves exist (`ngv2-poc-dotted-impl`, etc.) but they are not required for
   "daemon dispatching successful leaves again." Confirms §5 is right to keep C1–C3 late;
   the correction is to stop treating C1 as a near-term dependency.
   **Ordering impact:** Confirms C1–C3 at step 9 (no move), but removes any implied
   coupling to the restore path.

9. **LABEL: D2 verify-against-HEAD before declaring green**
   **Correction:** Land D2 (verify-claims-against-HEAD oracle re-run) early enough to use
   it as the acceptance check on the FIRST restored leaf, not as a late guardrail.
   **Rationale:** Memory repeatedly warns "re-exec no_diff lies — verify HEAD." When
   restoring a wedged factory the highest risk is a false "green" that re-wedges. Making
   D2 the gate on first-green-leaf is cheap (it's a standalone script) and protects the
   restore itself.
   **Ordering impact:** D2 moves from §5 step 6 → step 6 (right after the planner cluster,
   as the restore-validation button).

---

## YOUR PROPOSED ORDERED PLAN

1. **Clear the stale `git_commit.lock` + land B7** (auto-clear dead-PID lock). Unwedge
   the live daemon's commit path. *(blocks everything)*
2. **Land B6 + clear both pause channels** (unify pause to pause-file existence; clear
   `pause` file and `orchestrator.flag`). Make resume safe and singular.
3. **Build UEP verbatim block-manifest apply primitive + B3** (auto-retry
   `auto_commit_failed`/`synthesis_or_ast_failed` by class). Fix the actual APPLY-stage
   failure that dominates the backlog — RED-oracle first, routed through the pipeline.
4. **Land A5 (sidecar purge + retry-budget reset) and re-admit the 23 `.exhausted`
   blocked tasks.** Converts the existing backlog into dispatchable work → fastest
   green leaves. ▶ **Resume daemon here — expect first-green-leaf.**
5. **Land A1–A4** (oracle-source injection, mutation_target module-only, weak-vcmd
   upgrade, multifile split) as standing normalize passes + flip `archive_spent_briefs`
   (A6) + auto-push (A7). Keep-operational; run the whole planner suite.
6. **Land D2** (verify-claims-against-HEAD) and use it to validate steps 4–5 are
   genuinely green, not no-diff lies.
7. **Restore/unify Tier 0b substrate** (blue-green handoff de-clip, shadow→enforce
   canary, `agy_pool`, review `antigravity_mode`) — hardening + atomic-rollback, now
   that the factory is already producing green leaves.
8. **Ship the `daemon edit`/`daemon drive` verbs (B1/B2)** over the now-working
   apply-mode + normalizers. Absorbs operator manual drives.
9. **Tier 3 (C1–C3) NGv2-boundary**, each behind a NobleGreedv2 regression run; +
   remaining Tier 2/4 guardrails (B4, B5, B8, D1, D3, D4).

**Net change vs §5:** the restore critical path is steps 1–4 (unwedge → fix apply →
re-admit backlog), reaching first-green-leaf BEFORE the planner-normalizer tier and
WITHOUT the Tier-0b substrate unification that the current plan makes a prerequisite.
