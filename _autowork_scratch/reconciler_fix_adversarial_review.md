# Adversarial review — `brief_hooks_reconciler_reaps_spent_briefs.md` (corrected fix-brief)

READ-ONLY review. No production file, brief, oracle, or state was modified. One probe script set
was run under `_autowork_scratch/` plus inline `python3 -` heredocs (evidence below).

## ★ HEADLINE (changes the whole verdict)

**The work this brief describes has ALREADY SHIPPED — but as a DIFFERENT implementation than the
brief prescribes.** Both product files are committed clean at HEAD:

- `harness/state_reconciler.py::reap_spent_briefs` exists at line 1451, introduced by commit
  **`c6224c4`** ("Integrate validated code for watchdog-stall-detect-escalate-impl"). `git diff HEAD`
  for this file = **0 lines** (clean).
- `tests/harness/test_reconciler_reaps_spent_briefs.py` is committed at HEAD, `git diff HEAD` = 0.
- **The live oracle passes 6/6 against the live impl** (`pytest ... -q` → `6 passed in 0.08s`).

So the corrected brief is reviewing a *spec* whose product is already on disk and green. The
adversarial questions below are answered against BOTH (i) the brief's prescribed approach and
(ii) the impl that actually landed — because they DIVERGE.

The history is fully reconstructed and matches the prompt's premise:
- The ORIGINAL blocked attempt used the **un-gated** spec (`reap_for_task` on `tasks[0]`). Its
  `repair_feedback` (in `state/tasks/blocked/reconciler-reaps-spent-briefs-impl.json`) shows the
  EXACT failure: `test_..._partially_integrated` → `AssertionError: assert ['demo'] == []`. Retry
  sidecar: `attempts=2, last_outcome=auto_commit_failed`. **The defect is real and was the true
  cause — confirmed.** (`_autowork_scratch/reconciler_spec_bug_repro.py` reproduces: un-gated reaps
  `['demo']` in case (b); gated yields `[]`.)
- The blocked task's plan copy STILL carries the un-gated notes (`all(' present: False`,
  `reap_for_task(root_path, task_id` present: True). The archived plan json
  `_autowork_archive/plan_hooks_reconciler_reaps_spent_briefs.json` is likewise the OLD un-gated
  variant.
- What actually landed (`c6224c4`) is a **third variant**: a self-contained reimplementation that
  inlines its own ledger scan + its own `_archive_move_collision_safe`, NOT the brief's
  `reap_for_task` + `_integrated_task_ids` reuse, and NOT the un-gated defect either.

## Per-question verdicts

### 1. CORRECTNESS — PASS (both the brief's approach and the shipped impl satisfy the oracle)
The oracle (`tests/harness/test_reconciler_reaps_spent_briefs.py`) pins exactly cases (a)–(d):
(a) fully-integrated → `spent_briefs == ['demo']` + files under `_autowork_archive/<today>/reconciled/`;
(b) partial → `spent_briefs == []`, files remain; (c) wiring end-to-end via `reap_stale_disk`;
(d) fail-safe/idempotent + standalone `reap_spent_briefs(tmp_path) == []`.
- The brief's all-integrated gate approach passes both (a) and (b) — PROVEN by the repro
  (`FIXED-LOGIC passes BOTH oracle cases: True`).
- The SHIPPED impl also passes all six (live run). **The committed oracle needs NO change** — it
  is already green and already pins the partial-skip case (b) that the gate exists to satisfy.

### 2. OVER-CORRECTION — PASS for the brief's approach; **DIVERGENCE in the shipped impl (not a regression vs oracle)**
`_integrated_task_ids` (brief_reaper.py:144) counts `phase=='accepted'` / `event=='no_diff'` and
UN-counts on a later `reject_rollback`/`task_blocked` (ordered scan). The brief's gate
`all(tid in _integrated_task_ids(root) ...)` never wrongly skips a genuinely-integrated plan: a tid
is in the set iff its last relevant ledger event is an accept. Correct.
- **BUT the shipped impl does NOT match these semantics.** It counts `phase=='accepted'` OR
  `event=='accepted'` and has NO reject_rollback/task_blocked un-counting. PROVEN: a ledger with
  t1+t2 accepted then `t2 reject_rollback` → live `reap_spent_briefs` reaps `['demo']`, whereas
  `_integrated_task_ids` reports only `{'t1'}` integrated (so the brief's approach would yield `[]`).
  This is an OVER-reap (it archives a plan whose accept was reverted). The oracle does not exercise
  reject_rollback, so it does not catch this. This is a latent correctness gap in the SHIPPED code,
  not in the brief's prescription.

### 3. IMPORT/SCOPE — PASS
`_integrated_task_ids` is genuinely MODULE-scope (`tools/brief_reaper.py:144`, top-level `def`,
NOT nested in `reap_for_task`) and importable as `tools.brief_reaper._integrated_task_ids` (used it
directly in probes). The circular-import hazard is real and correctly characterized: brief_reaper.py
imports `from harness.state_reconciler import state_reconcile_lock` at its BOTTOM (line 141), so a
top-level `from tools.brief_reaper import ...` in state_reconciler would deadlock module load. The
brief's mandated lazy import inside the function avoids it. (The shipped impl sidesteps this entirely
by not importing from brief_reaper at all — it inlines the logic.)

### 4. EDGE CASES — PASS for fail-safety; **two semantic divergences in shipped impl**
Probed against the LIVE impl:
- empty-tasks plan → `[]` (skip). Brief approach: `plan_ids` empty → skip. Both correct.
- multi-plan (one full, one partial) → `['one']`. Both approaches correct (per-plan).
- plan with NO companion brief, fully integrated → live impl **reaps the plan** (moves it, returns
  `['np']`). The brief's `reap_for_task` reuse REQUIRES a paired brief (`_find_brief_paired_plan`
  returns `(None,None)` → `[]`), so it would SKIP. Divergence — the shipped impl is looser.
- epic plan (`plan_kind:epic`), integrated → live impl **reaps it** (`['ep']`). `reap_for_task`
  explicitly skips epics (`_plan_is_epic` / `_is_epic`). The brief's reuse approach would NOT reap an
  epic; the shipped impl DOES. **This is the more important divergence** — the worker hot-path
  (`reap_for_task`) never archives epic brief+plan pairs, but the reconciler sweep now would, so the
  two archive paths disagree on epics.
- No case raises; both variants are fail-safe per-plan (try/except per plan / outer try). Idempotent
  (files gone on re-run). Confirmed by oracle case (d) + probes.

### 5. R-ANCHOR / PATCH SHAPE — PASS (brief instruction is sound; moot for the shipped artifact)
The brief correctly mandates the R-ANCHOR-additive pattern: emit ONE `symbol` patch anchored on an
EXISTING top-level name (`reap_stale_disk`, which is edited anyway) whose `code` reproduces that
anchor verbatim-as-edited PLUS the new `reap_spent_briefs`, relying on the additional-`def`
allowed_extra whitelist. This is exactly the documented recipe for adding a brand-new top-level
symbol without an opaque `auto_commit_failed`. The blocked plan json's `implementation_notes`
follows this shape. (Note: the actual commit `c6224c4` evidently landed the symbol successfully, so
the anchor mechanics worked.)

### 6. REGRESSION — PASS
`reap_stale_disk`'s contract change is additive only: `results` now carries `'spent_briefs': []`
default (line 973) plus the populated value (line 992), set OUTSIDE... actually note the shipped impl
places the call INSIDE the lock block (line 991, still within `with state_reconcile_lock`), which is
safe ONLY because the shipped `reap_spent_briefs` does NOT call `reap_for_task` (no flock
re-acquisition) — it uses `_archive_move_collision_safe` directly. The brief's prescription (call
OUTSIDE the lock) is the CORRECT instruction *for the reuse approach* (where `reap_for_task`
re-acquires the flock → self-deadlock if nested). The two are consistent given their different
bodies. The four pre-existing reapers and their keys are unchanged. No grep'd caller/test asserts an
exact key set on `reap_stale_disk` that the added key would break; the regression tests
(`test_state_reconciler_clutter_scan_passes`, `..._path_correctness_passes`) are green.

## OVERALL VERDICT — **NEEDS-CHANGE (brief is now STALE / already superseded)**

The brief's CORE correction (the all-integrated gate vs the un-gated `tasks[0]` defect) is
**analytically sound and would pass the oracle** — if it were the thing being built. But it is NOT
shippable as-written because **the feature already landed at HEAD via a different, self-contained
implementation** that is green on the same committed oracle. Re-running this brief through the
pipeline would either no-op (files already at HEAD) or churn the shipped impl back to the
`reap_for_task`-reuse shape, which DIVERGES behaviorally (epic-awareness, brief-pairing,
reject_rollback un-counting). REJECT a blind re-dispatch.

Recommended disposition (no production edits made here — these are for the operator):

1. **Do NOT re-dispatch this brief.** Mark it DONE/superseded — `reap_spent_briefs` + oracle are
   committed clean at HEAD (`c6224c4`), oracle 6/6 green. Clear the stale state: the
   `state/tasks/blocked/reconciler-reaps-spent-briefs-impl{,.retry}.json` sidecars and the
   `state/control/autowork/running/...slot` reflect the OLD failed un-gated attempt, not reality;
   remove `reconciler_reaps_spent_briefs` from `state/control/autowork/auto_promote.allowlist` so it
   is not re-promoted.
2. If the brief is kept for the record, it MUST be corrected to describe what shipped: signature is
   `reap_spent_briefs(root) -> list` (NO `*, stamp=None`); body is self-contained (own ledger scan +
   `_archive_move_collision_safe`), NOT a `reap_for_task`/`_integrated_task_ids` wrapper; the call
   sits INSIDE the `state_reconcile_lock` block (safe because no flock re-acquisition). The current
   brief's "lazy-import reap_for_task", "OUTSIDE the lock", and "gate on `_integrated_task_ids`"
   prose all describe a design that did NOT ship.
3. **Separately consider a follow-up brief** (the only substantive gap): the SHIPPED impl is
   looser than the worker hot-path on three axes the oracle never tests — it reaps epic plans, reaps
   brief-less plans, and ignores `reject_rollback`/`task_blocked` un-counting. If parity with
   `reap_for_task` is desired (it probably is — the two archive paths should agree), file a brief to
   add epic-skip + brief-pairing + reject_rollback-aware counting to `reap_spent_briefs`, with oracle
   cases for each. This is the real residual work, NOT the gate the current brief obsesses over.

### Precise brief edits IF kept as documentation-of-shipped (option 2):
- Title/Scope frontmatter: signature → `reap_spent_briefs(root) -> list[str]` (drop `*, stamp=None`).
- Section 1 bullets: DELETE the "lazy-import `reap_for_task, _integrated_task_ids`" and
  "ALL-INTEGRATED GATE via `_integrated_task_ids`" prose; REPLACE with "inline ledger scan counting
  `phase=='accepted'`/`event=='accepted'`; reap when `all(tid in accepted)`; move via
  `_archive_move_collision_safe`."
- Section 2 / Implementation notes: DELETE "MUST be OUTSIDE the lock" + "LAZY import" + "LOCK
  RE-ENTRANCY" hazards (the shipped body acquires no nested flock). The call is INSIDE the lock.
- Keep the R-ANCHOR-additive note (still accurate and how it landed).
