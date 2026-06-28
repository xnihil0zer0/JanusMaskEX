---
working_dir: "/home/xnihil0zer0/AI-Data/JanusMaskEX"
operator_decision_required: false
auto_approve_requested: true
required_task_ids:
  - committed-impl-drop-mode-aware-oracle
  - committed-impl-drop-mode-aware-impl
interfaces: >
  Durable root-cause hardening of `_drop_committed_module_impls`
  (harness/planner/plan_normalizer.py:1012): make the committed-module drop
  fire ONLY on a genuine CLOBBER (an impl PAIRED WITH A test_authoring oracle
  whose `mutation_target` RE-CREATES a module already committed at HEAD), and
  NEVER on an ordinary fix-forward EDIT of an existing module. Today the drop
  conflates "edit an existing ngv2/*.py" with "clobber a module another brief
  built"; with 213 ngv2 modules already at HEAD, EVERY future NGv2-closure leaf
  that edits an existing module AND pairs it with that module's oracle is at
  risk of a silent impl+oracle drop -> `missing_required_task` rc=1 -> the brief
  is parked `deterministic:true`. The just-landed `required_task_ids` guard
  (keep_committed_impl_required_task) is a correct but OPT-IN mitigation: it only
  protects tasks the brief explicitly PINS. A leaf that forgets to pin, or whose
  impl uses a non-fix-forward (smoke) vcmd, is STILL silently dropped. This
  brief narrows the DETECTION so the drop is sound regardless of pinning: a
  clobber requires the paired oracle to be RE-CREATING the module (its
  `files_touched` includes the module .py, i.e. it writes the module file
  itself), not merely TESTING it (oracle `files_touched` is a tests/ file). An
  oracle whose only `files_touched` is a tests/** path can never clobber the
  module, so its paired impl is a legitimate edit and MUST NOT be dropped.

  TWO tasks editing exactly ONE existing file
  (harness/planner/plan_normalizer.py) via a single `__JANUSMASK_PATCHES__`
  SYMBOL recipe (one pre-existing top-level symbol), plus ONE paired RED
  test_authoring oracle.
---

# Title
Make `_drop_committed_module_impls` CLOBBER-aware so an ordinary fix-forward EDIT
of an existing module (paired with a tests/-only oracle) is never dropped —
eliminating the edit-existing misfire class at its root, not just for
`required_task_ids`-pinned leaves.

# Scope
TWO tasks. ONE `harness_self_fix` impl task (one `harness/**` file:
harness/planner/plan_normalizer.py) and ONE paired `test_authoring` oracle. READ
each file first. This is a ROOT-CAUSE harness fix per the
"fixes-are-permanent-and-reusable" and "turn-recurring-failures-into-pipeline-fixes"
rules. It is COMPLEMENTARY to the landed `keep_committed_impl_required_task`
guard (commit-pinned protection): that guard stays; this brief additionally
makes the underlying DETECTION sound so an unpinned fix-forward leaf is also
safe.

# Background — the exact mechanism (analytic-script verified)

`_drop_committed_module_impls(plan, repo_root)` at
harness/planner/plan_normalizer.py:1012 is intended to drop a *re-build clobber*:
an impl that RE-CREATES a module a DIFFERENT brief already committed at HEAD,
together with that clobber's paired test_authoring oracle. The detection
(lines ~1056-1087):

  - builds `oracle_modules` = {`_module_path(_mutation_target(oracle))` ->
    [oracle, ...]} over every test_authoring task;
  - for every impl task whose `files_touched` names a path that EXISTS at HEAD,
    looks up a paired oracle by that path;
  - if found (and the fix-forward-vcmd escape at ~1081-1083 does NOT fire), adds
    BOTH the impl AND the paired oracle to `drop_ids`.

THE ROOT DEFECT: "an oracle whose `mutation_target` maps to the impl's
HEAD-existing module" is TRUE for EVERY ordinary red-pair that edits an existing
module — the oracle's `mutation_target` is the module-under-test by design. So
the heuristic cannot distinguish:
  (A) a genuine CLOBBER — the paired oracle actually WRITES the module file (its
      `files_touched` lists the module .py), re-creating it; from
  (B) a fix-forward EDIT — the paired oracle only TESTS the module (its
      `files_touched` is a `tests/**` file) and the impl edits the existing
      module.
Both look identical to the current code, so case (B) is wrongly dropped.

ANALYTIC EVIDENCE (Adversarial Auditor #4, 2026-06-25, scratchpad scripts over
the LIVE /home/xnihil0zer0/NobleGreedv2 HEAD):
  - The c7 brief's `c7c-seams-env-phase-impl` (files_touched
    `ngv2/conductor_seams.py`, IN HEAD) + paired oracle
    `c7c-fsm-live-integration-oracle` (mutation_target `ngv2.conductor_seams`,
    files_touched `tests/ngv2/test_c7_complete_fsm_live.py`) — a pure fix-forward
    EDIT — is DROPPED by HEAD's 2-arg `_drop_committed_module_impls`, yielding a
    `missing_required_task` PlanViolation -> rc=1. (The landed
    `required_task_ids` guard now prevents this because c7 pins both ids; but an
    unpinned edit-existing leaf is still dropped.)
  - 213 ngv2/*.py modules already exist at HEAD
    (`git ls-tree -r --name-only HEAD -- ngv2/ | grep '\.py$' | wc -l` = 213), so
    nearly every remaining NGv2-closure leaf EDITS an existing module. The
    edit-existing misfire is the COMMON case, not the exception.
  - ROADMAP SURVEY (Auditor #4 sub-agent, 2026-06-25): ~6 upcoming NGv2-closure
    phases / ~10+ impl leaves (c7 itself, P2.2 `detonation_seam`, P3.1
    `authz_idor` ×3 modules, P3.3 `spawn_middle_phases`, P4.1
    `eligibility_typed_ledger`, P0.2-NGv2) ALL edit existing HEAD `ngv2/*.py`
    modules and thus share the c7 drop-bug class. The ONLY genuine create-new
    NGv2 modules remaining are the 6 `ngv2/workers/*.py` env-phase stubs created
    INSIDE c7. The roadmap docs labelling c4/c5/c6 handlers and the cP producers
    as "create-new" are STALE — those modules are already committed at HEAD, so
    any further touch is an EDIT. Conclusion: for the rest of NGv2 closure,
    edit-existing is essentially the ONLY mode, so the over-broad clobber
    detection is a recurring blocker the narrow `required_task_ids` pin only
    band-aids per-leaf.

THE FIX (narrow the clobber DETECTION, keep behavior for genuine clobbers): a
paired oracle only constitutes a clobber when it RE-CREATES the module — i.e. the
oracle's `files_touched` includes the HEAD-existing module path (`matched_path`).
An oracle whose `files_touched` is ONLY a `tests/**` path is a TEST, not a
re-creation, so its paired impl is a legitimate edit and must be KEPT. Restrict
`paired_oracles` (or the drop decision) to oracles whose `files_touched` includes
the matched HEAD path; if none remain, do NOT drop. This is STRICTLY narrower
(can only KEEP more) and preserves the original clobber protection for the real
re-build case (an oracle that writes the module file). It is orthogonal to and
composes with the landed `required_task_ids` guard.

PROVENANCE: `_drop_committed_module_impls` was introduced in commit `32f85ab`
(planner-committed-module-dedup-impl, 2026-06-13). The clobber it was built for
(NobleGreed-era multi-brief module re-creation) had oracles that WROTE the module;
the NGv2-closure edit-existing pattern (tests/-only oracles over a mature
213-module codebase) is what exposes the over-broad detection.

# Inputs
READ these files FIRST in `/home/xnihil0zer0/AI-Data/JanusMaskEX`:

- `harness/planner/plan_normalizer.py` — the file TASK 2 edits (NOT trust-core;
  NOT in `_NEVER_AUTO_APPROVE`, see harness/orchestrator.py:2651).
  VERIFIED current state of `_drop_committed_module_impls` (line ~1012):
  - The paired-oracle lookup loop builds `paired_oracles`/`matched_path` from
    `oracle_modules` keyed by `_module_path(_mutation_target(oracle))`
    (lines ~1072-1078).
  - The fix-forward-vcmd escape `continue` is at lines ~1081-1083.
  - The pair is added to `drop_ids` at lines ~1084-1087.
  - Helpers (reuse, do NOT reimplement): `_task_id` (~33), `_files_touched`
    (~38), `_mutation_target` (~46), `_is_test_authoring` (~50), `_module_path`
    (~29).
  - NOTE: after the landed `keep_committed_impl_required_task` brief lands, this
    function ALSO takes `*, required_task_ids=None` and skips a pinned pair. This
    brief's edit must compose with that guard (apply the clobber-narrowing
    BEFORE/INDEPENDENT of the req_set skip; both `continue` early).

- `harness/planner/plan_validator.py` — DO NOT EDIT (read for context). The
  `missing_required_task` check is at lines ~338-342.

- existing `tests/*plan_normalizer*` / `tests/harness/` — DO NOT EDIT existing
  tests (read for the established pattern: build `tasks` lists of plain dicts +
  a tmp git repo with a committed module file; call the function; assert on
  surviving ids).

# Non-Goals
Integration is out of scope (the literal word `integration` MUST appear in this
section and in EACH task's `non_goals` to excuse the integration-test
requirement). Specifically OUT OF SCOPE:
- Editing the `required_task_ids` guard added by
  `keep_committed_impl_required_task` (keep it; this brief is additive and
  composes with it).
- Editing `_drop_redundant_precommitted_oracles`, `_force_smoke_gated_leaf_impl`,
  `plan_validator.py`, `cli.py`, `orchestrator.py`, `autowork_daemon.py`, the
  c7 brief, or any file other than the one each task's `files_touched` declares.
- Changing the HEAD-membership probe, the telemetry marker, or the
  dependent-rewire block.
- Any external-corpus integration or network access; the oracle uses a hermetic
  local tmp git repo only.

# Deliverables

## TASK 1 — committed-impl-drop-mode-aware-oracle (test_authoring; harness/planner/plan_normalizer.py)
The test_authoring stage authors a RED behavioral oracle in
`tests/harness/test_drop_committed_module_impls_clobber_aware.py` against
`_drop_committed_module_impls`. It imports `harness.planner.plan_normalizer` and
calls `_drop_committed_module_impls` directly (or loads the edited module via
`importlib` from a `tmp_path` copy) — NEVER `exec`/`eval`/`__import__`
(AST-banned). Hermetic: build a `tmp_path` git repo (`git init`, write a module
file `pkg/mod.py`, `git add`+`git commit`) so `git cat-file -e HEAD:<rel>`
resolves; build `tasks` lists of plain dicts; no real `state/`, no network.

ANTI-GAMING ORACLE REQUIREMENTS (derive expectations from the function's REAL
mutation of the plan; do NOT paste impl source; do NOT assert a frozen function
body):
- FIX-FORWARD EDIT IS KEPT (the load-bearing RED case): commit `pkg/mod.py`.
  Build an impl `{'task_id':'imp','meta_task_type':'validation',
  'files_touched':['pkg/mod.py'],'dependencies':[],
  'verification_command':'python -c "import pkg.mod"'}` and a TESTS-ONLY oracle
  `{'task_id':'orc','meta_task_type':'test_authoring','mutation_target':'pkg.mod',
  'files_touched':['tests/test_mod.py'],'dependencies':['imp'],
  'verification_command':'python -m pytest tests/test_mod.py'}` (note the oracle's
  `files_touched` is a tests/ file, NOT `pkg/mod.py`). Call
  `_drop_committed_module_impls(plan, repo_root=<tmp git repo>)` (with NO
  `required_task_ids` — proving the fix is independent of pinning). Assert BOTH
  `'imp'` and `'orc'` SURVIVE. This MUST be RED on HEAD: today (even after the
  required_task_ids guard) an UNPINNED tests-only pair is DROPPED.
- GENUINE CLOBBER IS STILL DROPPED (no under-detection): the SAME committed
  module, but the paired oracle RE-CREATES it — its `files_touched` includes the
  module path `['pkg/mod.py','tests/test_mod.py']` (the oracle writes the module
  file). With NO `required_task_ids`, assert BOTH are DROPPED and the
  `normalizer_telemetry` reflects `duplicate_module_skipped:pkg/mod.py`. This
  proves the clobber protection is preserved for the real re-build case.
- NO HEAD MODULE IS A NO-OP: a tests-only pair whose module is NOT committed at
  HEAD -> assert nothing is dropped.
- COMPOSES WITH required_task_ids GUARD: a genuine-clobber pair that IS pinned in
  `required_task_ids` is STILL KEPT (the pin guard wins). [If the landed pin
  guard is present, assert this; otherwise SKIP this sub-assert gracefully.]
- DETERMINISM + PURITY: twice-called yields the same survivors; runs fully
  offline against a local tmp git repo.

`non_goals` MUST contain the literal word `integration`. `regression_tests >= 2`.

- `task_id: committed-impl-drop-mode-aware-oracle`
- `priority: high`
- `meta_task_type: test_authoring`
- `files_touched: ["tests/harness/test_drop_committed_module_impls_clobber_aware.py"]`
- `mutation_target: harness/planner/plan_normalizer.py` (MODULE-only dotted path)
- `dependencies: []`
- `verification_command:` `python -m pytest tests/harness/test_drop_committed_module_impls_clobber_aware.py -q`
  (RED against HEAD; do NOT use a broad `pytest tests/adversarial/ -q` vcmd).

## TASK 2 — committed-impl-drop-mode-aware-impl (harness/planner/plan_normalizer.py)

NOT TRUST-CORE: `harness/planner/plan_normalizer.py` is NOT in
`_NEVER_AUTO_APPROVE`, so this task is auto-approve-eligible
(`auto_approve_requested: true`, `operator_decision_required: false`). NO operator
decision file is required.

IMPLEMENTATION NOTES (LOAD-BEARING — GENERAL behavior, minimal surface):

1. PATCH SHAPE — this task edits an EXISTING multi-symbol harness file, so it
   MUST carry the `__JANUSMASK_PATCHES__` recipe and NOT a whole-file rewrite
   (else `whole_file_drift` reject). Submit a single top-level
   `__JANUSMASK_PATCHES__` list with EXACTLY ONE
   `{'kind':'symbol','name':'_drop_committed_module_impls','code': r'''...'''}`
   entry, reproducing the symbol VERBATIM except for the noted change. The target
   is a PRE-EXISTING top-level symbol, so NO R-anchor. Do NOT emit
   `__JANUSMASK_MANIFEST__`. Adds NO new top-level symbol.

2. THE EDIT — inside `_drop_committed_module_impls`, narrow the clobber match so
   a paired oracle counts ONLY when it RE-CREATES the matched HEAD module. After
   `matched_path` is resolved and `paired_oracles` is the non-empty list for that
   path (lines ~1072-1080), filter to RE-CREATING oracles:
       _recreating = [o for o in paired_oracles
                      if matched_path in _files_touched(o)]
       if not _recreating:
           continue
   and use `_recreating` (NOT the raw `paired_oracles`) for BOTH the
   fix-forward-vcmd escape check and the `drop_ids.add` loop, so a tests-only
   oracle (whose `files_touched` does NOT include the module path) never triggers
   a drop and its impl is kept. Reproduce the surrounding HEAD probe, the
   `required_task_ids` skip (if present from the landed guard), the telemetry
   append, the survivors filter, the dependent rewire, and the `except` clause
   BYTE-UNCHANGED apart from this narrowing.
   - Compose order: the `_recreating` narrowing and the existing
     `required_task_ids` skip BOTH `continue` the loop early; either firing keeps
     the pair. Apply the `_recreating` filter immediately after `matched_path`/
     `paired_oracles` are known and before the drop, so it is independent of the
     pin.

3. GENERALITY: do NOT special-case any module path, slug, task_id, or vcmd. The
   narrowing is driven solely by whether the paired oracle's `files_touched`
   includes the matched module path.

4. NO-REGRESSION: a genuine clobber (oracle re-creates the module, its
   `files_touched` includes the module .py) is dropped EXACTLY as today; only a
   tests-only fix-forward pair is now kept.

ANTI-GAMING ORACLE REQUIREMENT (TASK 2): the impl must make the TASK 1 oracle
GREEN by GENERAL behavior (the real `_recreating` filter over the synthetic
plan), NOT by detecting the fixture. Re-run the EXACT TASK 1 vcmd plus existing
plan_normalizer tests before dispatch and confirm none regress.

`non_goals` MUST contain the literal word `integration`. `regression_tests >= 2`.

- `task_id: committed-impl-drop-mode-aware-impl`
- `priority: high`
- `meta_task_type: harness_self_fix`
- `files_touched: ["harness/planner/plan_normalizer.py"]`
- OMIT `mutation_target` (impl editing a `harness/**` path).
- `dependencies: ["committed-impl-drop-mode-aware-oracle"]`
- Emit a `__JANUSMASK_PATCHES__` SYMBOL recipe with ONE entry
  (`_drop_committed_module_impls`), reproduced VERBATIM apart from the noted
  change.
- AUTO-APPROVE-ELIGIBLE: NOT in `_NEVER_AUTO_APPROVE`; NO operator decision file.
- `verification_command:` `python -m pytest tests/harness/test_drop_committed_module_impls_clobber_aware.py -q`
  (do NOT use a broad `pytest tests/adversarial/ -q` vcmd). Run the EXACT vcmd
  yourself before dispatch and confirm `N passed` with N>=2 and that existing
  plan_normalizer tests are NOT regressed.

# Required plan shape
Emit EXACTLY TWO tasks (pin via `required_task_ids:
[committed-impl-drop-mode-aware-oracle, committed-impl-drop-mode-aware-impl]`).
PRIORITY MUST be canonical lowercase (`high`), NEVER P0/P1/ints/Capitalized.
  - TASK 1 is `test_authoring` (writes the RED oracle; carries `mutation_target:
    harness/planner/plan_normalizer.py`, MODULE dotted path only).
  - TASK 2 is `harness_self_fix` (writes `harness/planner/plan_normalizer.py`,
    OMITS `mutation_target`; depends on TASK 1). NOT trust-core;
    auto-approve-eligible with NO operator decision file.
The impl task emits a `__JANUSMASK_PATCHES__` SYMBOL recipe (ONE symbol entry,
NOT a manifest). Each task's `non_goals` MUST contain the literal word
`integration`; each `regression_tests >= 2`. Do NOT add any task touching a file
other than the one its `files_touched` declares.
