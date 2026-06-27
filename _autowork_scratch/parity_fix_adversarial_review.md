# Adversarial review — delegated `reap_spent_briefs` refactor (parity fix)

READ-ONLY review. HEAD=`b0d6999`. Shipped impl at `harness/state_reconciler.py:1451`,
wired at `:992` inside `reap_stale_disk`. Canonical reaper `tools/brief_reaper.py`.
Validation: `_autowork_scratch/parity_fix_validation.py` (8/8 green) +
`/tmp/nested_lock_probe.py` (real `reap_stale_disk` drive, no deadlock).

## Per-question verdicts

### Q1 REGRESSION — existing oracle stays green — **PASS**
`tests/harness/test_reconciler_reaps_spent_briefs.py` (6 tests) passes on shipped
code today (verified). Its assertions: case (a) full-integrate -> `spent_briefs==['demo']`,
brief+plan gone from root, both present under `_autowork_archive/<today>/reconciled/`,
re-run `==[]`; (b) partial -> `spent_briefs==[]`, files remain; (c) wiring via
`reap_stale_disk` itself; (d) empty root clean + `reap_spent_briefs(tmp_path)==[]`.
The delegated path satisfies ALL of these: `reap_for_task` archives to the IDENTICAL
`_autowork_archive/<stamp>/reconciled/` dir and returns `[slug]`; the ledger fixture
writes `{'task_id', 'phase':'accepted'}` which `_integrated_task_ids` counts (line 176).
Cases (a)/(b)/(c)/(d) reproduced under the delegated design = PASS in the script.
NOTE: the oracle's `_write_ledger` writes NO `reject_rollback`/epic rows, so it cannot
distinguish shipped vs delegated on its own — it's a pure regression check, which holds.

### Q2 BEHAVIORAL DIFFERENCE — `git rm --cached` side effect — **PASS (desirable)**
Confirmed in a real git repo: after the delegated reap, `git status --porcelain` shows
`D  brief_hooks_<slug>.md` and `D  plan_hooks_<slug>.json` (BOTH staged deletions) and
the archived copies under `_autowork_archive/` are UNTRACKED — i.e. MOVE preserved, the
tree-tracked source is removed from the index. This is exactly the archive-on-integrate
intent (the spent brief+plan SHOULD leave the tracked tree). `_stage_deletion`
(`brief_reaper.py:90`) is fully fail-safe (`check=False`, bare `except Exception: pass`),
so a non-repo / missing-git / already-untracked path is swallowed. The shipped
`reconciler` sweep runs under `state_reconcile_lock`, NOT `git_commit.lock`, so this is
the intended off-the-commit-lock seam. Concurrent-worker concern: a worker auto-commit
could capture these staged deletions — but that is the DESIRED convergence (the same
`git rm --cached` already runs on the worker hot path via `_reap_spent_briefs_safe` ->
`reap_for_task`, `orchestrator_worker.py:70`); the reconciler is just a catch-up sweep
for briefs the hot path missed. This is a strict IMPROVEMENT over the shipped plain-move
(which leaves a `D` working-tree deletion unstaged → tree never converges).

### Q3 LOCK SAFETY — no nested-lock deadlock — **PASS (safer than the brief claims)**
IMPORTANT CORRECTION to the brief: `reap_spent_briefs` is NOT called "outside"
`state_reconcile_lock`. `reap_stale_disk` calls it at line 992 INSIDE the
`with state_reconcile_lock(state_dir):` block (opened :974). So `reap_for_task`'s
re-acquire (`brief_reaper.py:128`) is a NESTED acquisition on the same thread.
This is SAFE: `state_reconcile_lock` is RE-ENTRANT (`state_reconciler.py:603-619`) —
a `threading.local` refcount keyed by the resolved lock path; a re-acquire bumps the
count and yields without re-creating the `O_EXCL` file, and the file is unlinked only
on the OUTERMOST release. Proven end-to-end: driving the delegated impl through the REAL
`reap_stale_disk` completed with `spent_briefs==['demo']`, archived the brief, and left
NO `state_reconcile.lock` behind (clean release). `_integrated_task_ids` takes no lock
(pure read, `brief_reaper.py:144`). Per-plan re-acquire is a perf-only cost (re-entrant
no-op when already held), no correctness issue. The brief's wording is wrong but its
conclusion (no deadlock) is correct.

### Q4 RETURN CONTRACT — sortedness — **NEEDS-CHANGE (add the sort)**
Shipped returns `reaped.sort()` (sorted, `:1542`). The naive delegated version
`extends` across plans → insertion-ordered (= already sorted-by-slug, since
`glob('plan_hooks_*.json')` is `sorted()`, but a multi-plan-sharing-a-tid edge could
reorder). The ONLY consumer is `reap_stale_disk` storing `results['spent_briefs']`
(`:992`); grep confirms NO downstream code indexes/orders `spent_briefs` and the oracle
asserts `== ['demo']` (single element) and `== []`. So nothing FUNCTIONALLY depends on
sortedness — but the shipped docstring/contract promises "sorted list of reaped slugs".
To preserve the documented contract verbatim, the brief MUST `return sorted(reaped)`
(my validation impl does this; it costs nothing). Verdict: harmless either way, but
ADD the explicit `sorted()` to keep the stated contract.

### Q5 IMPORT/SCOPE — `_integrated_task_ids` importable, no circular import — **PASS**
`_integrated_task_ids` is MODULE-scope (`brief_reaper.py:144`, top-level `def`),
imports cleanly: `from tools.brief_reaper import reap_for_task, _integrated_task_ids`
succeeded in the validation run. `brief_reaper` imports `state_reconcile_lock` at its
BOTTOM (`:141`) — `state_reconciler` does not import `brief_reaper`, so no cycle. The
delegated impl in `state_reconciler` must use a LAZY (function-body) import of
`tools.brief_reaper` to avoid `state_reconciler` import-time depending on `brief_reaper`
import-time depending back on `state_reconciler` (the bottom-of-module import means
`brief_reaper` is only fully importable once `state_reconciler` is defined). Lazy import
inside `reap_spent_briefs` sidesteps this entirely. Verdict: PASS, with the explicit
requirement that the import be LAZY (function-local), matching the worker bridge
precedent (`orchestrator_worker.py:69` does the same lazy import).

### Q6 EDGE CASES — **PASS (delegated is equal-or-better on every case)**
- shared tid across plans: `_find_brief_paired_plan` returns `(None,None)` when
  `len(matches)!=1` → `reap_for_task` no-ops (oracle `test_shared_task_id_is_ambiguous_noop`).
  The pre-gate `all(... in integrated)` is on the per-plan ids, so each plan is judged
  independently; the disambiguation lives in `reap_for_task`. SAFE.
- `plan_ids[0]` integrated but a LATER id isn't: the EXPLICIT pre-gate
  `all(tid in integrated for tid in plan_ids)` (evaluated BEFORE `reap_for_task`, so
  before `reap_for_task`'s `integrated.add(task_id)` implicit-accept) catches it →
  skip. This is THE defect the shipped impl's design-twin (reap_for_task-on-tasks[0])
  would have mis-handled; the gate ordering is the whole point and it works (case e1/b).
- already-archived / re-run: idempotent — re-run finds plans gone, `glob` empty,
  returns `[]` (cases a/c/d rerun all `==[]`).
- malformed plan JSON: per-plan `try/except` swallows it AND a malformed plan among
  good ones still reaps the good one (case f PASS).
- reject_rollback (defect #1): `_integrated_task_ids` un-counts on a later
  `reject_rollback`/`task_blocked` → gate fails → SKIP (case e1 PASS). Shipped impl
  WRONGLY reaps (counts any `accepted`, never un-counts).
- epic (defect #2): `reap_for_task` skips epics via `_plan_is_epic` + brief-frontmatter
  `_is_epic` → returns `[]` → SKIP (case e2 PASS). Shipped impl WRONGLY archives epics.
NO case where the delegated design is WORSE than shipped; it is strictly better on the
two defect classes and parity elsewhere.

### Q7 PATCH SHAPE — single symbol patch — **PASS**
`reap_spent_briefs` already exists at HEAD (`:1451`), so a single `__JANUSMASK_PATCHES__`
`kind:symbol` patch REPLACING the existing top-level function is the correct shape — no
new-symbol R-anchor hazard (the symbol is present; the memory gotcha only bites a
brand-new not-yet-existing top-level name). The function is ~92 lines (well under any
truncation threshold). One-file (`harness/state_reconciler.py`), one symbol → clean
single-task symbol patch.

## Overall verdict: **SHIP-WITH-ADDITIONS**

The delegated design is correct and fixes both defects with zero regression. Required
additions before dispatch:
1. **Return `sorted(reaped)`** (Q4) — preserve the documented "sorted list" contract;
   the oracle/consumers don't require it but the docstring promises it. Trivial.
2. **LAZY (function-local) import** of `tools.brief_reaper` (Q5) — avoid the
   bottom-of-module circular-import trap; mirror `orchestrator_worker.py:69`.
3. **Per-plan `try/except: continue`** wrapping the whole gate+reap (Q6) — already in
   the design; keep it so one malformed plan never aborts the sweep.
4. **Doc correction (non-blocking):** the brief asserts `reap_spent_briefs` is called
   "OUTSIDE `state_reconcile_lock`" — it is actually called INSIDE (`reap_stale_disk`
   :992). The re-entrant lock makes the nested `reap_for_task` acquire safe regardless,
   but the brief's rationale text should be corrected so a future reader isn't misled.
5. **Docstring update:** the shipped docstring says "plain move and NEVER a delete" —
   the delegated path ADDS a `git rm --cached` staged deletion (still a filesystem MOVE,
   archive copy retained). Update the docstring to reflect the git-index convergence,
   else it contradicts the new (desirable) behavior.

No REJECT condition found. With additions 1–3 (functional) the refactor is correct;
4–5 are doc-accuracy fixes that should accompany it.
