# Adversary 4 Review — CUT SCOPE & MAKE IT COMPOUND

**Lens:** Be the editor. The 22-item plan is too big. Find the minimal COMPOUNDING set —
the few changes that (a) restore operation and (b) make every *next* fix cheaper — and
cut/defer the rest. Attack one-offs masquerading as root-cause fixes.

**Landed-state accounting (verified against git):**
- **A2 LANDED** — `db7a9ca` (RED oracle) + `a7f9ad1` (`strip-stray-mutation-target`); normalizer is a real pass in `harness/planner/plan_normalizer.py`. Remove from plan.
- **C1 precursor LANDED** — `6f5c4d2` (`stamp-working-dir-blind-draft`) + `785888f` (`_spy` working_dir kwarg). C1 is partially in flight, NOT done end-to-end.
- **Blue-green substrate EXISTS** — `merge_staging_to_parent`/`create_staging_worktree`/`perform_process_handover` in `git_integration.py`+`orchestrator.py`; `hooks_equivalence.py` present. So "restore" = un-clip, not rebuild.

---

## The core argument

The owner's diagnosis is that the factory **accretes faster than it consolidates** and the
*same blocker classes recur because fixes are one-offs*. The plan's own evidence says the
biggest *recurring* root cause is the **planner-defect cluster** (S1 / `normalize_plan`,
Lane-3 §1, Lane-2 §5/6). That is the only family where a single fix is *reusable by
construction*: a `normalize_plan` pass fires on **every plan, every epic, forever** — it
is the definition of compounding.

Everything else in the plan is either (a) a *verb* that wraps a manual command (B1/B2 —
convenience, not consolidation; absorbs keystrokes but doesn't stop a blocker class
recurring), (b) a *flag flip* (cheap, fine to batch), or (c) the **UEP/blue-green
mega-build** — which is the single biggest scope item and is *itself* the trap the owner
named: a universal mechanism, already built and clipped twice, that this plan proposes to
re-universalize as a large new program of work. Doing UEP-as-a-program now repeats the
accretion pattern. The compounding move is to **fix the planner passes first** (which
removes the *reasons* people route around the pipeline) and only then decide whether UEP is
still load-bearing.

A blunt test for "is this on the compounding path?": *Does it run automatically on the next
N tasks without anyone invoking it, and does it retire a whole blocker class?* If no to
either, it's a one-off or a convenience and gets cut/deferred.

---

## DISCRETE CORRECTIONS

### 1.
- **LABEL:** Planner-pass core is the slice
- **Correction:** KEEP A1, A3, A4, B4, B5 as the high-leverage core. These are the five S1/plan-time passes that attack the planner-defect cluster (oracle-source injection, vcmd upgrade, structural multi-file/whole-file route, deadlock-breaker default-on, clobber-bomb reject). Land them together as standing `normalize_plan`/`validate_plan` passes. A2 is already landed and joins this set as proof of the shape.
- **Rationale:** Lane-3 §1 names the planner-defect cluster as *the biggest recurring root cause*; Lane-1 ORACLE_AUTHORING=449, MANUAL_PIPELINE_DRIVING=1518, and the `plan_attempts` 5/5 deadlock slugs all trace here. A pass is reusable *by definition* — fires on every future plan. This is the only family where one fix provably stops a class from recurring. Counts are high AND determinism is high.
- **Ordering impact:** Position 1 (the whole first phase).

### 2.
- **LABEL:** Cut UEP-as-a-program; keep verbatim-apply primitive only
- **Correction:** CUT the UEP "Universal Edit Path" verb, the `daemon edit --file ...` entry point, and the Tier-0b blue-green re-universalization *as a build program*. KEEP only the one genuinely compounding primitive inside it: **verbatim block-manifest apply** (uniqueness-checked literal replace, fail-closed on 0/>1 match) as a new worker apply-mode. Land that primitive through the existing pipeline; do NOT build the verb, the shadow→enforce ladder restoration, or the self-re-exec generalization now.
- **Rationale:** UEP is the largest scope item and is the *exact* anti-pattern the owner flagged — a universal mechanism re-universalized as a big new program while the system already accretes too fast. The verbatim-apply primitive alone retires the entire AST-fragility blocker family (Lane-3: AST-truncation/never-patch-class-methods/R-anchor=9 approvals; Lane-2 `auto_commit_failed`=39) and removes the "147KB whole-file balk → Gemini-solo fallback" — that part compounds. The *verb wrapper* and *blue-green restore* do not retire a blocker class; they're a convenience+infra layer that can ride on top later, once the planner passes have already shrunk the hand-edit reasons. Building them now risks a *third* clip.
- **Ordering impact:** Position 3 (primitive only, after planner passes + flags).

### 3.
- **LABEL:** Merge sidecar/reset/inactivity into one terminal-state reaper
- **Correction:** MERGE A5 + B2 + B7 into a single deterministic "terminal-outcome reaper" that, on any task reaching terminal state (or on stale-lock detection), purges sidecars + sessions + processed/blocked markers + stale `git_commit.lock` and resets the retry budget. Expose `--reset-task` as a thin caller of the same function. Drop the separate B2/B7 line items.
- **Rationale:** These three are the *same* mechanical state-hygiene operation seen from three angles (Lane-1 STATE_SIDECAR ~700, Lane-2 `daemon_inactivity_stuck`=30 which is itself a stale-lock wedge). One function on the dispatch/terminal hook is reusable-by-construction and stops the stale-sidecar-precedence gotcha + the inactivity wedge as a class. Three line items collapse to one.
- **Ordering impact:** Position 2 (rides with the flag flips, before the apply primitive).

### 4.
- **LABEL:** Batch the OFF-flag flips, defer the risky ones
- **Correction:** KEEP as a single cheap batch: A6 (`archive_spent_briefs` ON), A7 (auto-push on green integrate), `wire_up_gate` already ON. DEFER `selfheal_auto_promote`, `agy_pool.enabled`, and `antigravity_mode` until after the planner core + verbatim primitive are proven. CUT the "restore blue-green/canary substrate" framing from this batch entirely (see #2).
- **Rationale:** A6/A7 are pure flips with known-good behavior and high keystroke payoff (Lane-1 GIT_PUSH=153 near-verbatim, declutter=56 commits). They compound passively. But `selfheal_auto_promote` rewrites `ngv2/workers/*`/`session_db.py` (Lane-2 §2) — turning it ON before the NGv2 contract-gate (C3) exists is a regression risk, not a compounding win. Flipping ON the canary/agy capabilities is scope dressed as "un-neuter"; defer.
- **Ordering impact:** Position 2 (A6/A7 in the flag batch); deferred flags → Position 6+.

### 5.
- **LABEL:** Cut B1/B2-verbs, B6/B8, D2/D3/D4 as one-offs/convenience
- **Correction:** CUT or DEFER: B1 (`daemon drive` verb), B6 (pause-primitive unify), B8 (allowlist auto-populate), D2 (verify-against-HEAD button), D3 (selfheal_skip re-try sweep), D4 (`scope_allowlist_to_epic`). B2 is absorbed by #3.
- **Rationale:** None of these retire a *recurring blocker class*; they wrap manual rituals. B1 is the biggest keystroke bucket (1518) but it's a *convenience verb* — once the planner passes stop the defects that *force* the manual drives, most of that 1518 evaporates without building a new verb (don't pave the cowpath you're about to remove). B8/D4 are allowlist ergonomics (90 churn) — real but low-leverage; the allowlist is an owner *governance* surface, automating it weakens the gate. B6 (pause unify) is a correctness nit worth a 2-line fix but not a phase. D2/D3 are audit conveniences. All are deferrable until the core compounds.
- **Ordering impact:** Deferred backlog (Position 6+), B6 as a trivial inline fix anytime.

### 6.
- **LABEL:** B3 folds into the verbatim primitive
- **Correction:** MERGE B3 (auto-retry `auto_commit_failed` by failure class) INTO the verbatim-apply primitive (#2) rather than building a separate self-heal classifier. With verbatim block-manifest apply, the class-method-edit / symbol-add / large-symbol-truncation failure classes *cannot occur* — there is no AST surgery to truncate. So B3's retry logic is largely obviated, not implemented.
- **Rationale:** B3 (Lane-2 §3, 39 events) is the dominant task-level heal failure, but it's a *symptom* of the AST partial-edit path. Building a classifier to retry AST failures is treating the symptom; the verbatim primitive removes the cause. Classic one-off-vs-root-cause: cut the classifier, fix the apply path. This is exactly the compounding substitution the owner wants.
- **Ordering impact:** Subsumed by Position 3; remove as a separate item.

### 7.
- **LABEL:** C1 finish-only; C2/C3 stay NGv2-gated and last
- **Correction:** KEEP C1 but scope it to *finish the already-started* end-to-end `working_dir` threading (precursor `6f5c4d2` landed) — staging-reroot + commit-reroot + seq-worker env. DEFER C2 (wire-up default-ON, already partly ON) and C3 (`selfheal_auto_promote` NGv2-gated) to the very end, each behind the §4 NGv2 contract regression.
- **Rationale:** C1 is the only Tier-3 item on the restore path — it unblocks every external EDIT leaf (Lane-3 §5, 18+ approvals; Lane-1 1710 NGv2 calls) and is a prerequisite for ever pointing edits at NobleGreedv2. It compounds (every future NGv2 leaf). C2/C3 are hardening, not restoration, and carry the highest break-NGv2 risk; they must not be early. Finishing C1 also closes a half-done item rather than opening a new one — consolidation, not accretion.
- **Ordering impact:** C1 → Position 4. C2/C3 → Position 6 (gated, last).

### 8.
- **LABEL:** D1 guard only after UEP-route exists — defer
- **Correction:** DEFER D1 (pre-commit guard flagging un-pipelined `harness/**`/`ngv2/**` edits). The plan itself says D1 *routes into UEP*. With UEP-as-a-program cut (#2), D1 has nowhere to route — it would just *block* the operator's fastest path with no sanctioned alternative, which will be ignored or reverted.
- **Rationale:** Lane-1 MANUAL_PRODUCTION_EDIT=1259 is the highest-*risk* category, so D1 is tempting. But a guard with no destination is a speed bump, not a fix — and the operator owns the repo, so it gets disabled. The compounding way to kill hand-edits is to make the pipeline path *not hit blockers* (the planner core + verbatim primitive); once those land, the verbatim direct-apply path becomes the easier option organically, and D1 (or a lighter nudge) can be added then.
- **Ordering impact:** Deferred (Position 6+), contingent on a verbatim-apply route existing.

---

## YOUR PROPOSED MINIMAL ORDERED PLAN

Five phases. Phases 1–4 are the restore-and-compound core (~9 effective items, several
already part-landed); Phase 5+ is the deferred backlog to pull from only after the core
proves it shrank the intervention rate.

**Phase 1 — Planner-pass core (the compounding slice).** Land A1, A3, A4, B4, B5 as
standing `normalize_plan`/`validate_plan` passes; A2 already landed. Run the *whole*
planner suite (a new pass can break sibling passes). *Compounds: fires on every future
plan; retires the planner-defect cluster — the #1 recurring root cause.*

**Phase 2 — Flag batch + terminal-state reaper.** Flip A6 + A7 ON. Land the merged
A5+B2+B7 terminal-outcome reaper (sidecar/session/marker/stale-lock purge + retry reset),
with `--reset-task` as a thin caller. *Compounds: passive declutter+push; one function
kills stale-sidecar precedence + inactivity wedge as a class.*

**Phase 3 — Verbatim block-manifest apply primitive (NOT the UEP verb).** Land
uniqueness-checked literal-replace apply-mode in `orchestrator_worker` + `git_integration`,
RED-oracle first, through the pipeline. Subsumes B3. *Compounds: retires the entire
AST-fragility blocker family and the whole-file/Gemini-solo fallback; becomes the future
edit substrate.*

**Phase 4 — Finish C1.** Complete end-to-end `working_dir` threading (precursor landed),
gated behind the NGv2 §4 contract regression. *Compounds: unblocks every external EDIT
leaf; consolidates a half-done item.*

**Phase 5+ — Deferred backlog (pull only if the core hasn't already absorbed the load).**
C2, C3 (NGv2-gated, last), then — only if still needed — B1 verb, D1 guard (now that a
verbatim-apply route exists to route into), B8/D4 allowlist ergonomics, D2/D3 audit
conveniences, and the deferred OFF-flags (`selfheal_auto_promote` behind C3,
`agy_pool.enabled`, `antigravity_mode`). B6 pause-unify as a trivial inline fix anytime.

**Explicitly CUT (not merely deferred):**
- **UEP-as-a-program** + the `daemon edit` verb (keep only the verbatim primitive).
- **Tier-0b blue-green/canary re-universalization as a build program** (un-clip later if
  ever load-bearing; building it now repeats the clip-it-twice pattern).
- **B3 as a separate self-heal classifier** (root-caused away by the verbatim primitive).
- **A2** (already landed).

**One-line thesis for cross-reviewer voting:** *The only fixes that compound by
construction are the plan-time passes (Phase 1) and the verbatim-apply primitive (Phase 3);
build those, flip the safe flags, finish C1 — and CUT the UEP/blue-green mega-build, which
is the very accretion-over-consolidation pattern the owner is trying to break.*
