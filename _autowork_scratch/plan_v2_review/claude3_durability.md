# Adversary 3 — Durability / Anti-Re-Wedge Review of the Intervention Plan

**Lens:** KEEP IT OPERATIONAL. Getting the factory green once is easy; the owner
wants it to STAY green. I attack any ordering that restores operation but leaves a
re-wedge primed.

## The core indictment of the plan's ordering

The plan's §5 sequencing is optimized for **first-green throughput**, not
**staying-green**. It front-loads the planner-defect normalizers (A1–A4) and the
UEP keystone (Tier 0/0b) — the things that make the *next* leaf land — and demotes
the actual wedge-recovery and re-wedge-prevention machinery (B6, B7, A5, the
self-heal-apply loop, the standing-pass guarantee) into "Tier 2 remainder in
parallel" at step 6. That is backwards for an operator whose factory is **PAUSED and
WEDGED right now**. The evidence is unambiguous about what *re-wedges*: the single
most-fired self-heal was `daemon_inactivity_stuck` ×30 (a stale-lock wedge re-kicked
30 times, never root-fixed), 86 tasks were permanently abandoned, and the SAME
blocker classes recur every epic because fixes shipped as one-offs, not standing
passes. None of those are throughput problems — they are durability problems, and
they sit late in the plan.

The plan even *names* its own anti-pattern (§2: "universal mechanisms clipped to one
arm... implemented twice and clipped both times") and then orders the durability
core after the throughput work — risking a third clip. The capabilities that PREVENT
re-wedging must land **before** we declare "operational", because "operational" with
a primed re-wedge is just a slower path back to PAUSED.

Below: the corrections that close re-wedge failure modes, ordered for durability.

---

1. **LABEL:** Stale-lock auto-reclaim in watchdog
   - **Correction:** The inactivity watchdog (`_check_inactivity_watchdog`,
     autowork_daemon.py:2913–2924) currently only *escalates* — writes
     `inactivity_escalated.json` and spawns a planner self-heal agent via
     `_escalate_inactivity` (daemon.py:2675). It never reclaims the stale
     `git_commit.lock`. The reclaim primitive **already exists** —
     `_acquire_commit_lock_or_reclaim` (daemon.py:2079) probes the owner PID via
     `os.kill(pid,0)` and reclaims a dead owner's lock — but it is wired **only** to
     the push path (daemon.py:2180). B7 must call this reclaim path from the watchdog
     when `is_stuck` and the lock owner PID is dead, BEFORE (or instead of) the
     re-kick escalation.
   - **Rationale:** Closes `daemon_inactivity_stuck` — the #1 recurring wedge (30
     fires, Lane 2 §2). Today the watchdog re-kicks a daemon that is wedged on a
     stale lock a dead worker left behind; the re-kick can't clear the lock, so it
     wedges again. This is THE canonical re-wedge loop in the evidence. The fix is
     not new architecture — it's connecting an existing reclaim function to the
     existing wedge detector. The plan's B7 says "auto-clear stale lock... instead of
     repeated re-kicks" but buries it at step 6; it must be near-first because it is
     the literal mechanism that keeps the factory down.
   - **Ordering impact:** Move to the **durability core, step 1** — before any
     throughput work. A factory that re-wedges on a stale lock can't run the rest of
     the plan unattended anyway.

2. **LABEL:** Unify the dual pause channel
   - **Correction:** B6 — collapse the two contradictory pause mechanisms to one
     authoritative channel. Today the daemon dispatch loop pauses on **existence** of
     `state/control/autowork/pause` (`_pause_flag_path`, daemon.py:288, checked at
     `_decide` daemon.py:1773 and resume telemetry daemon.py:2358), while the legacy
     `control_gate.check_pause` (control_gate.py:48) reads
     `state/control/orchestrator.flag` and only pauses on literal content `"paused"`
     (`DEFAULT_PAUSE_FLAG`, control_gate.py:23). Make `check_pause` delegate to the
     daemon's existence-check (or vice versa) so there is exactly one truth.
   - **Rationale:** Closes `daemon_pause_clobber_hazard` (Lane 3 #9, 17 interventions;
     L4 §1 correction). MEMORY records this firing repeatedly: "wrong pause → blind
     clobber workers". An operator who pauses the wrong channel believes the factory
     is stopped while it dispatches and clobbers live work — a re-wedge that also
     destroys in-flight progress. Because the *whole plan depends on the operator
     being able to safely pause* (every "do alongside" step, every gated landing
     assumes pause works), an ambiguous pause undermines every later step. It is also
     trivially low-risk (JM-internal, no NGv2 edge per L4 §4).
   - **Ordering impact:** **Durability core, step 2.** Must precede turning ON any of
     the OFF flags or the self-heal-apply loop — those make the daemon do MORE
     autonomously, which is exactly when a broken pause becomes catastrophic.

3. **LABEL:** Terminal sidecar purge + budget reset
   - **Correction:** A5/B2 — extend `worker_purge_stale_sidecars` so EVERY dispatch
     (not just operator-driven resets) purges `state/output/<id>.patches.json` /
     `.files.json`, `state/sessions/*_<id>_*`, and `state/tasks/<id>.json` on
     re-dispatch, and resets the retry budget for a fresh attempt. The retry logic
     (`_retry_blocked_tasks`, daemon.py:883; `effective_max` at 927) and the stale
     sidecar are independent re-wedge sources today.
   - **Rationale:** Closes `stale_sidecar_precedence` (Lane 3 #4) — the documented
     gotcha where a prior attempt's `.patches.json`/`.files.json` survives re-dispatch
     and takes precedence over fresh `.py`, so a re-tried task silently re-applies the
     OLD broken output and re-wedges identically. This is precisely why
     `drive_leaf.py` hand-codes a pre-clean block. Without it, the self-heal *retry*
     itself becomes a re-wedge: the loop "succeeds" against a stale sidecar and the
     task stays broken. Durability-critical because it's the failure mode that makes
     *recovery attempts themselves* fail silently.
   - **Ordering impact:** **Durability core, step 3.** Must land before the self-heal
     auto-apply (correction 5) — otherwise auto-apply retries against poisoned
     sidecars and you've automated the re-wedge.

4. **LABEL:** Standing-pass guarantee for fixes
   - **Correction:** Make A1–A4 + A2-mutation-target + B4-deadlock-breaker +
     B5-clobber-bomb land as permanent passes in the ONE idempotent
     `normalize_plan` pipeline (plan_normalizer.py:1013–1047, the 13-pass sequence
     per L4 §3.1) and as standing `validate_plan` rules — NOT as brief-nudges or
     `drive_leaf.py` overrides. Add a meta-guard/test asserting each recurring
     blocker class has a corresponding standing pass (a regression that fails if a
     known blocker class has no normalizer), so a future "fix" can't regress to a
     one-off.
   - **Rationale:** This is the plan's own §2 diagnosis #1 ("each defect... fixed by
     a one-off... then recurs on the next epic because the fix wasn't made a standing
     planner pass"). The re-wedge failure mode is *recurrence*: stray mutation_target,
     vacuous vcmd, clobber-bomb, AST truncation come back every epic. The plan lists
     these as A1–A4/B4/B5 but doesn't make "must be a standing pass" an enforced
     invariant — without the meta-guard, nothing prevents the *next* fix from being
     another nudge. The owner's standing rule (`fixes-are-permanent-and-reusable`) is
     the thing the system "keeps violating"; encode it as a test, not a hope.
   - **Ordering impact:** **Durability core, step 4** — the normalizer passes
     themselves are also the plan's step 1, so this is mostly an *enforcement* overlay
     on the same work: land the passes AND the meta-guard together. Whole planner
     suite must run (the documented "new pass breaks sibling passes" gotcha,
     L4 §3.1).

5. **LABEL:** Self-heal diagnose→apply, NGv2-gated
   - **Correction:** Turn `selfheal_auto_promote` ON (config.yaml:63, currently
     `false`; `_selfheal_auto_promote_enabled` selfheal.py:25) AND add the
     failure-class auto-retry rules (B3: class-method edit / symbol-add /
     large-symbol-truncation → whole-file/R-anchored strategy). Gate NGv2-touching
     heals behind the §4 contract regression (self-heal frequently rewrites
     `ngv2/workers/*`, `session_db.py` per L2 §2). The provenance + HMAC validation
     (`_selfheal_provenance_valid`) and eligibility already exist — flipping the flag
     closes the loop.
   - **Rationale:** Closes the "loop catches the easy half and punts the rest"
     failure (Lane 2: 86 `selfheal_skip` abandonments + 39 `auto_commit_failed` that
     diagnosed but never applied). A diagnose-only self-heal is, by construction, a
     re-wedge generator: it identifies the fix, writes a brief, and STOPS — requiring
     a human, which is the wedge. The whole point of "stay operational unattended" is
     that the heal applies. The plan does include this (Tier 0b un-neuter, C3) but
     frames it as "do alongside Tier 1" and tucks it into the NGv2-boundary tier —
     under-weighting that diagnose-only IS the wedge. **Dependency:** requires
     correction 3 (sidecar purge) first, or auto-apply retries against stale output.
   - **Ordering impact:** **Durability core, step 5** — after sidecar purge (3) and
     pause unification (2), because auto-apply is the highest-autonomy change and must
     not run until safe-pause and clean-retry are guaranteed.

6. **LABEL:** Re-neuter guard for clipped mechanisms
   - **Correction:** When Tier 0b restores the blue-green handoff
     (`create_staging_worktree` gi.py:1453, `merge_staging_to_parent` gi.py:1668,
     `perform_process_handover` orch.py:2005) and the shadow→enforce canary
     (`hooks_equivalence`), add a standing test that asserts each is wired to the
     **universal** path (≥1 external/NGv2 call site, not-disabled-under-pytest for the
     apply path, both promote AND rollback arms live). Remove the single-site /
     self-only / post-merge-only / pytest-disabled clips (the drift documented at
     orch.py:2980 self-only and orch.py:1181 rollback-only).
   - **Rationale:** The plan's own §2 admits this mechanism "was implemented twice and
     clipped both times." Restoring it WITHOUT a guard that fails when it gets
     re-clipped means the durability substrate (atomic swap + automatic rollback —
     the thing that makes UEP safe to leave running) silently degrades back to
     special-case on the next refactor. A re-clipped rollback arm = an edit that fails
     mid-apply and wedges the tree with no undo. This is a re-wedge-of-the-recovery-
     mechanism — the worst kind, because it removes the safety net while looking green.
   - **Ordering impact:** Land WITH Tier 0b (step 6, before UEP rides on it). UEP
     (Tier 0) must not be declared operational until its rollback substrate is both
     restored AND guarded against re-clipping.

7. **LABEL:** Skip-backlog re-try-once sweep
   - **Correction:** D3 — add a standing periodic sweep that re-queues
     `selfheal_skip`-marked tasks (86 markers, provenance tracked per L2 §4) **once**
     after a harness root-fix touches their failing subsystem. Make it automatic and
     subsystem-keyed, not a manual session.
   - **Rationale:** 86 permanently-abandoned tasks accumulate with zero
     re-evaluation. Each is a latent wedge: the moment a dependent needs one, dispatch
     dep-gates and the operator is back in the loop. Worse, the backlog only grows —
     it's a monotonic abandonment counter, which is the structural signature of "not
     staying operational." Once the durability core (1–6) actually fixes the failing
     subsystems, the abandoned tasks should auto-recover, not wait for a human to
     remember them. This converts the 86-marker pile from a one-way ratchet into a
     self-draining queue.
   - **Ordering impact:** After the durability core AND after the root-fix passes
     (corrections 4–5) exist — so the re-try has a fixed subsystem to retry against.
     Step 7.

8. **LABEL:** Operational-health regression as the gate
   - **Correction:** Before declaring the factory "operational," require a standing
     end-to-end durability regression that asserts the wedge-recovery invariants hold:
     (a) a planted stale `git_commit.lock` from a dead PID is reclaimed by the
     watchdog within N min (correction 1); (b) pause via either channel halts dispatch
     identically (correction 2); (c) a re-dispatched task ignores any stale sidecar
     (correction 3); (d) a diagnosed heal auto-applies and commits, NGv2-gated
     (correction 5); (e) `merge_staging_to_parent` rollback fires on a failed apply
     (correction 6). This is the **minimum durability core** definition.
   - **Rationale:** Without an explicit "staying-green" acceptance test, "operational"
     means "produced one green leaf" — which the evidence shows is fully compatible
     with re-wedging the next day (the 25–46% intervention band never fell with
     maturity, L2 §1). The plan's D2 ("verify-claims-against-HEAD") verifies *that a
     commit landed*, not *that the factory can recover unattended*. The owner's goal
     is the latter. This regression is what makes "permanent root-cause" auditable.
   - **Ordering impact:** This IS the gate for declaring operational — runs after the
     durability core (1–6), before UEP/Tier-3 are pointed at NGv2 at scale. Step 8.

---

## YOUR PROPOSED ORDERED PLAN

The reordering principle: **land the durability core that prevents re-wedging FIRST,
prove it with a staying-green regression, THEN do the throughput work the existing
plan front-loads.** A re-wedge primed behind a green leaf is a slower path back to
PAUSED, so anti-re-wedge corrections precede first-green even when they don't
produce the fastest first green.

**Phase A — Restore + de-wedge (get it running and KEEP it running):**
1. **Stale-lock auto-reclaim in watchdog** (corr. 1, B7) — wire existing
   `_acquire_commit_lock_or_reclaim` into `_check_inactivity_watchdog`. This is what
   un-wedges the currently-paused factory and stops the ×30 re-kick loop.
2. **Unify the dual pause channel** (corr. 2, B6) — one authoritative pause so the
   operator can safely stop the daemon before every later autonomy increase.
3. **Terminal sidecar purge + budget reset on every dispatch** (corr. 3, A5/B2) —
   so retries/heals don't silently re-apply stale broken output.

**Phase B — Make fixes permanent (stop the recurrence):**
4. **Standing-pass guarantee** (corr. 4) — A1–A4 + mutation-target (A2) +
   deadlock-breaker (B4) + clobber-bomb reject (B5) as `normalize_plan`/`validate_plan`
   passes, PLUS a meta-guard test that fails if a known blocker class has no standing
   pass. Run the whole planner suite. (This is also the plan's highest-leverage
   throughput work — it just gets the "must be standing" enforcement attached.)
5. **Self-heal diagnose→apply, NGv2-gated** (corr. 5, flip `selfheal_auto_promote`
   ON + B3 class-retries + C3 NGv2 contract gate) — closes the diagnose-only wedge.
   Depends on steps 2 and 3.

**Phase C — Restore the durable substrate, guarded:**
6. **Re-neuter guard for clipped mechanisms** (corr. 6, Tier 0b) — restore blue-green
   handoff + shadow→enforce canary to universal, WITH a test that fails on re-clip,
   so the atomic-swap/rollback safety net can't silently degrade.

**Phase D — Prove staying-green, THEN build throughput on top:**
7. **Operational-health regression** (corr. 8) — the explicit "minimum durability
   core" acceptance gate. **Declare the factory operational only when this is green.**
8. **Skip-backlog re-try-once sweep** (corr. 7, D3) — drain the 86 abandonments now
   that subsystems are root-fixed.
9. **THEN** the existing plan's throughput keystone: UEP core primitive (Tier 0,
   verbatim block-manifest apply, inside the now-guarded green slot) → `daemon edit`
   verb (B1/B2) → Tier 3 NGv2 boundary (C1–C3, each behind the §4 NGv2 contract
   regression) → remaining Tier 4 guardrails (D1 router, D4).

**Minimum durability core that must land before "operational":** corrections 1, 2,
3, 5, 6, validated by the regression in correction 8. (4 and 7 strongly recommended
in the same pass.) UEP and the NGv2-scale work in the existing plan's Tier 0/3 can
follow — they make the factory *faster*, but they do not make it *stay up*, and the
evidence is that staying up is the unsolved problem.
