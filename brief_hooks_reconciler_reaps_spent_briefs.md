---
working_dir: "/home/xnihil0zer0/JanusMaskJR"
required_task_ids:
  - reconciler-reaps-spent-briefs-oracle
  - reconciler-reaps-spent-briefs-impl
interfaces: >
  harness/state_reconciler.py — add a NEW top-level helper `reap_spent_briefs(root, *, stamp=None)`
  and EDIT the existing sweep `reap_stale_disk(root, *, now=None)` to invoke it. Goal: make
  archive-on-integrate SELF-HEALING. Today the ONLY path that archives a spent brief+plan is the
  worker hot-path hook `harness/orchestrator_worker.py::_reap_spent_briefs_safe` -> `tools/brief_reaper.py::reap_for_task`,
  which fires EXACTLY ONCE on the last task's accept and swallows all errors with no retry. The
  periodic reconciler sweep `reap_stale_disk` runs four reapers (orphaned workdirs, ledger compaction,
  log age-out, `_autowork_archive` retention prune) but has NO step that catches a brief whose
  fire-once archive was missed. Add that fifth step, reusing the already-idempotent `reap_for_task`.
---

# Title
Make archive-on-integrate self-healing: reconciler sweep reaps spent-but-unarchived briefs

# Scope
EDIT the EXISTING file `harness/state_reconciler.py` (READ it first). SINGLE FILE. This is a
sensitive-path edit (`harness/**`), so the implementation task is `harness_self_fix`.

Two changes to that one file, emitted as `__JANUSMASK_PATCHES__`:

1. ADD a new top-level function:
   `reap_spent_briefs(root, *, stamp=None) -> list[str]` that:
   - Resolves `root` to a `Path`; if it is not an existing dir, returns `[]`.
   - Computes `stamp` when `None` as `datetime.date.today().isoformat()` (import `datetime` lazily
     inside the function).
   - LAZILY imports BOTH helpers inside the function body —
     `from tools.brief_reaper import reap_for_task, _integrated_task_ids` — to AVOID a circular import
     (`tools/brief_reaper.py` imports `state_reconcile_lock` from this very module at its bottom; a
     top-level import here would deadlock the module load). `_integrated_task_ids` is intentionally a
     MODULE-scope helper (hoisted out of `reap_for_task` precisely so callers can reuse it).
   - Iterates `sorted(root.glob('plan_hooks_*.json'))`. For each plan file: load JSON; collect the
     plan's task ids `plan_ids = [t['task_id'] for t in data.get('tasks', []) if isinstance(t, dict)
     and t.get('task_id')]`; if `plan_ids` is empty, skip this plan.
   - ★ ALL-INTEGRATED GATE (CRITICAL — this is the whole point of the sweep): compute
     `integrated = _integrated_task_ids(root)` and reap ONLY when `all(tid in integrated for tid in
     plan_ids)`. When the gate passes, call `reap_for_task(root, plan_ids[0], stamp=stamp)` and extend
     a result list with whatever slugs it returns (0 or 1). When the gate FAILS (a partially-integrated
     plan), SKIP the plan and reap nothing.
     WHY THE EXPLICIT GATE (do NOT delete it): `reap_for_task` force-adds the task_id you pass to its
     integrated set (`integrated.add(task_id)`) — an "implicit accept" that is correct ONLY on the
     worker hot-path (where that task genuinely just accepted). In THIS sweep the passed id may NOT be
     accepted, so calling `reap_for_task` directly on `plan_ids[0]` would WRONGLY reap a
     partially-integrated plan (proven: `_autowork_scratch/reconciler_spec_bug_repro.py` — case (b)
     reaps `['demo']` without the gate, `[]` with it). Gating on `_integrated_task_ids` FIRST means
     every id in `plan_ids` is already genuinely integrated, so the implicit-accept is then redundant
     and harmless.
   - Wrap EACH plan in its own try/except so one bad plan never aborts the loop; the whole function is
     fail-safe and returns the list of archived slugs.
   - It does NOT take `state_reconcile_lock` itself — `reap_for_task` already acquires that lock
     per-call internally; `_integrated_task_ids` only READS the ledger and takes no lock.

2. EDIT `reap_stale_disk(root, *, now=None)` so that, AFTER its existing
   `with state_reconcile_lock(state_dir):` block has EXITED (the lock RELEASED), it calls
   `reap_spent_briefs(root_path)` inside its own contained try/except and stores the result under a
   new `results['spent_briefs']` key (default `[]` on any error), then returns `results` as before.
   CRITICAL: the call MUST be OUTSIDE the `with state_reconcile_lock(...)` block — `reap_for_task`
   re-acquires that same flock, and nesting it inside the already-held lock would self-deadlock.

# Inputs
READ `harness/state_reconciler.py`. VERIFIED current code (source of truth — do NOT change beyond
the two edits above):
- The sweep to edit: `def reap_stale_disk(root, *, now=None):` (currently ~line 949). It sets
  `now = time.time()` when `None`, builds
  `results = {'workdirs': [], 'ledger_compacted': False, 'logs': [], 'archive': []}`, runs the four
  reapers under `with state_reconcile_lock(state_dir):`, and `return results`.
- The reuse target (do NOT modify): `tools/brief_reaper.py::reap_for_task(repo_root, task_id, *, stamp, archive=True)`
  is idempotent and ground-truth-gated — it archives a brief+plan IFF the WHOLE plan's tasks are
  integrated per `state/impl_progress.jsonl` (an `accepted`/`no_diff` ledger row, un-counted by a later
  `reject_rollback`/`task_blocked`), the brief is NOT an epic, the brief/plan are paired, exactly one plan
  claims the tid, and it MOVES (never deletes) the files to `_autowork_archive/<stamp>/reconciled/` under
  `state_reconcile_lock`. It returns `[slug]` or `[]`. Re-running it on an already-archived brief is a safe
  no-op (the root files are gone -> no match -> `[]`).
  ★ CAVEAT that drives the all-integrated gate above: `reap_for_task` does `integrated.add(task_id)`
  BEFORE checking `all(plan_ids in integrated)` — i.e. it ASSUMES the `task_id` you pass is integrated
  (valid on the worker accept hot-path; INVALID for an arbitrary id in a sweep). That is exactly why
  `reap_spent_briefs` must gate on `_integrated_task_ids(root)` itself FIRST and only pass an id that is
  already genuinely integrated. Do NOT "simplify" by dropping the gate and calling `reap_for_task` on
  `plan_ids[0]` directly — that is the original defect (oracle case (b) regresses).
- The reuse target (do NOT modify): `tools/brief_reaper.py::_integrated_task_ids(root) -> set` — a
  MODULE-scope helper returning the set of task ids with an `accepted`/`no_diff` ledger row (un-counted
  by a later `reject_rollback`/`task_blocked`), exact-match, fail-soft (missing ledger -> empty set). It
  takes NO lock and only reads `state/impl_progress.jsonl`.
- The RED oracle (pre-committed sibling) is the source of truth for required behavior.

# Non-Goals
Integration is out of scope for the implementation task (the literal word `integration` MUST appear
here to excuse the integration-test requirement). Do NOT modify `tools/brief_reaper.py`,
`reap_for_task`, `cleanup_state`, `state_reconcile_lock`, or any other symbol or file. Do NOT change
the four existing reapers or the `results` keys other than ADDING `spent_briefs`. Do NOT change the
worker hot-path hook. Do NOT author tests beyond the one oracle. Do NOT restart or reconfigure the
daemon.

# Deliverables
`harness/state_reconciler.py` with (1) the new `reap_spent_briefs` helper and (2) `reap_stale_disk`
invoking it OUTSIDE the reconcile lock and surfacing `results['spent_briefs']`, GREEN under the
scoped verification_command, with no regression to the existing reapers.

# Required plan shape
Emit EXACTLY TWO tasks, a RED-pair.

Task 1 — the oracle (authored RED first):
- task_id MUST be exactly `reconciler-reaps-spent-briefs-oracle`.
- meta_task_type: test_authoring
- mutation_target: harness.state_reconciler   (dotted MODULE only)
- files_touched: ["tests/harness/test_reconciler_reaps_spent_briefs.py"]
- Submit the test file source directly (ordinary Python; NEITHER marker).
- verification_command: `python -m pytest tests/harness/test_reconciler_reaps_spent_briefs.py -q`
- The oracle MUST, using a tmp-dir fixture `root` (NO reliance on the live repo), assert:
  (a) FULLY-INTEGRATED case: write `root/state/impl_progress.jsonl` with `accepted` rows for EVERY
      task_id in a `root/plan_hooks_demo.json` (2 tasks), and a `root/brief_hooks_demo.md`; after
      calling `reap_stale_disk(root)` the brief AND plan are GONE from `root` and PRESENT under
      `root/_autowork_archive/<today>/reconciled/`, and `'spent_briefs'` is in the returned dict.
  (b) PARTIALLY-INTEGRATED case: only ONE of two task_ids has an `accepted` row -> after
      `reap_stale_disk(root)` the brief+plan REMAIN at `root` (NOT archived).
  (c) WIRING: the archival in (a) happens via `reap_stale_disk` itself (call it end-to-end), proving
      `reap_stale_disk` invokes the new helper — not merely that `reap_spent_briefs` works in isolation.
  (d) FAIL-SAFE/idempotent: a second `reap_stale_disk(root)` after (a) does not raise and re-archives
      nothing; a `root` with no plans / no ledger returns cleanly.

Task 2 — the implementation:
- task_id MUST be exactly `reconciler-reaps-spent-briefs-impl`.
- meta_task_type: harness_self_fix
- files_touched: ["harness/state_reconciler.py"]
- depends on `reconciler-reaps-spent-briefs-oracle`.
- Emit a `__JANUSMASK_PATCHES__` (do NOT emit `__JANUSMASK_MANIFEST__`).
- OMIT mutation_target. spec_author: null (oracle is the pre-committed sibling).
- verification_command: `python -m pytest tests/harness/test_reconciler_reaps_spent_briefs.py -q`
- non_goals MUST contain the literal word `integration`; regression_tests >= 2.

# Implementation notes / hazards
- R-ANCHOR additive (the new `reap_spent_briefs` is a brand-new top-level symbol): a standalone
  `kind:symbol` patch for a not-yet-existing name fails patch-apply. Add it via the R-ANCHOR additive
  pattern — one `symbol` patch whose `name` is an EXISTING 1-part top-level anchor (e.g. `reap_stale_disk`
  itself, which you are editing anyway, OR `prune_autowork_archive`) and whose `code` reproduces that
  anchor VERBATIM-as-edited PLUS the new `reap_spent_briefs` function. Every extra node must be in the
  allowed_extra whitelist (an additional `def` qualifies); the new name must not collide with an existing
  one. If you anchor on `reap_stale_disk`, both edits land in ONE patch entry.
- LAZY import only: `from tools.brief_reaper import reap_for_task` MUST live INSIDE `reap_spent_briefs`,
  never at module top — `tools/brief_reaper.py` imports `state_reconcile_lock` from this module, so a
  top-level import is circular.
- LOCK RE-ENTRANCY: call `reap_spent_briefs` strictly OUTSIDE `reap_stale_disk`'s
  `with state_reconcile_lock(state_dir):` block. `reap_for_task` re-acquires that flock; nesting deadlocks.
- NESTED-QUOTE HAZARD: if any docstring is emitted in the patch, emit `"""` (not `'''`) and never
  backslash-escape quotes.
