# Adversary 2 — Bootstrapping / Chicken-and-Egg Review

**Lens:** The plan fixes the factory *using* the factory, but the factory is paused,
double-locked, and its planner suite is RED at HEAD. Every ordering assumption that
silently depends on a working pipeline is a defect. I verified the live state rather
than trusting the report.

## Live state I verified (the report is stale on several points)

- **Double pause + stale lock, not a clean pause.** `state/control/autowork/pause`
  EXISTS *and* `state/control/orchestrator.flag == "paused"` (both channels active).
  The daemon (PID 3684794) is alive but wedged. `git_commit.lock` holds PID
  **3731840 which is DEAD**. The report's §5 never says "clear these first."
- **Planner suite is RED at HEAD.** `tests/planner/test_blind_draft_wiring_oracle_synthesis.py`
  has **2 failures** — a committed RED oracle (`66f4df2 Add RED oracle: blind_draft
  synthesizes wiring-oracle token...`) whose **implementation was never landed**.
  Working tree is clean on tracked prod, so this is a *stranded TDD oracle baked into
  HEAD*. The plan's keystone caveat — "a new normalize pass can break sibling passes,
  run the WHOLE planner suite" — assumes a green baseline that does not exist.
- **A2 is ALREADY DONE.** `_strip_stray_mutation_targets` is present and wired into
  `normalize_plan` (plan_normalizer.py:1046). Memory/`02` still list it "in flight."
- **A1 is mostly done.** `_inject_oracle_sources` is real and in the pass chain (:285).
  A1/A3/A4 are partial-landed, not greenfield — the plan presents Tier 1 as net-new.
- **Tier 0 keystone does NOT exist.** No `block_manifest`/`daemon edit` verb; the
  daemon has **no subcommand parser at all** (only `--once/--dry-run/--config`).
  Tier-0b substrate DOES exist (`create_staging_worktree`:1453,
  `merge_staging_to_parent`:1668, `perform_process_handover`, `apply_rollback`).
- **`orchestrator_worker` does NOT honor pause/full_stop.** So a hand-drive through
  `orchestrator_worker --task-id` runs even while the daemon is paused — this is the
  only currently-working bootstrap channel. `drive_leaf.py` is the working hand-tool.
- 41 blocked tasks (not 18); 23 `.exhausted` (retry budget terminal), 86 selfheal_skip.

---

## CORRECTIONS

1. **LABEL: Out-of-band unwedge is Step 0**
   - **Correction:** Before ANY pipeline step, hand-clear the wedge out-of-band:
     delete the stale `git_commit.lock` (PID 3731840 confirmed dead), unify to ONE
     pause channel (B6 done first, manually), and drain/triage the 41 blocked tasks.
     None of this can be pipeline-built because the pipeline is what's wedged.
   - **Rationale:** Steps 1–6 all assume the daemon can stage/commit. With a stale
     commit-lock and contradictory pause flags, the very first integrate deadlocks or
     blind-clobbers a worker (the B6 hazard). This is pure operator surgery — sanctioned
     because it's state files, not production code.
   - **Ordering impact:** New Step 0, ahead of everything. Unblocks the entire chain.

2. **LABEL: Green the planner baseline first**
   - **Correction:** The 2 failing `test_blind_draft_wiring_oracle_synthesis` cases are
     a committed RED oracle with no impl. Land that impl (via `drive_leaf.py` hand-drive)
     BEFORE adding any Tier-1 normalize pass — OR explicitly quarantine/xfail it and
     record the baseline. Either way, establish a known-green planner suite as the gate.
   - **Rationale:** The plan's own Step-1 caveat is "run the whole planner suite" to
     catch a new pass breaking siblings. With 2 pre-existing reds you cannot tell *your*
     breakage from the baseline — the safety gate is blind. You can't verify the fixes
     to the verifier while the verifier is red.
   - **Ordering impact:** Step 0.5, immediately after unwedge, before Tier 1 (Step 1).

3. **LABEL: Reconcile "done" before building**
   - **Correction:** A2 is fully landed; A1/A3/A4 are partially landed in `normalize_plan`.
     Re-audit each Tier-1 item against HEAD (grep the pass list) and rewrite the plan to
     only build the *missing delta*, not re-author landed passes.
   - **Rationale:** Bootstrap budget is ~14–21 leaves/day. Re-dispatching already-landed
     passes risks the seesaw hazard (a new pass breaking the sibling that already does the
     job) and wastes the scarce hand-drive capacity that Step 0 just freed up.
   - **Ordering impact:** Folds into Step 1; shrinks Tier 1 to its real remainder.

4. **LABEL: Bootstrap via orchestrator_worker, daemon stays paused**
   - **Correction:** Make explicit that Tier-1/Tier-0 fixes are landed by hand-driving
     `drive_leaf.py` → `orchestrator_worker --task-id` **with the daemon paused**, because
     `orchestrator_worker` does NOT check the pause flag. Do NOT unpause the daemon to
     "let it build its own fixes" until Tier 1 is green.
   - **Rationale:** This is the honest answer to "can you pipeline-build a fix for the
     paused pipeline?" — yes, but only through the worker entrypoint that ignores pause,
     not through the daemon loop. Unpausing early re-arms the dispatch loop against
     blocked-task time-bombs (23 `.exhausted`) and clobber-bombs before the guards exist.
   - **Ordering impact:** Defines the *mechanism* for Steps 1–3; the daemon unpause moves
     to AFTER Tier 1 + B5/B7 land.

5. **LABEL: drive_leaf is the bootstrap, not obsolete-yet**
   - **Correction:** The plan says A1 "obsoletes `drive_leaf.py`." Invert the dependency:
     `drive_leaf.py` is the ONLY working way to land A1 (and A3/A5). Keep it as the
     sanctioned bootstrap tool until A1/A3/A5 are green via it, THEN retire it. Do not
     plan to delete the ladder you're standing on.
   - **Rationale:** Classic step-N-needs-step-N+3: A1 is supposed to remove the manual
     oracle-injection that `drive_leaf.py` does, but you need `drive_leaf.py` to inject
     the oracle for the leaf that builds A1.
   - **Ordering impact:** `drive_leaf.py` survives through Step 1; retired only at end of
     Step 1.

6. **LABEL: Tier 0 keystone is greenfield, sequence it late**
   - **Correction:** Verbatim block-manifest apply + `daemon edit` verb do not exist and
     the daemon has no subcommand parser — this is multi-leaf net-new code (apply-mode in
     `orchestrator_worker` + `git_integration`, a new CLI surface). Treat Tier 0 as a
     *consumer* of green Tier 1 + Tier 0b substrate, never a prerequisite. Do not let any
     earlier step assume `daemon edit` exists.
   - **Rationale:** The plan calls UEP "the foundational capability the rest assumes" yet
     also "assembled from Tier-1 pieces." Only the second is true. Building it first would
     require hand-editing production harness to create the tool that's supposed to replace
     hand-editing — the purest chicken-and-egg.
   - **Ordering impact:** Tier 0 stays at Step 3 (after Tier 1 green + Tier 0b restored),
     exactly where §5 puts it — but the plan must stop describing it as foundational/first.

7. **LABEL: Don't unpause onto live blocked-task bombs**
   - **Correction:** Land B7 (auto-clear stale `git_commit.lock`) and B5 (reject
     clobber-bombs at plan time) BEFORE the daemon is unpaused for autonomous running.
     Triage the 23 `.exhausted` + 41 blocked tasks (the clobber-bomb time-bombs) out of
     `state/tasks/blocked/` first.
   - **Rationale:** MEMORY warns "blocked clobber = TIME BOMB (`_retry_blocked_tasks`
     budget 3)." Unpausing re-runs `_retry_blocked_tasks` against a backlog full of
     vacuous-vcmd clobber-bombs before the B5 guard that catches them is in place.
   - **Ordering impact:** B5 + B7 promote ahead of the general Tier-2 batch; gate the
     daemon unpause behind them.

8. **LABEL: NGv2 work needs its own green baseline too**
   - **Correction:** Before Tier 3 (C1–C3), confirm the NGv2 `python -m ngv2.workers.<phase>`
     smoke + workers' oracle suite is green standalone. The plan gates Tier 3 *landings*
     behind an NGv2 regression run but never establishes the pre-fix baseline — and Lane 2
     shows self-heal already rewrites `ngv2/workers/*`.
   - **Rationale:** A regression run is only meaningful against a known-green reference. If
     NGv2's own suite is already red (it builds into a sibling repo via the wedged
     pipeline), every Tier-3 gate "fails regression" with no signal about cause.
   - **Ordering impact:** Add an NGv2-baseline check at the head of Step 5 (Tier 3).

---

## YOUR PROPOSED ORDERED PLAN

0. **Out-of-band unwedge (operator, state files only):** delete stale `git_commit.lock`
   (dead PID), unify the two pause channels (manually apply B6's single-channel decision),
   triage the 41 blocked / 23 `.exhausted` tasks out of the dispatch path. Daemon STAYS
   paused.
0.5. **Green the planner baseline:** land the stranded `blind_draft` wiring-oracle impl
   (via `drive_leaf.py` hand-drive) or xfail+record it, so the planner suite is a trusted
   gate. Re-audit Tier 1 vs HEAD — A2 done, A1/A3/A4 partial — and reduce Tier 1 to its
   real remainder.
1. **Land the Tier-1 remainder** through `drive_leaf.py` → `orchestrator_worker` with the
   daemon paused (worker ignores pause). RED oracle first; run the now-green whole planner
   suite after each pass. Retire `drive_leaf.py` only once A1/A3/A5 are green via it.
2. **Restore Tier 0b substrate + un-neuter the 4 OFF flags**, each behind its oracle,
   same hand-drive channel (still paused). Land B5 + B7 here too.
3. **Build Tier 0 (verbatim block-manifest apply + `daemon edit` verb)** as a consumer of
   green Tier 1 + Tier 0b — RED-oracle-first, hand-driven, inside the green staging slot.
4. **Now unpause the daemon** (backlog triaged, B5/B7 in place) and run the `daemon edit`
   verb + B1/B2 self-hosted from here on.
5. **Establish NGv2 standalone-green baseline, then Tier 3 (C1–C3)** each gated behind the
   NGv2 regression run.
6. **Tier 2 remainder + Tier 4** in parallel as policies/guardrails; D1 becomes the router
   into `daemon edit`.
