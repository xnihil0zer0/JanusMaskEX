---
working_dir: "/home/xnihil0zer0/JanusMaskJR"
required_task_ids:
  - reap-spent-briefs-parity-oracle
  - reap-spent-briefs-parity-impl
interfaces: >
  harness/state_reconciler.py — REFACTOR the EXISTING top-level helper `reap_spent_briefs(root) -> list`
  so it DELEGATES both its integration gate and its archival to the canonical reaper
  `tools/brief_reaper.py`. Today `reap_spent_briefs` (shipped in c6224c4, oracle 6/6 GREEN) does its OWN
  ledger scan that counts a task integrated on any `phase=='accepted' or event=='accepted'` row and
  NEVER un-counts a later `reject_rollback`/`task_blocked`, and does its OWN archive move that does NOT
  skip epic plans nor require brief/plan pairing. That diverges from the canonical reaper
  `tools/brief_reaper.py::reap_for_task` (epic-skip + pairing + collision-safe move + git-rm--cached) and
  from its integration oracle `_integrated_task_ids` (reject_rollback/task_blocked-aware). Two latent
  WORKS defects result and are independently reproduced in
  `_autowork_scratch/reconciler_spec_bug_repro.py`: (1) reject_rollback OVER-REAP — a plan whose every
  task has an `accepted` row but one was LATER `reject_rollback`'d is WRONGLY reaped, so a reverted brief
  disappears from root and is never re-worked; (2) epic OVER-REAP — an epic plan+brief is reaped, whereas
  `reap_for_task` skips epics. Fix = make `reap_spent_briefs` a thin sweep that gates on
  `_integrated_task_ids` and archives via `reap_for_task`, preserving the shipped signature and contract.
---

# Title
Bring the reconciler-sweep spent-brief reaper to integration parity with the canonical reaper (reject_rollback-aware + epic-skip)

# Scope
EDIT the EXISTING file `harness/state_reconciler.py` (READ it first). SINGLE FILE. This is a
sensitive-path edit (`harness/**`), so the implementation task is `harness_self_fix`.

ONE change to that one file, emitted as a `__JANUSMASK_PATCHES__` SYMBOL patch:

REFACTOR the EXISTING top-level function `reap_spent_briefs(root) -> list` so it DELEGATES its
integration gate to `tools.brief_reaper._integrated_task_ids` (which is reject_rollback/task_blocked-aware)
and its archival to `tools.brief_reaper.reap_for_task` (which already does epic-skip, brief/plan pairing,
exactly-one-plan-claims-tid, a collision-safe MOVE — never a delete — to
`_autowork_archive/<stamp>/reconciled/`, and `git rm --cached` staging). This is a behaviour-preserving
PARITY fix for the two currently-passing cases plus a correctness fix for the three divergent cases. The
function already exists at HEAD — this is a SYMBOL EDIT, NOT a new-symbol add (no R-anchor-additive hazard).

# Inputs
READ `harness/state_reconciler.py`. VERIFIED current code (source of truth):
- The function to edit: `def reap_spent_briefs(root) -> list:` (currently ~line 1451). It does its OWN
  ledger scan into an `accepted` set (counting `phase=='accepted' or event=='accepted'` and NEVER
  un-counting a later `reject_rollback`/`task_blocked`), then its OWN `_archive_move_collision_safe` of any
  plan whose tasks are all in that set — with NO epic-skip and NO brief/plan-pairing requirement. It returns
  a sorted list of reaped slugs.
- The unchanged call site (do NOT change it): `reap_stale_disk(root, *, now=None)` (currently ~line 957)
  calls `results['spent_briefs'] = reap_spent_briefs(root_path)` (~line 992) inside its own try/except,
  passing ONLY `root_path`. KEEP the `reap_spent_briefs(root) -> list` signature so this call site is
  untouched.
- The reuse target (do NOT modify): `tools/brief_reaper.py::reap_for_task(repo_root, task_id, *, stamp, archive=True) -> list[str]`
  archives a brief+plan IFF the WHOLE plan is integrated per `state/impl_progress.jsonl`, the brief is NOT
  an epic (frontmatter `epic: true` OR plan `plan_kind=='epic'`/`epic is True`), the brief/plan are paired,
  and exactly ONE plan claims the tid; it MOVES (never deletes) collision-safe to
  `_autowork_archive/<stamp>/reconciled/` under `state_reconcile_lock` and `git rm --cached`s the source.
  Returns `[slug]` or `[]`; re-running on an already-archived brief is a safe no-op.
  ★ CAVEAT that drives the explicit gate below: `reap_for_task` does `integrated.add(task_id)` BEFORE
  checking `all(plan_ids in integrated)` — i.e. it ASSUMES the `task_id` you pass is integrated (valid on
  the worker accept hot-path; INVALID for an arbitrary id in a sweep). So `reap_spent_briefs` MUST gate on
  `_integrated_task_ids(root)` itself FIRST and only call `reap_for_task` once every plan id is already
  genuinely integrated.
- The reuse target (do NOT modify): `tools/brief_reaper.py::_integrated_task_ids(root) -> set` — a
  MODULE-scope helper returning the set of task ids with an `accepted`/`no_diff` ledger row, UN-counted by a
  LATER `reject_rollback`/`task_blocked` row for the same id (exact-match, fail-soft: missing ledger ->
  empty set). It takes NO lock and only reads `state/impl_progress.jsonl`.
- PROVEN behaviour: `_autowork_scratch/reconciler_spec_bug_repro.py` plus the operator's 5-case analytic
  run show the delegated design passes all five: (a) fully-integrated -> reap; (b) partial -> skip;
  (c) reject_rollback -> skip; (d) epic -> skip; (e) brief-less -> skip. Today's shipped code over-reaps
  on (c) and (d).
- The RED oracle (pre-committed sibling) is the source of truth for required behavior.

# Exact algorithm the implementation MUST prescribe
Replace the body of `reap_spent_briefs(root) -> list` with the following, emitting the COMPLETE
replacement function (full body, not a fragment):
- KEEP the signature exactly `reap_spent_briefs(root) -> list` (the caller passes only `root_path`; do
  NOT change the call site).
- Resolve `root_path = Path(root)`.
- Compute `stamp = datetime.date.today().isoformat()` internally (import `datetime` LAZILY inside the
  function).
- LAZY-import inside the function body: `from tools.brief_reaper import reap_for_task, _integrated_task_ids`.
  This avoids the load-time circular import — `tools/brief_reaper.py` imports `state_reconcile_lock` from
  this very module at its bottom, so a top-level import here would be circular.
- Compute `integrated = _integrated_task_ids(root_path)` ONCE (it is a pure ledger read).
- Iterate `sorted(root_path.glob('plan_hooks_*.json'))`, EACH plan wrapped in its OWN try/except so one
  bad plan never aborts the loop (fail-safe). For each plan: load JSON into `data`; collect
  `plan_ids = [t['task_id'] for t in data.get('tasks', []) if isinstance(t, dict) and t.get('task_id')]`;
  if `plan_ids` is empty, skip this plan.
- ★ ALL-INTEGRATED GATE (do NOT delete it): reap ONLY when `all(tid in integrated for tid in plan_ids)`.
  This gate MUST come BEFORE `reap_for_task` precisely because `reap_for_task` force-adds the passed
  `task_id` to its integrated set (`integrated.add(task_id)`) — valid on the worker hot-path, but it would
  otherwise over-reap a partial plan in a sweep. When the gate passes, call
  `reap_for_task(root_path, plan_ids[0], stamp=stamp)` and EXTEND a result list with whatever slugs it
  returns (0 or 1). When the gate FAILS, SKIP the plan.
- Return the reaped slugs as a SORTED list (preserve the shipped contract).
- `reap_spent_briefs` takes NO lock of its own (`_integrated_task_ids` only reads the ledger). The call
  site `reap_stale_disk` invokes it INSIDE its `with state_reconcile_lock(state_dir):` block (line ~992) —
  and that is SAFE because `state_reconcile_lock` is RE-ENTRANT (threading.local refcount,
  state_reconciler.py:603-619): when `reap_for_task` re-acquires the SAME lock it merely increments the
  refcount, so there is NO self-deadlock (verified by driving real `reap_stale_disk` end-to-end). Do NOT
  change `reap_stale_disk` and do NOT move the call site — leave the existing in-lock call exactly as-is.
- Do NOT remove the now-possibly-unused `_archive_move_collision_safe` helper (out of scope; leaving dead
  code is safe — another reaper may use it).

# Non-Goals
Integration is out of scope for the implementation task (the literal word `integration` MUST appear here
to excuse the integration-test requirement). Do NOT modify `tools/brief_reaper.py`, `reap_for_task`,
`_integrated_task_ids`, `agent_jail.py`, `orchestrator.py`, `cleanup_state`, `state_reconcile_lock`, the
`reap_stale_disk` call site, or any other symbol or file. Do NOT remove `_archive_move_collision_safe`.
Do NOT change the worker hot-path hook. Do NOT author tests beyond the one oracle. Do NOT restart or
reconfigure the daemon.

# Deliverables
`harness/state_reconciler.py` with `reap_spent_briefs` REFACTORED to delegate its integration gate to
`tools.brief_reaper._integrated_task_ids` and its archival to `tools.brief_reaper.reap_for_task`,
preserving the `reap_spent_briefs(root) -> list` signature and the sorted-slug return contract, GREEN
under the scoped verification_command, with the EXISTING reaper oracle still passing (no regression to the
already-shipped cases a+b).

# Required plan shape
Emit EXACTLY TWO tasks, a RED-pair.

Task 1 — the oracle (authored RED first):
- task_id MUST be exactly `reap-spent-briefs-parity-oracle`.
- meta_task_type: test_authoring
- mutation_target: harness.state_reconciler   (bare dotted MODULE only)
- priority: high
- files_touched: ["tests/harness/test_reap_spent_briefs_parity.py"]
- Submit the test file source directly (ordinary Python; NEITHER `__JANUSMASK_*` marker).
- verification_command: `python -m pytest tests/harness/test_reap_spent_briefs_parity.py -q`
- The oracle MUST import and exercise the LIVE `harness.state_reconciler.reap_spent_briefs` (and/or
  `reap_stale_disk` end-to-end), use REAL tmp dirs (NO reliance on the live repo), and write ledger rows
  with the SAME shape the system uses — `{'task_id': tid, 'phase': 'accepted'}` for an accept and
  `{'task_id': tid, 'event': 'reject_rollback'}` for a revert. It MUST assert the three currently-divergent
  cases:
  (c) REJECT_ROLLBACK: a `plan_hooks_demo.json` with tasks `[t1, t2]`, a paired `brief_hooks_demo.md`, and
      a ledger with `accepted` rows for BOTH t1 and t2 FOLLOWED BY a LATER `{'task_id': t1, 'event':
      'reject_rollback'}` row -> `reap_spent_briefs(root)` returns `[]` and the brief AND plan REMAIN at
      `root` (NOT archived). This FAILS RED on today's shipped code, which over-reaps the reverted plan.
  (d) EPIC: a plan+brief whose brief frontmatter declares `epic: true` (and/or plan `epic: true`), its
      single task `accepted` in the ledger -> `reap_spent_briefs(root)` returns `[]` and the brief+plan
      REMAIN at `root`. This FAILS RED on today's shipped code, which has no epic-skip.
  (e) BRIEF-LESS: a `plan_hooks_demo.json` with NO paired `brief_hooks_demo.md`, its task `accepted` ->
      `reap_spent_briefs(root)` returns `[]` and the plan REMAINS at `root`.

Task 2 — the implementation:
- task_id MUST be exactly `reap-spent-briefs-parity-impl`.
- meta_task_type: harness_self_fix
- priority: high
- files_touched: ["harness/state_reconciler.py"]
- depends on `reap-spent-briefs-parity-oracle`.
- operator_decision_required: true
- Emit ONE `__JANUSMASK_PATCHES__` SYMBOL patch (do NOT emit `__JANUSMASK_MANIFEST__`):
  `{'file': 'harness/state_reconciler.py', 'kind': 'symbol', 'name': 'reap_spent_briefs', 'code': <COMPLETE new function body>}`.
- OMIT mutation_target. spec_author: null (oracle is the pre-committed sibling).
- verification_command MUST run BOTH the existing oracle AND the new one (regression-proof cases a+b stay
  green): `python -m pytest tests/harness/test_reconciler_reaps_spent_briefs.py tests/harness/test_reap_spent_briefs_parity.py -q`
- non_goals MUST contain the literal word `integration`; regression_tests >= 2.

# Implementation notes / hazards
- SYMBOL EDIT, NOT additive: `reap_spent_briefs` ALREADY EXISTS at HEAD (~line 1451), so emit a single
  `kind:symbol` patch named `reap_spent_briefs` whose `code` is the COMPLETE replacement function. There is
  NO R-anchor-additive hazard here (the symbol is not new). Do NOT emit a partial/anchored patch.
- LAZY import only: `from tools.brief_reaper import reap_for_task, _integrated_task_ids` MUST live INSIDE
  the `reap_spent_briefs` body, never at module top — `tools/brief_reaper.py` imports `state_reconcile_lock`
  from this module, so a top-level import is circular. `import datetime` must also be lazy inside the
  function (as it is today).
- GATE-BEFORE-REAP: compute `integrated = _integrated_task_ids(root_path)` and check
  `all(tid in integrated for tid in plan_ids)` BEFORE calling `reap_for_task`, because `reap_for_task` does
  `integrated.add(task_id)` and would otherwise over-reap a partial plan. Do NOT "simplify" by dropping the
  gate and calling `reap_for_task` on `plan_ids[0]` directly — that re-introduces the partial-reap defect
  (existing oracle case (b) regresses).
- LOCK (re-entrant — no deadlock): `reap_spent_briefs` takes NO lock itself. It is invoked INSIDE
  `reap_stale_disk`'s `with state_reconcile_lock(state_dir):` block (~line 992). This does NOT deadlock
  because `state_reconcile_lock` is RE-ENTRANT (threading.local refcount, state_reconciler.py:603-619):
  `reap_for_task` re-acquiring the SAME lock just bumps the refcount. Do NOT change `reap_stale_disk` and
  do NOT move the call site (in or out) — leave the existing in-lock call as-is.
- FAIL-SAFE: wrap EACH plan iteration in its own try/except so one corrupt/unreadable plan never aborts the
  sweep; the whole function returns the list of archived slugs (sorted) and never raises.
- NESTED-QUOTE HAZARD: emit `"""` docstrings (never `'''`) and never backslash-escape quotes in the patch
  `code`.
