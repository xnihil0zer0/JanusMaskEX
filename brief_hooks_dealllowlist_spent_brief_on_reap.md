---
working_dir: "/home/xnihil0zer0/AI-Data/JanusMaskEX"
required_task_ids:
  - dealllowlist-spent-brief-on-reap-oracle
  - dealllowlist-spent-brief-on-reap-impl
interfaces: >
  EDIT EXACTLY ONE existing file: tools/brief_reaper.py. Archive-on-integrate
  (the `reap_for_task` reaper that MOVES a fully-integrated brief+plan pair into
  `_autowork_archive/<stamp>/reconciled/`) is the ONE chokepoint BOTH live reap
  paths funnel through — the worker hot-path hook
  `harness/orchestrator_worker.py::_reap_spent_briefs_safe` and the (separately
  briefed) periodic full-sweep `harness/state_reconciler.py::reap_spent_briefs`
  both call `tools.brief_reaper.reap_for_task`. Today, when a spent brief is
  archived, its slug is LEFT on the auto-promote allowlist
  `state/control/autowork/auto_promote.allowlist` forever — NOTHING removes a
  fully-landed slug from that file (verified: `tools/brief_reaper.py` and its
  callers never reference the allowlist; grep of `auto_promote.allowlist` across
  `harness/`+`tools/` shows only READS via `_auto_promote_allowlist`, the daemon
  PLANNED_STALE writer, and the WebUI CRUD PUT — none drops a SPENT slug). PROOF
  the gap is live: `planner_redraft_once_on_invalid_draft` is fully integrated
  (`planner-redraft-once-impl`/`-oracle` both `accepted` in the ledger) yet still
  occupies a line in the committed allowlist. FIX: add a default-OFF, fail-safe
  de-allowlist step INSIDE `reap_for_task` so that, on the SAME ground-truth
  "whole plan integrated + non-epic + uniquely paired" decision that archives the
  pair, the reaped slug is ALSO removed from the allowlist (a comment/blank-line-
  preserving, atomic, line-exact rewrite). Gated OFF behind a NEW
  `JM_DEALLOWLIST_ON_REAP` env flag (default false) so it cannot regress prod
  until proven; when off it is a strict no-op and the existing archive behavior is
  byte-for-byte unchanged.
---

# Title
brief_reaper: de-allowlist a spent brief's slug from auto_promote.allowlist on
reap — default-OFF, fail-safe, comment-preserving line-exact rewrite (ZERO
harness/** edit)

# Scope
EDIT the SINGLE EXISTING file `tools/brief_reaper.py` (READ it first). SINGLE
FILE. `tools/brief_reaper.py` is NOT under any sensitive apply glob
(`_SENSITIVE_APPLY_GLOBS = ('harness/**', 'config/**', 'scripts/**',
'services/**')` — `git_integration.py:8`) and is NOT in `_NEVER_AUTO_APPROVE`, so
this is an ordinary (non-sensitive) module edit, NOT `harness_self_fix`. The
historical precedent for editing this very file is `meta_task_type: data_model`
(plans `brief_reaper_module` / `brief_reaper_v2`); this brief instead uses
`io_adapter` because the new behavior is fundamentally a FILE parse-edit-rewrite
of the allowlist text (read lines, drop one exact slug line, rewrite atomically) —
the encode/decode/parse shape `io_adapter` names, and a fuzzable callable.

Two changes to that one file, emitted as `__JANUSMASK_PATCHES__` SYMBOL patches:

1. ADD a NEW top-level helper `_deallowlist_slug(repo_root, slug) -> bool` that
   removes EXACTLY the line equal to `slug` from
   `<repo_root>/state/control/autowork/auto_promote.allowlist`, preserving every
   comment / blank / other-slug line verbatim, writing atomically, and is a strict
   fail-safe no-op when the file is missing / the slug is absent / the flag is off.
2. EDIT the EXISTING top-level `reap_for_task(repo_root, task_id, *, stamp,
   archive=True)` to call `_deallowlist_slug(root, slug)` on the SAME spent-pair
   decision that archives — only when the pair is actually reaped and the flag is
   armed.

The new behavior must EXTEND the reaper, never reinvent it. The reap GATE
(whole-plan-integrated, non-epic, uniquely-paired) is REUSED as-is; this brief
only adds the de-allowlist side-effect onto the already-proven reap decision and
puts it behind a default-OFF flag.

# Background — why spent slugs stay allowlisted forever (verified)
The auto-promote allowlist `state/control/autowork/auto_promote.allowlist` is a
plain line-based file (one slug per line; `#`-prefixed and blank lines ignored) —
the SAFETY BOUNDARY the daemon reads via `_auto_promote_allowlist`
(`autowork_daemon.py:3107`, also read at `brief_status.py:192`) to decide which
briefs may auto-promote. The operator ADDS a slug to allowlist a brief for the
factory to work; once that brief's whole plan lands, the slug is SPENT — it should
be removed so the allowlist reflects only LIVE work.

Nothing removes a spent slug today. The three writers of that file are:
  - `harness/autowork_daemon.py` PLANNED_STALE arm — only archives a STALE-PLAN /
    evicts a stale brief; it explicitly `continue`s (skips) fully-landed briefs
    (`autowork_daemon.py:2301-2303`) and never edits the allowlist text.
  - `tools/webui_control.py` — a WebUI PUT CRUD endpoint (operator-driven).
  - `harness/rebuild/job.py` — unrelated rebuild bootstrap.
None drops a slug because its brief is now spent.

The reaper `tools/brief_reaper.py::reap_for_task` is the natural home for this:
it already makes the authoritative "this brief is fully integrated and safe to
retire" decision (ground-truth ledger replay via `_integrated_task_ids`, non-epic,
uniquely paired) and MOVES the brief+plan off root. Adding a de-allowlist on that
exact decision keeps allowlist hygiene CONSISTENT with archive hygiene and rides
the ONE chokepoint both live reap paths share.

PROVEN GAP (read-only, this repo): the committed allowlist still lists
`planner_redraft_once_on_invalid_draft`, whose tasks `planner-redraft-once-impl`
and `planner-redraft-once-oracle` are both `accepted` in
`state/impl_progress.jsonl` (its root brief is already gone) — a spent slug that
no code path will ever retire.

WHY DEFAULT-OFF: the allowlist is a SAFETY BOUNDARY (a missing/empty allowlist is
DENY-ALL; an errant drop could de-list LIVE work). The program rule is
BUILT != WORKS, and a new mutator of the safety boundary must land default-OFF,
be proven by its oracle, then be flipped on by the operator. So the de-allowlist
is a strict no-op unless `JM_DEALLOWLIST_ON_REAP` is truthy.

WHY THIS IS SAFE EVEN WHEN ARMED: the de-allowlist fires ONLY for a slug that
`reap_for_task` has ALREADY decided is spent (whole plan integrated, non-epic,
uniquely paired) and is archiving in the same call — i.e. exactly the briefs that
must NOT remain allowlisted. A LIVE / partially-integrated / epic / unpaired brief
never reaches the reap branch, so its slug is never touched.

# Inputs
READ these files FIRST in `/home/xnihil0zer0/AI-Data/JanusMaskEX`:

- `tools/brief_reaper.py` — the SINGLE file both tasks touch. VERIFIED current
  state (source of truth — do NOT change beyond the two edits below):
  - `def reap_for_task(repo_root, task_id, *, stamp, archive=True) -> list[str]:`
    (line 34). It resolves `root = Path(repo_root)`, finds the unique
    `(slug, data)` via the nested `_find_brief_paired_plan`, bails on epic / no
    pair / not-all-integrated, and on the reap branch does:
        if not archive:
            return [slug]
        plan_path = root / f'plan_hooks_{slug}.json'
        state_dir = root / 'state'
        with state_reconcile_lock(state_dir):
            dest = root / '_autowork_archive' / stamp / 'reconciled'
            dest.mkdir(parents=True, exist_ok=True)
            moved = []
            if brief_path.exists() and _move_no_clobber(brief_path, dest):
                moved.append(brief_path.name)
            if plan_path.exists() and _move_no_clobber(plan_path, dest):
                moved.append(plan_path.name)
            for name in moved:
                _stage_deletion(root, name)
        return [slug]
    `slug` is the brief/plan slug (underscore form, e.g.
    `planner_priority_normalize`) derived from the plan FILENAME, and is EXACTLY
    the allowlist line for the brief. The de-allowlist call goes INSIDE this
    `with state_reconcile_lock(state_dir):` block (the lock is REENTRANT per-thread
    via a refcount — `harness/state_reconciler.py:611-619` — so calling a helper
    that does NOT re-take the lock is fine; do NOT re-acquire the lock in the
    helper), AFTER the moves, gated on the flag.
  - The module bottom imports `from harness.state_reconciler import
    state_reconcile_lock` (line 141). Do NOT add new top-level imports that would
    introduce a circular import; use `import os` (already stdlib-safe) at module
    top or lazily inside the helper.
  - `reap_for_task` is FULLY FAIL-SAFE (wrapped in a top-level `try/except` that
    returns `[]`); the new de-allowlist call MUST itself be contained so that an
    allowlist I/O error never aborts the archive and never propagates.

- `state/control/autowork/auto_promote.allowlist` — DO NOT EDIT (read for the
  format only). Plain text, one slug per line; `#`-prefixed lines and blank lines
  are comments. The de-allowlist must remove ONLY a line whose STRIPPED content
  EXACTLY equals `slug` (never a substring/prefix; `t1` must not match `t12`) and
  preserve every other line (comments, blanks, other slugs) byte-for-byte in order.

- `harness/autowork_daemon.py::_auto_promote_allowlist` (line 3107) — DO NOT EDIT
  (read for parse semantics): blank + `#`-prefixed lines are skipped; only a
  non-empty, non-comment line is a slug. The de-allowlist's matching MUST mirror
  this (strip; ignore comment/blank lines when deciding equality) so the WebUI and
  daemon agree on what a "slug line" is.

- `harness/orchestrator_worker.py:45-70` and
  `harness/state_reconciler.py:1451-1528` — DO NOT EDIT (read for context only):
  the two live callers of `reap_for_task`. Both inherit the de-allowlist for free
  because the change is INSIDE `reap_for_task`.

# Non-Goals
Integration is out of scope (the literal word `integration` MUST appear in this
section and in EACH task's `non_goals` to excuse the integration-test
requirement). Specifically OUT OF SCOPE:
- Editing any file other than `tools/brief_reaper.py`. Do NOT edit
  `harness/orchestrator_worker.py`, `harness/state_reconciler.py`,
  `harness/autowork_daemon.py` (in `_NEVER_AUTO_APPROVE`), the allowlist file
  itself, or `harness/config.yaml`.
- Flipping `JM_DEALLOWLIST_ON_REAP` on in any committed config / env, or adding a
  `harness/config.yaml` flag key (that would be a second file). The flag defaults
  OFF when the env var is absent, which is the desired safe default; the operator
  arms it later, exactly like the watchdog / disk-reaper-battery patterns.
- Wiring the periodic full-sweep reaper into the live daemon loop — that is the
  SEPARATE already-authored brief `brief_hooks_wire_disk_reapers_live_loop.md`
  (`reap_periodic_disk_battery` via `reap_orphaned_workdirs`); this brief only adds
  the de-allowlist side-effect to `reap_for_task` and inherits whatever live paths
  call it. Do NOT widen this brief to wire the sweep.
- Retroactively de-allowlisting the existing stale
  `planner_redraft_once_on_invalid_draft` line by hand (NEVER hand-edit the
  allowlist) — once armed, the reaper retires spent slugs on its own; the stale
  line is cited only as PROOF the gap is real.
- Changing the reap GATE (whole-plan-integrated / non-epic / unique-pair), the
  archive move, the `git rm --cached` staging, or `_integrated_task_ids`. The
  de-allowlist is purely additive and rides the existing reap decision.
- Auto-deleting or gitignoring scratch dirs / research PDFs / `.superseded` files
  (a separate brief / owner judgment call).

# Deliverables

## TASK 1 — dealllowlist-spent-brief-on-reap-oracle (test_authoring; tools/brief_reaper.py)
The test_authoring stage authors a RED behavioral oracle (NO production edit in
this task). It MUST be a hermetic test that builds a fake repo root under a
`tmp_path` (its own `state/impl_progress.jsonl`, root brief+plan pair, and
`state/control/autowork/auto_promote.allowlist`) and asserts the de-allowlist
BEHAVIOR + default-OFF + comment-preservation + exact-match + live-protection —
NOT a frozen-literal comparison and NOT satisfiable by hardcoding.

ANTI-GAMING ORACLE REQUIREMENTS (the oracle MUST, and MUST NOT leak the answer
key — do NOT paste the impl source into the test, do NOT compare against a frozen
expected file blob):
- DEFAULT-OFF: with `JM_DEALLOWLIST_ON_REAP` UNSET (use `monkeypatch.delenv(...,
  raising=False)`), seed a fully-integrated brief+plan pair (both task_ids
  `accepted` in the ledger) AND an allowlist containing that slug plus a comment
  line and a SECOND live slug. Call `reap_for_task(root, <a-task-id>, stamp=...)`.
  Assert the pair IS archived (the existing behavior — the brief/plan moved into
  `_autowork_archive/<stamp>/reconciled/`) AND the allowlist file is BYTE-FOR-BYTE
  UNCHANGED (the spent slug line is still present when off). This is the
  load-bearing default-safe property and it must FAIL on today's code only if the
  impl wrongly de-allowlists when off — i.e. it pins the no-op default.
- ARMED + REAPED ⇒ DE-ALLOWLISTED: set `JM_DEALLOWLIST_ON_REAP=1`
  (`monkeypatch.setenv`), same seed, call `reap_for_task`. Assert the pair is
  archived AND the spent slug line is REMOVED from the allowlist, while the comment
  line and the other live slug remain present in their original order (parse the
  rewritten file with the SAME skip-comment/blank semantics as
  `_auto_promote_allowlist`). This is the core property and MUST FAIL on today's
  code (which never edits the allowlist).
- EXACT-MATCH (no substring/prefix drop): seed allowlist slugs `foo` and `foobar`
  and reap the pair whose slug is `foo`; assert only `foo` is removed and `foobar`
  survives.
- COMMENT / BLANK PRESERVATION: seed an allowlist with a header `#`-comment, a
  blank line, the spent slug, and a live slug; after an armed reap assert the
  header comment and blank line are preserved verbatim and only the spent slug
  line is gone.
- LIVE / PARTIALLY-INTEGRATED PROTECTION (safety invariant): seed a brief+plan
  pair whose tasks are NOT all `accepted` (one missing) AND its slug on the
  allowlist; arm the flag and call `reap_for_task`. Assert NEITHER the pair is
  archived NOR the slug removed (the reap gate fails first, so de-allowlist never
  runs). Also seed an EPIC brief+plan with its slug allowlisted; assert it is
  likewise neither archived nor de-allowlisted.
- FAIL-SAFE: with the flag armed and a valid reap, but the allowlist file ABSENT,
  assert `reap_for_task` still archives the pair and returns `[slug]` without
  raising (a missing allowlist is a no-op for the de-allowlist, never an error).
- IDEMPOTENCE / NO-DOUBLE: a second armed `reap_for_task` call on the
  already-archived/already-de-allowlisted slug is a clean no-op (returns `[]`, no
  error, allowlist unchanged the second time).
The oracle MUST derive expectations from the on-disk allowlist + archive effects,
exercise the live `reap_for_task` behavior, and MUST NOT special-case a known slug
string in the test logic.

`non_goals` MUST contain the literal word `integration`. `regression_tests >= 2`.

- `task_id: dealllowlist-spent-brief-on-reap-oracle`
- `priority: high`
- `meta_task_type: test_authoring`
- `files_touched: ["tests/test_brief_reaper_deallowlist.py"]`
  (the RED oracle file; the test_authoring stage stages `tools/brief_reaper.py` as
  the module-under-test)
- `mutation_target: tools/brief_reaper.py`  (MODULE-only dotted path; the test
  exercises this module)
- `dependencies: []`
- `verification_command:` `python -m pytest tests/test_brief_reaper_deallowlist.py -q`
  (RED against HEAD — `_deallowlist_slug` does not yet exist and `reap_for_task`
  never edits the allowlist; do NOT use a broad `tests/adversarial/ -q` vcmd).

## TASK 2 — dealllowlist-spent-brief-on-reap-impl (tools/brief_reaper.py)

IMPLEMENTATION NOTES (LOAD-BEARING — GENERAL correct behavior, NOT
fixture-matching):

1. PATCH SHAPE: emit a `__JANUSMASK_PATCHES__` SYMBOL patch. TWO symbols change:
   - ADD the NEW top-level helper `_deallowlist_slug` — land it via an R-ANCHORED
     enclosing patch on an existing top-level symbol (anchor on `reap_for_task` or
     `_integrated_task_ids`) so a brand-new module-level symbol lands correctly (a
     standalone new-symbol patch with no anchor fails patch-apply with an opaque
     `auto_commit_failed` — the program's new-symbol R-anchor rule).
   - EDIT the EXISTING `reap_for_task` to call the helper on the reap branch.
   Do NOT emit `__JANUSMASK_MANIFEST__` (single existing file, symbol patches —
   not whole-file).

2. NEW helper `_deallowlist_slug(repo_root, slug) -> bool`:
   - FAIL-SAFE / DEFAULT-OFF arming: armed iff the `JM_DEALLOWLIST_ON_REAP` env var
     is truthy. Use a CONSERVATIVE truthiness coercion (a non-empty value other
     than `'0'`/`'false'`/`'no'`/`''`, case-insensitive — mirror the existing
     `_watchdog_truthy` shape in `harness/state_reconciler.py:1152` conceptually,
     but DEFINE it inline here; do NOT import a harness internal just for this).
     With the env unset/falsey -> return False immediately, touch NOTHING.
   - When armed: resolve `path = Path(repo_root) / 'state' / 'control' / 'autowork'
     / 'auto_promote.allowlist'`. If it does not exist -> return False (no-op). Read
     its text; split into lines PRESERVING comments/blanks; DROP exactly the lines
     whose `.strip()` equals `slug` (skip-equality on non-comment, non-blank lines
     only — a `#`-prefixed line is never matched, even if it contains the slug);
     keep every other line verbatim and in order. If NO line was dropped -> return
     False (idempotent no-op, do not rewrite). If a line was dropped -> rewrite the
     file ATOMICALLY (write to a temp file in the same dir, then `os.replace`),
     preserving the file's trailing-newline shape, and return True.
   - Wrap the WHOLE helper in a contained `try/except Exception: return False` so
     an unreadable/locked/permission-denied allowlist never raises.
   - Do NOT acquire `state_reconcile_lock` inside the helper (its caller
     `reap_for_task` already holds it on the reap branch).

3. EDIT `reap_for_task`: INSIDE the existing
   `with state_reconcile_lock(state_dir):` block, AFTER the `for name in moved:
   _stage_deletion(root, name)` loop and BEFORE the block exits / `return [slug]`,
   add a CONTAINED call:
        try:
            _deallowlist_slug(root, slug)
        except Exception:
            pass
   The helper is gated OFF internally, so this is a strict no-op until the operator
   arms the flag — `reap_for_task`'s current archive behavior is byte-for-byte
   unchanged by default. Keep the entire existing reap branch (gate, moves,
   `_stage_deletion`, `return [slug]`) otherwise byte-identical. Do NOT move the
   call outside the lock, do NOT change the `archive=False` early-return branch
   (a dry-run must NOT de-allowlist), and do NOT change the function signature.

4. GENERALITY: the arming check is the GENERAL env-truthiness pattern, NOT a
   hardcoded environment string match or a special-cased slug; the line-drop is the
   GENERAL exact-strip-equality rule, NOT a match against any fixture slug. Do NOT
   key the helper on any task_id, plan field, or hardcoded slug string.

`non_goals` MUST contain the literal word `integration`. `regression_tests >= 2`.

- `task_id: dealllowlist-spent-brief-on-reap-impl`
- `priority: high`
- `meta_task_type: io_adapter`
- `files_touched: ["tools/brief_reaper.py"]`
- OMIT `mutation_target` (this is an impl task editing a module path, not a
  test_authoring task).
- `dependencies: ["dealllowlist-spent-brief-on-reap-oracle"]` (the RED oracle must
  exist first; the impl turns it green — preserve the red pair).
- Emit a `__JANUSMASK_PATCHES__` SYMBOL patch: the NEW `_deallowlist_slug`
  (R-anchored on `reap_for_task` or `_integrated_task_ids`) + the EDIT to
  `reap_for_task`.
- `verification_command:` a SCOPED, non-vacuous pytest selecting the new oracle
  AND a slice of the existing brief_reaper / reconciler suite that must stay green,
  e.g.
  `python -m pytest tests/test_brief_reaper_deallowlist.py tests/harness/test_reap_spent_briefs_parity.py tests/harness/test_reconciler_reaps_spent_briefs.py -q`
  (do NOT use a broad `pytest tests/adversarial/ -q` vcmd — it is non-hermetic and
  flaky-blocks). Run the EXACT vcmd yourself before dispatch and confirm
  `N passed` with N>=2 and that the existing reaper tests are NOT regressed.

# Required plan shape
Emit EXACTLY TWO tasks (pin via
`required_task_ids: [dealllowlist-spent-brief-on-reap-oracle, dealllowlist-spent-brief-on-reap-impl]`).
PRIORITY MUST be canonical lowercase (`high`), NEVER P0/P1/ints/Capitalized. The
oracle task is `test_authoring` (writes the RED test + carries `mutation_target:
tools/brief_reaper.py`, MODULE dotted path only); the impl task is `io_adapter`
(writes the single `tools/brief_reaper.py` path, OMITS `mutation_target`). Each
emits a `__JANUSMASK_PATCHES__` SYMBOL patch (the oracle writes a NEW test file;
the impl R-anchors the new helper). Each task's `non_goals` MUST contain the
literal word `integration`; each `regression_tests >= 2`. The impl `dependencies`
on the oracle so the red pair is preserved (oracle RED-before, impl GREEN-after).
Do NOT add any task touching a file other than the one its `files_touched`
declares; do NOT add a task editing `autowork_daemon.py`, `state_reconciler.py`,
`orchestrator_worker.py`, the allowlist file, or `config.yaml`.

`tools/brief_reaper.py` is NOT a sensitive apply glob and NOT in
`_NEVER_AUTO_APPROVE`, so neither task needs an operator decision file; the
ordinary non-sensitive apply path covers both.
