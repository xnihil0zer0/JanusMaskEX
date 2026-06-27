---
working_dir: "/home/xnihil0zer0/JanusMaskJR"
operator_decision_required: false
auto_approve_requested: true
required_task_ids:
  - centralize-required-survival-oracle
  - centralize-required-survival-impl
interfaces: >
  Close the SYSTEMIC plan-normalization drop hole once, at a single choke-point,
  instead of bolting a per-function `required_task_ids` guard onto each of N drop
  passes (the per-function approach has already been proven incomplete: even with
  `_drop_redundant_precommitted_oracles` guarded by 9f54746, the SIBLING pass
  `_drop_committed_module_impls` still drops the same committed-module pair first,
  and `_dedupe_oracles` + `_split_multifile_module_tasks` carry NO guard at all).

  Add ONE deterministic, additive choke-point to `normalize_plan`
  (harness/planner/plan_normalizer.py:1335): BEFORE any pass runs, snapshot the
  brief-required tasks by id from the input plan; AFTER every pass has run, for each
  required id that is NO LONGER present in `normalized['tasks']` and whose original
  task dict was snapshotted, RESTORE that original task dict (de-duplicated, appended
  in stable original order). This makes the normalizer honor the invariant "a
  brief-pinned task is NEVER silently dropped by normalization" regardless of WHICH
  pass dropped it — present passes and any FUTURE drop pass alike — so `validate_plan`
  never raises `missing_required_task` for a normalizer-induced drop and the daemon
  never parks such a leaf `deterministic:true`.

  TWO tasks editing exactly ONE existing file (harness/planner/plan_normalizer.py) via
  a single `__JANUSMASK_PATCHES__` SYMBOL recipe (ONE pre-existing top-level symbol
  `normalize_plan` + ONE new top-level helper `_restore_dropped_required_tasks`
  R-anchored on `normalize_plan`), plus ONE paired RED test_authoring oracle.

  (1) centralize-required-survival-oracle (test_authoring):
      RED behavioral oracle proving that `normalize_plan(..., required_task_ids=[...])`
      RETAINS a brief-pinned task that the underlying passes drop — across the THREE
      empirically-confirmed drop shapes (committed-module impl+oracle pair,
      duplicate-oracle collapse, and a non-required clobber that MUST still drop). RED
      on HEAD (today `_dedupe_oracles` and `_drop_committed_module_impls` drop the
      pinned task and `normalize_plan` returns a plan missing it).

  (2) centralize-required-survival-impl (harness/planner/plan_normalizer.py):
      Add the `_restore_dropped_required_tasks` helper and call it as the FINAL step of
      `normalize_plan` (after all passes, before the strip/priority finalizers run on
      the restored set). PURE, deterministic, additive. `plan_normalizer.py` is NOT in
      `_NEVER_AUTO_APPROVE` -> auto-approve-eligible.
---

# Title
Centralize `required_task_ids` survival in `normalize_plan` so NO plan-normalization
pass (present or future) can silently drop a brief-pinned task — eliminating the
systemic, deterministic `missing_required_task` rc=1 that parks such leaf briefs
forever, instead of patching each drop pass one at a time.

# Scope
TWO tasks. ONE `harness_self_fix` impl task (one `harness/**` file:
harness/planner/plan_normalizer.py) and ONE paired `test_authoring` oracle. READ each
file FIRST.

1. `centralize-required-survival-oracle` (test_authoring) authors a RED behavioral
   oracle in `tests/harness/test_normalize_required_task_survival.py` against
   `normalize_plan` in `harness/planner/plan_normalizer.py`. NO production edit in this
   task.

2. `centralize-required-survival-impl` edits `harness/planner/plan_normalizer.py` to add
   a `_restore_dropped_required_tasks` helper and invoke it as the final restoration
   step inside `normalize_plan`. `harness/planner/plan_normalizer.py` is NOT in
   `_NEVER_AUTO_APPROVE` (the irreducible set is `harness/agent_jail.py`,
   `harness/dbus_proxy.py`, `harness/paths.py`, `harness/git_integration.py`,
   `harness/orchestrator.py`, `harness/interceptors.py`, `harness/selfheal.py`,
   `harness/autowork_daemon.py`, `services/**` — see harness/orchestrator.py:2651), so
   this task is auto-approve-eligible (`operator_decision_required: false`,
   `auto_approve_requested: true`). NO operator decision file is required.

This is a ROOT-CAUSE harness fix per "fixes-are-permanent-and-reusable" and
"turn-recurring-failures-into-pipeline-fixes": it removes the STRUCTURAL reason ANY
normalization pass can silently drop a brief-pinned task, rather than adding a guard to
each pass as the bug recurs.

# Background — the exact mechanism (analytic-script verified, with line anchors)

`normalize_plan(plan, repo_root=None, contracts=None, *, required_task_ids=None)` lives
at `harness/planner/plan_normalizer.py:1335`. It runs a SEQUENCE of mutation passes over
the plan's `tasks`. SEVERAL of those passes can REMOVE a task; the
`required_task_ids` enforcement was bolted on per-function INCONSISTENTLY, so multiple
passes still drop a brief-pinned task. Then `cli.main` (cli.py:494) calls
`normalize_plan(..., required_task_ids=getattr(brief_obj,'required_task_ids',None))`,
stamps `plan['required_task_ids']` via `_stamp_brief_metadata` (cli.py:495), and runs
`validate_plan` (cli.py:497); the `missing_required_task` check (plan_validator.py:338-342)
fires and the CLI exits rc=1 (cli.py:498-500). The daemon classifies rc!=0,!=124 as
`planner_validation_rejected` and parks the slug `deterministic:true`, re-failing every
cycle.

A 5-shape adversarial probe (run, output captured below) over the REAL functions in the
REAL production order (`normalize_plan(kwarg)` -> stamp `plan['required_task_ids']` ->
`validate_plan`) found:

  | pass                                   | accepts required_task_ids? | drops a pinned task in prod order? |
  | -------------------------------------- | -------------------------- | ---------------------------------- |
  | _drop_committed_module_impls           | NO (2-arg on HEAD)         | YES  (committed impl+oracle pair)  |
  | _dedupe_oracles                        | NO                         | YES  (non-min duplicate oracle)    |
  | _split_multifile_module_tasks          | NO (RENAMES the orig id)   | YES  (orig multi-file id vanishes) |
  | _drop_redundant_precommitted_oracles   | YES (9f54746 guard)        | no (guarded — when reached)        |
  | _force_smoke_gated_leaf_impl           | reads PLAN-DICT key only   | no (dissolved upstream; LATENT)    |

CAPTURED PROBE OUTPUT (the load-bearing RED evidence — deterministic, no LLM/clock/net):

    A — _drop_committed_module_impls: committed-module impl+oracle pair, pinned
      survivors=[]  missing_required_task=True  ["...missing required task_ids ... ['imp', 'orc']"]
    C — _dedupe_oracles: required NON-surviving duplicate oracle
      survivors=['orc_a']  missing_required_task=True  ["...missing ... ['orc_z']"]
    D — _split_multifile_module_tasks: required multi-file impl id
      survivors=['multi__a', 'multi__b']  missing_required_task=True  ["...missing ... ['multi']"]
    B — _drop_redundant_precommitted_oracles (guard in isolation):
      UNPINNED ['impB'] (orcB dropped); PINNED ['impB','orcB'] (orcB kept)
    E — _force_smoke_gated_leaf_impl:
      bare (no dict key) drops orcE; (dict-key pin) keeps orcE; PRODUCTION normalize_plan
      keeps orcE because _sanitize_impl_verification_commands dissolves the share upstream.

WHY A CENTRALIZED CHOKE-POINT (not N per-function guards): the per-function approach is
DEMONSTRABLY INCOMPLETE. Commit 9f54746 added the guard to
`_drop_redundant_precommitted_oracles` only; a SECOND brief
(`keep_committed_impl_required_task`) is needed for `_drop_committed_module_impls`; and
`_dedupe_oracles` + `_split_multifile_module_tasks` STILL carry no guard. Worse, even a
fully-guarded `_drop_redundant` is MASKED in the full pipeline: for a committed-module
pair, `_drop_committed_module_impls` drops it FIRST, so guarding one pass does not
protect the scenario. Each new drop pass added in future is a fresh hole. A single
post-pass restoration in `normalize_plan` makes the survival invariant hold for ALL
passes at once and for any future pass, with O(1) maintenance.

WHY RESTORATION (not "skip the drop") at the choke-point: the passes legitimately drop
NON-required tasks (real clobbers, real duplicates) — that behavior MUST be preserved.
A post-pass restoration touches ONLY tasks that (a) are brief-pinned AND (b) were
dropped, re-adding the ORIGINAL task dict. For a pure-drop pass (A, C) this fully
restores the pinned task. For the RENAME pass (D), the original `multi` task dict is
restored ALONGSIDE the split `multi__a`/`multi__b` tasks; that is acceptable and SAFE
(the brief pinned `multi`, so re-materializing it satisfies the pin; the split children
remain), and it is strictly better than today's silent rc=1 park. (A future refinement
could teach `_split` to not rename a pinned id, but that is OUT OF SCOPE here.)

PROVENANCE (proves these are real introduced defects, not a misread):
  - `_dedupe_oracles` (UNGUARDED) — introduced commit `6ba723e`
    (impl-plan-normalizer, 2026-06-05).
  - `_drop_committed_module_impls` (UNGUARDED on HEAD) — introduced commit `32f85ab`
    (planner-committed-module-dedup-impl, 2026-06-13).
  - `_split_multifile_module_tasks` (UNGUARDED, drops-via-rename) — introduced commit
    `a7091b0` (split_multifile_module_tasks_impl, 2026-06-13).
  - `_drop_redundant_precommitted_oracles` GUARD — added commit `9f54746`
    (keep-required-oracle-normalize-core-impl, 2026-06-25) — guards ONE pass only.

# Inputs
READ these files FIRST in `/home/xnihil0zer0/JanusMaskJR`:

- `harness/planner/plan_normalizer.py` — the file TASK 2 edits (NOT trust-core).
  VERIFIED current state:
  - `normalize_plan(plan, repo_root=None, contracts=None, *, required_task_ids=None)`
    at line ~1335. It deep-copies `plan` into `normalized`, extracts `tasks =
    normalized.get('tasks')`, computes `req_ids` at lines ~1354-1356 (`req_ids =
    required_task_ids; if req_ids is None: req_ids =
    normalized.get('required_task_ids')`), then runs the pass sequence
    (lines ~1357-1374) ending with `_strip_stray_mutation_targets` and
    `_normalize_task_priorities`, and finally `return normalized` at line ~1375.
  - The id helper to reuse: `_task_id(task)` at line ~33 (returns the task's id as a
    str, '' when absent). Reuse it; do NOT reimplement.
  - The `req_set` coercion to MIRROR is the one in
    `_drop_redundant_precommitted_oracles` (lines ~925-931):
        if isinstance(required_task_ids, str):
            req_set = {s.strip() for s in required_task_ids.split(',') if s.strip()}
        elif isinstance(required_task_ids, (list, tuple, set)):
            req_set = {r for r in required_task_ids if isinstance(r, str)}
        else:
            req_set = set()

- `harness/planner/plan_validator.py` — DO NOT EDIT (read for context only). The
  `missing_required_task` check is at lines ~338-342 (`required =
  plan.get('required_task_ids') or []` -> any pinned id not in `seen_task_ids` ->
  `PlanViolation('missing_required_task', ...)`). This is what fires today when a pass
  drops a pinned task.

- `harness/planner/cli.py` — DO NOT EDIT (read for context only). `main` calls
  `normalize_plan(..., required_task_ids=getattr(brief_obj,'required_task_ids',None))`
  (line ~494), then `_stamp_brief_metadata` (line ~495 — stamps
  `plan['required_task_ids']`), then `validate_plan` (line ~497) and `sys.exit(1)` on
  any violation (line ~500). So once the pinned tasks are RESTORED inside
  `normalize_plan`, validation passes and the CLI exits 0.

- existing `tests/harness/test_drop_committed_module_impls_required.py` and any
  `tests/*plan_normalizer*` — DO NOT EDIT (read for the established pattern: build
  `tasks` lists of plain dicts + a tmp git repo with committed module files, call the
  function, assert on the surviving task ids).

# Non-Goals
Integration is out of scope (the literal word `integration` MUST appear in this section
and in EACH task's `non_goals` to excuse the integration-test requirement). Specifically
OUT OF SCOPE:
- Editing or REMOVING the existing per-function guards
  (`_drop_redundant_precommitted_oracles`, `_force_smoke_gated_leaf_impl`,
  `_drop_committed_module_impls`); the choke-point is ADDITIVE and complements them. A
  per-function guard that fires first simply means the choke-point finds nothing to
  restore.
- Changing the DROP DETECTION of any pass (HEAD probes, dedup grouping, multi-file
  split, smoke-collapse). A genuine NON-required clobber/duplicate is STILL dropped
  exactly as today; only a brief-PINNED dropped task is restored.
- Teaching `_split_multifile_module_tasks` to avoid renaming a pinned id (a possible
  future refinement); this brief only RESTORES the original pinned task post-pass.
- Editing `harness/planner/plan_validator.py`, `harness/planner/cli.py`,
  `harness/orchestrator.py`, `harness/autowork_daemon.py`, or ANY file other than the
  one each task's `files_touched` declares.
- Any external-corpus integration or network access; the oracle uses in-memory dicts +
  a hermetic local tmp git repo only.

# Deliverables

## TASK 1 — centralize-required-survival-oracle (test_authoring; harness/planner/plan_normalizer.py)
The test_authoring stage authors a RED behavioral oracle (NO production edit). It imports
`harness.planner.plan_normalizer` and calls `normalize_plan` directly (or loads the
edited module via `importlib` from a `tmp_path` copy) — NEVER `exec`/`eval`/`__import__`
(AST-banned). It is hermetic: build a `tmp_path` git repo
(`subprocess.run(['git','init',...])`, write+commit module files) so the HEAD probes in
`_drop_committed_module_impls` resolve; build `tasks` lists of plain dicts in-memory; no
real `state/`, no network.

ANTI-GAMING ORACLE REQUIREMENTS (derive expectations from the REAL `normalize_plan`
mutation; do NOT paste impl source into the test, do NOT assert a frozen literal of the
function body):
- PINNED COMMITTED-MODULE PAIR IS RETAINED (load-bearing RED #1): in a tmp git repo
  commit `pkg/mod.py`. Build an impl `{'task_id':'imp',
  'meta_task_type':'validation', 'files_touched':['pkg/mod.py'], 'dependencies':[],
  'verification_command':'python -c "import pkg.mod"'}` (vcmd does NOT name the oracle's
  test file) and a paired oracle `{'task_id':'orc',
  'meta_task_type':'test_authoring', 'mutation_target':'pkg.mod',
  'files_touched':['tests/test_mod.py'], 'dependencies':['imp'],
  'verification_command':'python -m pytest tests/test_mod.py'}`. Call
  `normalize_plan({'tasks':[imp,orc]}, repo_root=<tmp repo>,
  required_task_ids=['imp','orc'])`. Assert BOTH `'imp'` and `'orc'` are present in the
  returned `plan['tasks']`. RED on HEAD (today `_drop_committed_module_impls` drops both).
- PINNED DUPLICATE ORACLE IS RETAINED (load-bearing RED #2): two `test_authoring`
  oracles with the SAME `mutation_target` `pkg.mod` but different ids `orc_a` / `orc_z`
  and different `files_touched` (`tests/test_a.py` / `tests/test_z.py`). Pin the
  NON-min one: `required_task_ids=['orc_z']`. Call `normalize_plan` and assert `'orc_z'`
  is STILL present. RED on HEAD (today `_dedupe_oracles` keeps `min(task_id)`=`orc_a`
  and drops `orc_z`).
- NON-REQUIRED DROP STILL FIRES (no over-retention): the SAME duplicate-oracle pair with
  `required_task_ids=None` (or pinning neither) -> assert exactly ONE of `orc_a`/`orc_z`
  survives (the dedup still collapses). This proves the choke-point restores ONLY
  brief-pinned tasks and preserves normal dedup/clobber behavior.
- DETERMINISM: calling `normalize_plan` twice on equivalent inputs yields the same
  surviving id SET. PURITY: the oracle runs fully offline against in-memory dicts + a
  local tmp git repo (no network).
The oracle MUST derive expectations from the live `normalize_plan` mutation of the plan
it builds, MUST NOT paste the impl into the test, and MUST NOT assert a frozen
function-body literal.

`non_goals` MUST contain the literal word `integration`. `regression_tests >= 2`.

- `task_id: centralize-required-survival-oracle`
- `priority: high`
- `meta_task_type: test_authoring`
- `files_touched: ["tests/harness/test_normalize_required_task_survival.py"]`
- `mutation_target: harness/planner/plan_normalizer.py`  (MODULE-only dotted path; the
  test exercises `normalize_plan` in this module)
- `dependencies: []`
- `verification_command:` `python -m pytest tests/harness/test_normalize_required_task_survival.py -q`
  (RED against HEAD; do NOT use a broad `pytest tests/adversarial/ -q` vcmd).

## TASK 2 — centralize-required-survival-impl (harness/planner/plan_normalizer.py)

NOT TRUST-CORE: `harness/planner/plan_normalizer.py` is NOT in `_NEVER_AUTO_APPROVE`
(harness/orchestrator.py:2651), so this task is auto-approve-eligible
(`auto_approve_requested: true`, `operator_decision_required: false`). NO operator
decision file is required.

IMPLEMENTATION NOTES (LOAD-BEARING — GENERAL behavior, minimal surface):

1. PATCH SHAPE — this task edits an EXISTING multi-symbol harness file, so it MUST carry
   the `__JANUSMASK_PATCHES__` recipe and NOT a whole-file rewrite (else it hits the
   `whole_file_drift` reject). Submit a single top-level `__JANUSMASK_PATCHES__` list
   with EXACTLY TWO `{'kind':'symbol', 'name':..., 'code': r'''...'''}` entries:
     - Entry A: `name: 'normalize_plan'` (PRE-EXISTING top-level symbol; NO R-anchor).
     - Entry B: `name: '_restore_dropped_required_tasks'` (NEW top-level helper). A
       brand-new top-level symbol via `__JANUSMASK_PATCHES__` MUST carry an R-ANCHOR on
       an EXISTING top-level symbol or patch-apply fails with an opaque
       `auto_commit_failed` (per "new-symbol-needs-r-anchor-or-autocommit-fails"). Anchor
       Entry B on `normalize_plan` (e.g. `'anchor': 'normalize_plan'`, placed AFTER it).
   Do NOT emit `__JANUSMASK_MANIFEST__` (single existing file).

2. THE NEW HELPER — `_restore_dropped_required_tasks(normalized, original_tasks, req_ids)`:
   - Pure, deterministic, no I/O. Signature accepts the normalized plan dict, the
     ORIGINAL `tasks` list (a snapshot taken BEFORE any pass mutated it), and the
     resolved `req_ids` (str/list/tuple/set/None).
   - Coerce `req_ids` to a `req_set` using the SAME coercion as
     `_drop_redundant_precommitted_oracles` (str -> split on comma; list/tuple/set ->
     str members; else empty). If `req_set` is empty, return `normalized` unchanged.
   - Build `present = {_task_id(t) for t in normalized.get('tasks') or [] if
     isinstance(t, dict)}`.
   - Build an `orig_by_id` map `{_task_id(t): t for t in original_tasks if
     isinstance(t, dict) and _task_id(t)}` (first occurrence wins; iterate in original
     order so restoration order is stable).
   - For each `rid` in `req_set` that is NOT in `present` AND IS in `orig_by_id`:
     append a DEEP COPY (`copy.deepcopy`) of `orig_by_id[rid]` to
     `normalized['tasks']`, and add `rid` to `present` (so a duplicated required id is
     restored at most once). Preserve original task order of restoration by iterating
     `original_tasks` and restoring those whose id is in `req_set` and missing, rather
     than iterating the unordered `req_set`.
   - A required id that is neither present NOR in the original snapshot (never existed)
     is left alone (the choke-point does not invent tasks — that is a genuine planner
     omission `validate_plan` should still catch).
   - Return `normalized`. Guard against `normalized` not being a dict / `tasks` not
     being a list (return unchanged).

3. THE EDIT — `normalize_plan`:
   - IMMEDIATELY after `tasks = normalized.get('tasks')` is confirmed a list and
     `req_ids` is resolved (lines ~1353-1356), capture an ORIGINAL snapshot BEFORE any
     pass mutates it: `original_tasks = copy.deepcopy(tasks)` (so later in-place passes
     cannot corrupt the snapshot). `copy` is already imported at module top.
   - Leave the existing pass sequence (lines ~1357-1374) BYTE-UNCHANGED.
   - As the FINAL step, AFTER `_strip_stray_mutation_targets` and
     `_normalize_task_priorities` (so the restored tasks are NOT re-stripped — restore
     the ORIGINAL, fully-formed task), and BEFORE `return normalized`, call:
         normalized = _restore_dropped_required_tasks(normalized, original_tasks, req_ids)
     (Placing the restore AFTER the finalizers is deliberate: a restored task is the
     verbatim brief-authored task, which already satisfies the schema; re-running the
     finalizers on it is unnecessary and risks re-stripping a legitimately-present
     `mutation_target` on a restored oracle.)
   - Reproduce the rest of `normalize_plan` BYTE-UNCHANGED.

4. GENERALITY: do NOT special-case any module path, slug, task_id, vcmd, or pass name.
   The restoration is driven SOLELY by `req_set` membership + drop detection (id absent
   from output but present in the original snapshot), so it covers EVERY current drop
   pass and any FUTURE one.

5. NO-REGRESSION: when `req_ids` is None/empty (no brief pin), `req_set` is empty, the
   helper returns immediately, and every pass behaves EXACTLY as today (a non-required
   clobber/duplicate is still dropped). When a pinned task was NEVER dropped, `present`
   already contains it and nothing is appended (idempotent no-op).

ANTI-GAMING ORACLE REQUIREMENT (TASK 2): the impl must make the TASK 1 oracle GREEN by
the GENERAL restoration over the synthetic plans, NOT by detecting the fixture. Re-run
the EXACT TASK 1 vcmd plus existing plan_normalizer tests
(`tests/harness/test_drop_committed_module_impls_required.py`,
`tests/harness/test_planner_priority_normalize.py`) before dispatch and confirm none
regress.

`non_goals` MUST contain the literal word `integration`. `regression_tests >= 2`.

- `task_id: centralize-required-survival-impl`
- `priority: high`
- `meta_task_type: harness_self_fix`
- `files_touched: ["harness/planner/plan_normalizer.py"]`
- OMIT `mutation_target` (impl task editing a `harness/**` path).
- `dependencies: ["centralize-required-survival-oracle"]` (RED oracle first; impl turns
  it green — red-pair preserved).
- Emit a `__JANUSMASK_PATCHES__` SYMBOL recipe with TWO entries (`normalize_plan` +
  the new `_restore_dropped_required_tasks` R-anchored on `normalize_plan`), each
  reproduced VERBATIM apart from the noted change.
- AUTO-APPROVE-ELIGIBLE: `harness/planner/plan_normalizer.py` is NOT in
  `_NEVER_AUTO_APPROVE`; NO operator decision file is required.
- `verification_command:` a SCOPED, non-vacuous pytest selecting the new oracle:
  `python -m pytest tests/harness/test_normalize_required_task_survival.py -q`
  (do NOT use a broad `pytest tests/adversarial/ -q` vcmd). Run the EXACT vcmd yourself
  before dispatch and confirm `N passed` with N>=2 and that existing plan_normalizer
  tests are NOT regressed.

# Required plan shape
Emit EXACTLY TWO tasks (pin via `required_task_ids: [
centralize-required-survival-oracle, centralize-required-survival-impl]`). PRIORITY MUST
be canonical lowercase (`high`), NEVER P0/P1/ints/Capitalized.
  - TASK 1 is `test_authoring` (writes the RED oracle for `normalize_plan`; carries
    `mutation_target: harness/planner/plan_normalizer.py`, MODULE dotted path only).
  - TASK 2 is `harness_self_fix` (writes `harness/planner/plan_normalizer.py`, OMITS
    `mutation_target`; depends on TASK 1). It is NOT trust-core; auto-approve-eligible
    with NO operator decision file.
The impl task emits a `__JANUSMASK_PATCHES__` SYMBOL recipe (TWO symbol entries: an EDIT
of `normalize_plan` + a NEW R-anchored `_restore_dropped_required_tasks`, NOT a
manifest). Each task's `non_goals` MUST contain the literal word `integration`; each
`regression_tests >= 2`. Do NOT add any task touching a file other than the one its
`files_touched` declares; do NOT add a task editing `plan_validator.py`, `cli.py`,
`orchestrator.py`, or `autowork_daemon.py`.

`harness/planner/plan_normalizer.py` is NOT in the irreducible `_NEVER_AUTO_APPROVE` set
(`harness/agent_jail.py`, `harness/dbus_proxy.py`, `harness/paths.py`,
`harness/git_integration.py`, `harness/orchestrator.py`, `harness/interceptors.py`,
`harness/selfheal.py`, `harness/autowork_daemon.py`, `services/**`), so TASK 2 is
auto-approve-eligible and requires NO operator decision file.
