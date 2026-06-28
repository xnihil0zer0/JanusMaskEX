---
working_dir: "/home/xnihil0zer0/AI-Data/JanusMaskEX"
operator_decision_required: false
auto_approve_requested: true
required_task_ids:
  - enforce-module-first-strip-cycle-oracle
  - enforce-module-first-strip-cycle-impl
interfaces: >
  Close a planner CYCLE-DEADLOCK hole: `_enforce_module_first`
  (harness/planner/plan_normalizer.py:146) takes a fix-forward red-pair EXCEPTION
  (`continue` at line ~168 when the impl's `verification_command` names the oracle's
  own test file) and returns from that iteration WITHOUT sanitizing the oracle's
  dependency list — so a pre-existing oracle->impl edge from the (non-deterministic)
  LLM draft is left intact. The fix-forward branch SKIPS the very block (lines
  169-192) that normally (a) makes the oracle depend on the impl and (b) STRIPS any
  `oracle in impl.deps` back-edge. Combined with non-deterministic draft dep
  direction, the daemon's INCREMENTAL staging can stage `oracle.deps=['impl']` from
  one run AND `impl.deps=['oracle']` from another -> a 2-cycle -> 0 dispatchable
  tasks (deadlock). `validate_plan`'s cycle check
  (harness/planner/plan_validator.py:~280) runs at full-plan validation and does NOT
  gate the daemon's per-task incremental staging path, so the cycle is not caught.

  ONE impl task editing exactly ONE existing file
  (harness/planner/plan_normalizer.py) via a __JANUSMASK_PATCHES__ SYMBOL patch,
  plus ONE paired RED test_authoring oracle.

  (1) enforce-module-first-strip-cycle-oracle (test_authoring):
      RED behavioral oracle for `_enforce_module_first` — when the fix-forward
      red-pair EXCEPTION fires AND the draft carried an oracle->impl edge, the
      oracle's deps are now SANITIZED (the oracle->impl back-edge is stripped) so the
      surviving graph has impl-depends-on-oracle (or no edge between them), never a
      cycle. RED on HEAD (today the back-edge survives the fix-forward `continue`).

  (2) enforce-module-first-strip-cycle-impl (harness/planner/plan_normalizer.py):
      Make the fix-forward EXCEPTION still strip any oracle->impl dependency edge
      from the oracle before `continue`, so the resulting pair can never form a cycle
      with the impl's own (vcmd-justified) oracle-first orientation. PURE list
      surgery; deterministic. `plan_normalizer.py` is NOT in `_NEVER_AUTO_APPROVE`
      -> auto-approve-eligible.
---

# Title
Sanitize the fix-forward red-pair exception in `_enforce_module_first` so it strips
the oracle->impl back-edge before `continue`, eliminating the
oracle.deps=['impl'] + impl.deps=['oracle'] 2-cycle that deadlocks the daemon's
incremental staging (0 dispatchable tasks).

# Scope
TWO tasks. ONE `harness_self_fix` impl task (one `harness/**` file:
harness/planner/plan_normalizer.py) and ONE paired `test_authoring` oracle. READ
each file first.

1. `enforce-module-first-strip-cycle-oracle` (test_authoring) authors a RED
   behavioral oracle in
   `tests/harness/test_enforce_module_first_fixforward_cycle.py` against
   `_enforce_module_first` in `harness/planner/plan_normalizer.py`. NO production
   edit in this task.

2. `enforce-module-first-strip-cycle-impl` edits
   `harness/planner/plan_normalizer.py` to sanitize the fix-forward exception.
   `harness/planner/plan_normalizer.py` is NOT in `_NEVER_AUTO_APPROVE`
   (the irreducible set is `harness/agent_jail.py`, `harness/dbus_proxy.py`,
   `harness/paths.py`, `harness/git_integration.py`, `harness/orchestrator.py`,
   `harness/interceptors.py`, `harness/selfheal.py`, `harness/autowork_daemon.py`,
   `services/**` — see harness/orchestrator.py:2577), so this task is
   auto-approve-eligible (`operator_decision_required: false`,
   `auto_approve_requested: true`). NO operator decision file is required.

This is a ROOT-CAUSE harness fix per the "fixes-are-permanent-and-reusable" and
"turn-recurring-failures-into-pipeline-fixes" rules: it removes the structural
reason a fix-forward red-pair can deadlock the daemon, rather than manually
un-cycling each blocked plan.

# Background — the exact mechanism (verified, with line anchors)
`_enforce_module_first(tasks, repo_root=None) -> None` lives at
`harness/planner/plan_normalizer.py:146` and is called from `normalize_plan` at
`harness/planner/plan_normalizer.py:1343`. Its job is to flip oracle-first
inversions to module-first while keeping the dep graph acyclic.

For each oracle (a `test_authoring` task with a `mutation_target`), it resolves the
paired impl via `_impl_for_module(tasks, _module_path(target))` (line ~157), then:

  - line ~164-168: the FIX-FORWARD EXCEPTION. If the impl's
    `verification_command` (a non-empty string) NAMES any of the oracle's
    `files_touched`, it does `continue` — leaving the pair oracle-first to mirror
    `harness.redpair_acceptance.is_fix_forward_redpair` (the runtime acceptance
    contract). THIS IS THE HOLE: the `continue` happens BEFORE the sanitizing block
    below, so whatever dep edges the (non-deterministic) LLM draft put on the oracle
    survive untouched.
  - lines ~169-177 (SKIPPED on fix-forward): ensure `iid in oracle.deps` (oracle
    depends on impl) AND strip any `oid in impl.deps` (remove the impl->oracle
    back-edge).
  - lines ~178-192 (SKIPPED on fix-forward): a while-loop that removes impl deps
    until the impl no longer reaches the oracle (`_reaches(graph, iid, oid)`),
    guaranteeing acyclicity for the non-exception path.

So for a fix-forward pair the function returns having sanitized NOTHING. If the
draft left `oracle.deps = ['impl_id']` (an oracle->impl edge), it stays. Separately,
the CORRECT fix-forward orientation is impl-depends-on-oracle (`impl.deps =
['oracle_id']`) — the RED oracle must run/land first, the impl turns it green. The
daemon's INCREMENTAL staging stages tasks as they become available across runs; with
non-deterministic draft dep direction it can end up with BOTH `oracle.deps=['impl']`
(surviving back-edge) AND `impl.deps=['oracle']` (correct edge) live at once ->
a 2-cycle -> `_build_graph` has impl<->oracle -> NEITHER is dispatchable -> deadlock
(0 dispatchable tasks).

WHY validate_plan does NOT catch it: `validate_plan`
(`harness/planner/plan_validator.py`) has a cycle check at line ~280 (`dfs`/`dfs2`
emitting `dependency_cycle` PlanViolations), but it runs at FULL-PLAN validation
time. The daemon's per-task incremental staging path does NOT route through
`validate_plan`'s cycle DFS, so the cycle is never gated there. The MEMORY note
"factory-selffix-fuzz-and-oracle-overreach" records the validated 2-line
`_enforce_module_first` fix as a known blocker-chain item.

THE FIX (chosen seam — sanitize the exception at its source; the cleanest,
most-local seam): make the fix-forward branch, BEFORE `continue`, STRIP any
oracle->impl edge from the oracle's deps (and, defensively, ensure the impl carries
the correct impl->oracle edge OR at minimum no impl->oracle? — see precise
requirement below). Why this seam over the alternative ("per-task staging rejects a
pair whose combined deps form a cycle"):
  - It fixes the ROOT (the normalizer is the single place that decides the
    fix-forward orientation), so EVERY downstream consumer — incremental staging,
    full-plan validation, re-plan — sees a coherent acyclic pair. The staging-side
    guard would only catch the symptom at one consumer and would need a new cycle
    check threaded into the per-task path.
  - It is a SMALL, deterministic, PURE list edit inside one function, in a
    non-trust-core file (auto-approve-eligible) — minimal surface, no new module, no
    new flag.
  - It directly closes the documented validated 2-line fix the blocker-chain note
    already identified.
Optionally the impl MAY also note the staging-side guard as defense-in-depth in
non_goals, but the in-scope change is the normalizer sanitize ONLY (do NOT edit the
staging path or plan_validator in this brief).

# Inputs
READ these files FIRST in `/home/xnihil0zer0/AI-Data/JanusMaskEX`:

- `harness/planner/plan_normalizer.py` — the file TASK 2 edits (NOT trust-core).
  VERIFIED current state:
  - `_enforce_module_first(tasks, repo_root=None) -> None` at line ~146. The
    fix-forward `continue` is at line ~168 inside
    `if isinstance(_vc, str) and _vc:` / `if any((of in _vc for of in _ofiles)):`.
    The sanitizing block it skips is lines ~169-192.
  - Helpers (reuse, do NOT reimplement): `_task_id` (~33), `_files_touched` (~38),
    `_mutation_target` (~46), `_is_test_authoring` (~50), `_module_path` (~29),
    `_impl_for_module` (~53), `_build_graph` (~65), `_reaches` (~76),
    `_dependencies` (used by `_build_graph`). `oid = _task_id(oracle)`,
    `iid = _task_id(impl)` are already bound (lines ~160-161) when the exception
    fires.
  - `oracle.get('dependencies')` may be absent, None, or a non-list — handle
    defensively (mirror the existing `if not isinstance(oracle_deps, list):`
    normalization at lines ~169-172).

- `harness/redpair_acceptance.py` — DO NOT EDIT (read for context only). It defines
  `is_fix_forward_redpair`, the runtime acceptance contract the exception mirrors:
  a fix-forward pair is legitimately oracle-FIRST (impl depends on oracle / impl's
  vcmd runs the oracle's test). The sanitize must preserve THAT orientation
  (impl->oracle is fine / desired); only the OPPOSITE oracle->impl back-edge is the
  bug.

- `harness/planner/plan_validator.py` — DO NOT EDIT (read for context only). Its
  cycle check is at line ~280 (`dfs`/`dfs2` -> `dependency_cycle`). It documents the
  cycle that the incremental staging path does NOT gate; this brief removes the cause
  upstream so the cycle never forms.

- `tests/harness/` / `tests/test_plan_normalizer*.py` — DO NOT EDIT existing tests
  (read for the established `_enforce_module_first` test pattern: build a `tasks`
  list of plain dicts, call `_enforce_module_first(tasks)`, then assert on the
  resulting `dependencies` lists and acyclicity via `_build_graph`/`_reaches`). The
  new oracle follows that pure, in-memory pattern (no git tree, no network — the
  function is pure list surgery).

# Non-Goals
Integration is out of scope (the literal word `integration` MUST appear in this
section and in EACH task's `non_goals` to excuse the integration-test requirement).
Specifically OUT OF SCOPE:
- The staging-side guard ("per-task staging rejects a pair whose combined deps form
  a cycle"). That is a SEPARATE, larger change to the daemon/orchestrator staging
  path; this brief fixes the ROOT in the normalizer ONLY. Do NOT edit the staging
  path, the daemon, or `plan_validator.py`.
- Changing the NON-exception path of `_enforce_module_first` (the lines ~169-192
  block, the flip-to-module-first logic, the acyclicity while-loop). The fix adds
  sanitizing to the EXCEPTION branch only; the existing non-exception behavior is
  byte-unchanged.
- Changing the fix-forward DETECTION (the `impl.vcmd names the oracle's test file`
  test at lines ~164-167) or `harness.redpair_acceptance.is_fix_forward_redpair`.
  The exception still fires for the same pairs; we only sanitize the oracle's deps
  before `continue`.
- Editing `harness/planner/plan_validator.py`, `harness/redpair_acceptance.py`,
  `harness/orchestrator.py`, `harness/autowork_daemon.py`, or ANY file other than the
  one each task's `files_touched` declares.

# Deliverables

## TASK 1 — enforce-module-first-strip-cycle-oracle (test_authoring; harness/planner/plan_normalizer.py)
The test_authoring stage authors a RED behavioral oracle (NO production edit). It
loads the edited code via `importlib` (`spec.loader.exec_module` from a `tmp_path`
copy, or import `harness.planner.plan_normalizer` and call `_enforce_module_first`
directly) — NEVER `exec`/`eval`/`__import__` (AST-banned). It is hermetic: build
`tasks` lists of plain dicts in-memory; no real `state/`, no git tree, no network
(the function is pure list surgery; `repo_root` defaults to None).

ANTI-GAMING ORACLE REQUIREMENTS (derive expectations from the function's REAL
mutation of the `tasks` list; do NOT paste impl source into the test, do NOT assert
a frozen literal of the function body):
- FIX-FORWARD PAIR WITH oracle->impl BACK-EDGE IS SANITIZED (the load-bearing RED
  case): build an oracle task `{'task_id':'orc', 'meta_task_type':'test_authoring',
  'mutation_target':'pkg/mod.py', 'files_touched':['tests/test_mod.py'],
  'dependencies':['imp']}` (oracle ERRONEOUSLY depends on impl) and an impl task
  `{'task_id':'imp', 'files_touched':['pkg/mod.py'], 'dependencies':[],
  'verification_command':'python -m pytest tests/test_mod.py -q'}` (impl's vcmd NAMES
  the oracle's test file -> fix-forward exception fires). Call
  `_enforce_module_first(tasks)`. Assert that AFTER the call the oracle's
  `dependencies` does NOT contain `'imp'` (the oracle->impl back-edge is STRIPPED),
  and that the combined graph (`_build_graph(tasks)`) is ACYCLIC (use `_reaches` to
  assert NOT (`_reaches(g,'orc','imp')` AND `_reaches(g,'imp','orc')`)). This MUST be
  RED on HEAD (today the back-edge survives the `continue`).
- CYCLE PREVENTED WHEN IMPL ALSO DEPENDS ON ORACLE: same fix-forward pair but ALSO
  set `impl.dependencies = ['orc']` (the correct fix-forward orientation present
  too). After `_enforce_module_first(tasks)`, assert the graph is ACYCLIC — i.e. the
  oracle no longer depends on the impl, so impl->oracle is the only surviving edge
  (no 2-cycle). This is the exact deadlock scenario from the diagnosis.
- NON-FIX-FORWARD PAIR UNCHANGED (no regression): an oracle/impl pair where the
  impl's vcmd does NOT name the oracle's test file (so the EXCEPTION does NOT fire)
  -> assert the existing flip-to-module-first behavior is preserved (the function
  still makes `iid in oracle.deps` and strips `oid` from `impl.deps`, and the graph
  is acyclic) — proving the change touches ONLY the exception branch.
- NO IMPL (oracle alone) IS A NO-OP: an oracle whose `mutation_target` module has no
  impl task in `tasks` -> `_impl_for_module` returns None -> `continue` early ->
  assert the oracle's `dependencies` is unchanged (the new sanitize must not fire
  when there is no impl).
- DETERMINISM: calling `_enforce_module_first` twice on equivalent inputs yields the
  same dependency lists. PURITY: the oracle runs fully offline against in-memory
  dicts.
The oracle MUST derive expectations from the live `_enforce_module_first` mutation of
the `tasks` it builds, MUST NOT paste the impl into the test, and MUST NOT assert a
frozen function-body literal.

`non_goals` MUST contain the literal word `integration`. `regression_tests >= 2`.

- `task_id: enforce-module-first-strip-cycle-oracle`
- `priority: high`
- `meta_task_type: test_authoring`
- `files_touched: ["tests/harness/test_enforce_module_first_fixforward_cycle.py"]`
- `mutation_target: harness/planner/plan_normalizer.py`  (MODULE-only dotted path;
  the test exercises `_enforce_module_first` in this module)
- `dependencies: []`
- `verification_command:` `python -m pytest tests/harness/test_enforce_module_first_fixforward_cycle.py -q`
  (RED against HEAD; do NOT use a broad `pytest tests/adversarial/ -q` vcmd).

## TASK 2 — enforce-module-first-strip-cycle-impl (harness/planner/plan_normalizer.py)

NOT TRUST-CORE: `harness/planner/plan_normalizer.py` is NOT in `_NEVER_AUTO_APPROVE`
(harness/orchestrator.py:2577), so this task is auto-approve-eligible
(`auto_approve_requested: true`, `operator_decision_required: false`). NO operator
decision file is required.

IMPLEMENTATION NOTES (LOAD-BEARING — GENERAL behavior, minimal surface):

1. PATCH SHAPE — this task edits an EXISTING multi-symbol harness file, so it MUST
   carry the `__JANUSMASK_PATCHES__` recipe and NOT a whole-file rewrite (else it
   hits the `whole_file_drift` reject, which rejects a whole-file submission that
   modifies >1 existing top-level symbol). `harness/planner/plan_normalizer.py`
   defines MANY top-level symbols. Submit a single top-level `__JANUSMASK_PATCHES__`
   list with ONE `{'kind':'symbol', 'name':'_enforce_module_first',
   'code': r'''...'''}` entry that reproduces `_enforce_module_first` VERBATIM except
   for the added sanitize in the fix-forward branch. Replace ONLY
   `_enforce_module_first`. Do NOT emit `__JANUSMASK_MANIFEST__` (single existing
   file, one symbol). This fix adds NO new top-level symbol; it edits one existing
   symbol in place. (If a fix EVER needed a brand-new top-level symbol, it would have
   to be R-ANCHORED inside an existing symbol's reproduced code — a standalone
   unanchored new-symbol patch entry fails patch-apply with a KeyError.)

2. THE EDIT: in the fix-forward EXCEPTION branch (lines ~164-168), BEFORE the
   `continue`, SANITIZE the oracle's deps so any oracle->impl back-edge is removed.
   Concretely, inside `if any((of in _vc for of in _ofiles)):` and before
   `continue`:
       _od = oracle.get('dependencies')
       if isinstance(_od, list) and iid in _od:
           oracle['dependencies'] = [d for d in _od if d != iid]
       continue
   `iid = _task_id(impl)` and `oid = _task_id(oracle)` are already bound above. This
   leaves the impl-depends-on-oracle (fix-forward) orientation intact and removes
   ONLY the erroneous oracle->impl edge, so the pair can never form a 2-cycle. Do NOT
   touch the impl's deps in the exception branch (the impl->oracle edge is the
   correct fix-forward orientation and may legitimately be present). Do NOT alter the
   detection logic (`_vc`, `_ofiles`, the `any(...)` test) or the non-exception block
   (lines ~169-192).

3. GENERALITY: do NOT special-case any module path, slug, task_id, or vcmd string.
   The sanitize is driven solely by `iid` membership in the oracle's deps list, so it
   applies to ANY fix-forward red-pair.

4. NO-REGRESSION: the non-fix-forward path (when the exception does NOT fire) is
   BYTE-UNCHANGED — it still runs the flip-to-module-first block and the acyclicity
   while-loop. The only behavioral change is: a fix-forward pair now also has its
   oracle->impl back-edge stripped.

ANTI-GAMING ORACLE REQUIREMENT (TASK 2): the impl must make the TASK 1 oracle GREEN
by GENERAL behavior (the real sanitize over the synthetic `tasks`), NOT by detecting
the fixture. Re-run the EXACT TASK 1 vcmd plus any existing plan_normalizer
_enforce_module_first tests before dispatch and confirm none regress.

`non_goals` MUST contain the literal word `integration`. `regression_tests >= 2`.

- `task_id: enforce-module-first-strip-cycle-impl`
- `priority: high`
- `meta_task_type: harness_self_fix`
- `files_touched: ["harness/planner/plan_normalizer.py"]`
- OMIT `mutation_target` (impl task editing a `harness/**` path).
- `dependencies: ["enforce-module-first-strip-cycle-oracle"]` (RED oracle first;
  impl turns it green — red-pair preserved).
- Emit a `__JANUSMASK_PATCHES__` SYMBOL patch (ONE entry, `name:
  '_enforce_module_first'`, with the added oracle-dep sanitize; reproduce the
  function VERBATIM otherwise).
- AUTO-APPROVE-ELIGIBLE: `harness/planner/plan_normalizer.py` is NOT in
  `_NEVER_AUTO_APPROVE`; NO operator decision file is required.
- `verification_command:` a SCOPED, non-vacuous pytest selecting the new oracle plus
  any existing plan_normalizer slice that must stay green, e.g.
  `python -m pytest tests/harness/test_enforce_module_first_fixforward_cycle.py -q`
  (do NOT use a broad `pytest tests/adversarial/ -q` vcmd). Run the EXACT vcmd
  yourself before dispatch and confirm `N passed` with N>=2 and that existing
  plan_normalizer tests are NOT regressed.

# Required plan shape
Emit EXACTLY TWO tasks (pin via `required_task_ids: [
enforce-module-first-strip-cycle-oracle, enforce-module-first-strip-cycle-impl]`).
PRIORITY MUST be canonical lowercase (`high`), NEVER P0/P1/ints/Capitalized.
  - TASK 1 is `test_authoring` (writes the RED oracle for `_enforce_module_first`;
    carries `mutation_target: harness/planner/plan_normalizer.py`, MODULE dotted path
    only).
  - TASK 2 is `harness_self_fix` (writes `harness/planner/plan_normalizer.py`, OMITS
    `mutation_target`; depends on TASK 1). It is NOT trust-core; auto-approve-eligible
    with NO operator decision file.
The impl task emits a `__JANUSMASK_PATCHES__` SYMBOL patch (NOT a manifest). Each
task's `non_goals` MUST contain the literal word `integration`; each
`regression_tests >= 2`. Do NOT add any task touching a file other than the one its
`files_touched` declares; do NOT add a task editing `plan_validator.py`,
`redpair_acceptance.py`, `orchestrator.py`, or `autowork_daemon.py`.

`harness/planner/plan_normalizer.py` is NOT in the irreducible `_NEVER_AUTO_APPROVE`
set (`harness/agent_jail.py`, `harness/dbus_proxy.py`, `harness/paths.py`,
`harness/git_integration.py`, `harness/orchestrator.py`, `harness/interceptors.py`,
`harness/selfheal.py`, `harness/autowork_daemon.py`, `services/**`), so TASK 2 is
auto-approve-eligible and requires NO operator decision file.
