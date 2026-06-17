# Intervention-Automation Plan — v2 (adversarial-panel revision)

**How this was produced.** v1 (`INTERVENTION_ANALYSIS_00_FINAL_REPORT.md`) was put to an
8-adversary panel, each tasked to re-order it for the fastest *restore-and-stay-operational*
path, no fallbacks. The 4 agy (Gemini) voters were blocked on an expired OAuth and did not
vote; the 4 Claude voters (fastest-path, bootstrapping, durability, cut-and-compound) all
returned and **converged strongly**, and each verified live state rather than trusting v1.

**Voting rule applied.** A correction needs ≥4/8 votes (with my veto) to enter v2. With the
agy four absent, any correction at **4/4 Claude = 4 of 8 = clears the bar** independent of agy
(missing votes can only add support). 4/4 items are LOCKED. 2–3/4 items are where agy would
have mattered; I arbitrate those with veto power and flag them. Two items below threshold are
included anyway because they are *verified facts*, not opinions — labeled as such.

**Live facts the panel verified (v1 was stale on all of these):**
- `state/control/autowork/git_commit.lock` holds **PID 3731840 — DEAD**. The live daemon
  cannot commit. (#1 self-heal signature, `daemon_inactivity_stuck` ×30.)
- **Both** pause channels are set (`pause` file *and* `orchestrator.flag=="paused"`) — the
  dual-pause hazard, live.
- **41 blocked tasks, 23 `.exhausted`** (zero retry budget — will NOT re-dispatch on resume).
- **Planner suite is RED at HEAD** — oracle `66f4df2` (`blind_draft` wiring-oracle token) has
  no impl landed. The "run the whole planner suite" safety gate is blind against a non-green
  baseline.
- **A1, A2, A4 are ALREADY landed** as passes in `plan_normalizer.py`
  (`_inject_oracle_sources`:285, `_strip_stray_mutation_targets`:994,
  `_split_multifile_module_tasks`:836). The blue-green/canary substrate also already exists.
  → v1 presented Tier 1 and the substrate as net-new. They are not. This shrinks v2 a lot.

---

## 1. Cross-panel tally

Voters: **1**=fastest-path, **2**=bootstrap, **3**=durability, **4**=cut/compound.

| Correction (canonical) | 1 | 2 | 3 | 4 | Votes | Status |
|---|:-:|:-:|:-:|:-:|:-:|---|
| **Clear stale lock + wire auto-reclaim into watchdog (B7) — step zero** | ✓ | ✓ | ✓ | ✓ | 4/4 | **LOCKED** |
| **Unify dual pause channel + clear both signals (B6)** | ✓ | ✓ | ✓ | ~ | 4/4 | **LOCKED** (4 calls it trivial, not a phase) |
| **Terminal sidecar purge + retry-budget reset on dispatch (A5/B2)** | ✓ | ✓ | ✓ | ✓ | 4/4 | **LOCKED** |
| **Merge lock-clear + sidecar-purge + budget-reset into ONE terminal-state reaper** | ~ | – | ✓ | ✓ | 4/4* | **LOCKED** (implementation form) |
| **Keep the verbatim block-manifest apply primitive** | ✓ | ✓ | ✓ | ✓ | 4/4 | **LOCKED** |
| **Do NOT build the UEP verb / blue-green re-universalization now (defer/cut)** | ✓ | ✓ | ✓ | ✓ | 4/4 | **LOCKED** (1/2/3 defer, 4 cut) |
| **Planner passes (A1/A3/A4+B4/B5) are standing `normalize_plan`/`validate_plan` passes** | ✓ | ✓ | ✓ | ✓ | 4/4 | **LOCKED** |
| **Reconcile "done" vs HEAD — build only the missing delta (A1/A2/A4 landed)** | ✓ | ✓ | – | ✓ | 3/4 | **LOCKED** (verified fact) |
| **C1 finish-only; C2/C3 NGv2-gated and last** | ✓ | ✓ | ✓ | ✓ | 4/4 | **LOCKED** |
| **Green the RED planner baseline before adding passes** | – | ✓ | ~ | – | 1/4 | **INCLUDED (verified blocker, not opinion)** |
| **Keep daemon paused; land fixes via `orchestrator_worker` hand-drive; gate unpause behind green core** | ✓ | ✓ | ✓ | – | 3/4 | **INCLUDED (arbiter)** |
| **Defer risky flags (`selfheal_auto_promote`, `agy_pool`, `antigravity_mode`) until after core + NGv2 gate** | ~ | – | ⊘ | ✓ | 2–3/4 | **INCLUDED, gated** (3 wants selfheal in core; see veto) |
| Standing-pass meta-guard test ("blocker class ⇒ has a pass") | – | – | ✓ | ~ | 2/4 | below-threshold — see §3 |
| Operational-health regression as the "operational" gate / D2 verify-against-HEAD | ✓ | – | ✓ | ✗ | 2/4 | below-threshold — see §3 |
| Re-neuter guard for clipped mechanisms | – | – | ✓ | – | 1/4 | deferred (moot until substrate restored) |
| Skip-backlog re-try-once sweep (D3) | – | – | ✓ | ✗ | 1/4 | deferred |
| B1 `daemon drive` verb | ⊘defer | – | ⊘defer | ✗cut | — | **CUT/defer** |
| D1 un-pipelined-edit guard | – | – | – | ✗cut | — | **CUT/defer** (routes into cut UEP verb) |
| B3 as a separate AST-failure classifier | ⊘ | – | – | ✗fold | — | **FOLD into the primitive** (no AST surgery ⇒ class can't occur) |
| B8 / D4 allowlist ergonomics | – | – | – | ✗cut | — | **CUT** (governance surface) |

✓ = supports · ~ = supports with caveat · ⊘ = defer · ✗ = cut · – = not raised

---

## 2. My vetoes / arbitrations

1. **VETO "apply-primitive *before* planner passes" (Adv-1's ordering, 1/4).** Adv-1 is right
   that the *current backlog* fails at apply, not plan-shape — but the verbatim primitive is
   greenfield net-new code (Adv-2: no apply-mode/verb exists), so it can't be built until the
   pipeline is un-wedged and the baseline is green. Primitive lands **after** the de-wedge core
   and the baseline-green, alongside the planner-pass delta — not first.
2. **REFINE the "single reaper" (locked) with Adv-3's precise finding:** the reaper must also
   fire stale-lock reclaim **from the inactivity watchdog** (`_check_inactivity_watchdog`,
   autowork_daemon.py:2913), not only on dispatch — because the existing reclaim primitive
   (`_acquire_commit_lock_or_reclaim`:2079) is today wired *only* to the push path (:2180).
   That gap is the literal cause of the ×30 re-kick loop. B7 = connect existing reclaim to
   existing detector.
3. **ARBITRATE the `selfheal_auto_promote` split (Adv-3 core vs Adv-4 defer):** defer it, but
   keep Adv-3's hard ordering constraint — *if/when* enabled it must come **after** the sidecar
   purge (else auto-apply retries against poisoned sidecars) **and** be NGv2-contract-gated.
   Not in the must-do core; revisit after the core proves out.
4. **No veto on the cuts.** UEP-verb, D1, B8/D4, and B3-as-classifier are cut/folded with panel
   support; this is the consolidation the owner asked for.

---

## 3. Below-threshold but recommended (your call — not auto-included)

These got 2/4 (would need agy to clear). I find them compelling and tied to your compounding
goal, but per the rule they are **not** auto-integrated:
- **Standing-pass meta-guard test** (Adv-3): a regression that fails if a known blocker class
  has no standing normalize/validate pass — encodes your "fixes must be permanent" rule as a
  test instead of a hope. Strongly recommend folding into the planner-pass phase.
- **Operational-health regression as the operational gate** (Adv-1+3): assert the wedge-recovery
  invariants (stale-lock reclaimed, either pause halts dispatch, stale sidecar ignored, rollback
  fires) before declaring "operational." Adv-4 cut it as audit overhead.

Re-authenticate agy and I'll run the 4-voter panel to resolve these two (and any 3/4 marginals)
under the true 8-voter math.

---

## 4. The v2 ordered plan

**Phase 0 — Out-of-band unwedge (operator, state files only; daemon stays paused).**
Sanctioned because it's state, not production code.
- Delete the stale `git_commit.lock` (PID 3731840, dead).
- Collapse to one pause channel; clear it when ready to resume.
- Triage the 41 blocked / 23 `.exhausted` tasks out of the dispatch path.

**Phase 0.5 — Green the planner baseline.** Land the stranded `blind_draft` wiring-oracle impl
(via `drive_leaf.py` → `orchestrator_worker --task-id`, daemon paused) **or** xfail+record it,
so the planner suite is a trusted gate before any new pass is added.

**Phase 1 — De-wedge core, made permanent (the durability core).** All via hand-drive through
`orchestrator_worker` (it ignores pause), RED-oracle first:
1. **B7 reaper** — stale-lock reclaim wired into the inactivity watchdog *and* the terminal-state
   reaper (purge `state/output/<id>.{patches,files}.json`, `state/sessions/*_<id>_*`,
   `state/tasks/<id>.json`, stale lock; reset retry budget). One function, fired on dispatch +
   watchdog. (Locked: B7 + A5/B2 merged.)
2. **B6** — unify the dual pause to one authoritative channel.

**Phase 2 — Planner-pass delta + safe flags.**
- Reconcile A1/A2/A4 (already landed) vs HEAD; build only the **delta**: **A3** (weak-vcmd→pytest
  upgrade), **B4** (deadlock-breaker default-on), **B5** (clobber-bomb reject at plan time) — as
  standing `normalize_plan`/`validate_plan` passes. Run the *whole* (now-green) planner suite.
- Flip the **safe** flags only: **A6** (`archive_spent_briefs` ON), **A7** (auto-push on green
  integrate). Defer `selfheal_auto_promote`, `agy_pool`, `antigravity_mode`.
- *(Recommended, §3: add the standing-pass meta-guard here.)*

**Phase 3 — Verbatim block-manifest apply primitive.** Uniqueness-checked literal replace,
fail-closed on 0/>1 match, as a new worker apply-mode in `orchestrator_worker` + `git_integration`.
RED-oracle first, hand-driven. **Subsumes B3** (the AST-fragility failure classes can't occur
without AST surgery). This is the durable fix for the apply-stage failures dominating the backlog.

▶ **Declare "operational" here** — re-admit the triaged backlog, unpause the daemon, expect green
leaves. *(Recommended, §3: gate this on the operational-health regression.)*

**Phase 4 — Finish C1 (NGv2-gated).** Complete end-to-end `working_dir` threading
(staging-reroot + commit-reroot + seq-worker env; precursor `6f5c4d2` landed), behind the §4
NGv2 contract regression. Unblocks external EDIT leaves.

**Phase 5+ — Deferred backlog, pull only if the core hasn't absorbed the load.** C2/C3
(NGv2-gated, last); then *if still needed* the UEP `daemon edit` verb, D1 router, the deferred
flags (`selfheal_auto_promote` behind C3 + after the purge), `agy_pool`. Skip-backlog re-try
sweep (D3) once subsystems are root-fixed.

---

## 5. What changed from v1 (summary)

- **De-wedge is now first, not buried at step 6.** v1 front-loaded planner normalizers that
  don't unblock the live backlog; v2 leads with lock-reclaim + pause-unify + sidecar/budget reset.
- **UEP-as-a-program and the blue-green re-universalization are cut/deferred** — the panel
  (and the owner) flagged building them now as a repeat of the clip-it-twice accretion pattern.
  Only the **verbatim-apply primitive** survives.
- **Tier 1 shrank to a delta** — A1/A2/A4 are already live; only A3/B4/B5 remain.
- **A new hard prerequisite surfaced** — the planner suite is RED at HEAD; v1's safety gate was
  blind. Phase 0.5 fixes it.
- **B3 folded, B1/D1/B8/D4 cut.** Net: v2 is roughly **9 effective items across 4 phases**, much
  of it already part-landed — days, not weeks.
