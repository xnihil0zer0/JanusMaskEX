# HANDOFF — Project Concurrency Isolation + NGv2 Solver/AST Verifier Capabilities

You are the **overseer**. Your mission is to land the three tasks below through the gated
pipeline. Every production change to the harness (`harness/**`) routes as a `harness_self_fix`
(RED oracle committed FIRST → brief → planner → stage → worker → operator decision file at
`state/control/decisions/<task_id>.json`). Rule: [[never-hand-edit-production-outside-pipeline]].

---

## Orientation (verified 2026-06-11 against HEAD `10e5428`)

* **Repository**: `/home/xnihil0zer0/JanusMaskJR` (the harness itself). External target:
  `/home/xnihil0zer0/NobleGreedv2` — working tree CLEAN at `ae2675a` (master pushed, in sync with
  origin, suite 1191 green as of 2026-06-11 end of bounty-FSM epic), which matters because
  `EXTERNAL_DIRTY_GATE` (`harness/orchestrator.py:2833-2847`) refuses to stage a dirty external repo.
* **Posture**: the daemon is **RUNNING** (pid 1258348,
  `python -m harness.autowork_daemon --state-dir state --config harness/config.yaml`); no pause flag
  under `state/control/autowork/`; `state/control/autowork/auto_promote.allowlist` is non-empty
  (live slugs). Do not disturb `state/` or production code by hand.
* **Operational rule**: with the daemon live, do **not** drive `orchestrator_worker` manually in
  parallel with it (the shared `state/control/autowork/git_commit.lock` flock wedges on collision).
  The dispatch path for every task here is: commit the RED oracle → drop the brief
  `brief_hooks_<slug>.md` → write the decision file (for `harness_self_fix`) → append the slug to
  `state/control/autowork/auto_promote.allowlist` → let the RUNNING daemon dispatch it.
* **Memory reference**: `ngv2-cleanroom-rebuild-plan`.

### Architecture context for T1 (read before touching scheduling)

JM already implements the merge-queue concurrency shape used by
[bors / GitHub merge queue / Mergify](https://mergify.com/blog/the-origin-story-of-merge-queues):
**parallel speculative verification, serialized integration**.

* Verification is isolated per task: each task gets its own detached staging worktree
  (`create_staging_worktree`, `harness/git_integration.py:1453`).
* Integration (commit) is globally serialized by a bounded flock on
  `state/control/autowork/git_commit.lock` (`_acquire_git_commit_lock_bounded`,
  `harness/orchestrator.py:2418`; usage documented at `:2517`).
* Admission control is optimistic and file-granular: `can_run_parallel`
  (`harness/autowork_parallelism.py:35`) blocks pairs with overlapping `files_touched` or a
  transitive dependency edge; missing `files_touched` is conservative-blocked.

So semantic conflicts are screened at admission, racy writes at commit time are excluded by the
lock, and verification can fan out. Any additional serialization is throughput spent to buy
protection against *shared state outside `files_touched`* — name that state before paying.

---

## State at handoff

Uncommitted hand-edits in the working tree (`git status`: `M harness/autowork_parallelism.py`,
`M harness/config.yaml`, `M tests/test_autowork_parallelism.py`) implementing per-project
concurrency isolation:

* `can_run_parallel` gains a project-isolation block (only one task per project at a time) plus a
  new top-level helper `_get_project_dir`; projects whose resolved dir contains the substring
  `"NobleGreedv2"` are exempted from the serialization.
* `harness/config.yaml:49` `parallel_cap` changes **5 → 4**. Note the direction: HEAD already runs
  `parallel_cap: 5`; this diff *reduces* global parallelism and *adds* per-project serialization.
* `tests/test_autowork_parallelism.py::test_project_isolation` added. Suite is green on the working
  tree (8 passed, re-run 2026-06-11) and the new test is RED against HEAD code (HEAD
  `can_run_parallel` has no `working_dir` awareness).

**NOTE — the owner decisions (T1, settled 2026-06-11) INVERT this diff's semantics**: the
hand-edit serializes JM self-tasks and exempts NGv2; the decided contract serializes same-external-
root tasks and exempts JM self-tasks, with `parallel_cap` kept at 5. The working-tree diff is
therefore raw material only — P1 reverts the config.yaml edit and rewrites the oracle to the
decided contract; the T1 brief directs the worker to the decided behavior.

NGv2 capability gaps (T2/T3): **UNBLOCKED 2026-06-11** — P2/P3 dependencies are installed into the
NGv2 venv and verified live (see P2/P3 for versions and the verified API snippet). NGv2's
`requirements.txt` lines remain to be landed as pipeline leaves.

---

## Tasks

### T1 — Land Project Concurrency Isolation (harness_self_fix)

* **Goal**: land the working-tree changes in `harness/autowork_parallelism.py` +
  `harness/config.yaml` through the pipeline. The worker stages from the WORKING TREE
  (`_stage_targets` copies working-tree content), so the existing hand-edit becomes the staged
  baseline the worker re-emits through the gate.
* **Pre-dispatch (MANDATORY)**: complete **P1** first — commit the oracle before any
  `harness_self_fix` worker run (memory: [[untracked-test-poisons-patches-commit]]).
* **Owner decisions — SETTLED 2026-06-11 (owner-delegated; encode these in P1's oracle and the
  brief; the working-tree diff does NOT yet implement them — the brief directs the worker to)**:
  1. **Throughput: JM self-task serialization REJECTED; `parallel_cap` stays 5.** Per-project
     serialization of worktree-isolated self-tasks is strictly more pessimistic than the existing
     protections (isolated worktrees + serialized commit lock + file-overlap admission); no
     remaining shared-state hazard was named, and the historical collision classes (`8d5a88d`,
     `21ce30f`) are hermeticized. The `config.yaml` 5→4 hand-edit is to be REVERTED in P1
     (`git checkout -- harness/config.yaml`), which also makes T1 a SINGLE-file change.
  2. **Exemption direction INVERTED: isolation applies to EXTERNAL-project tasks only.** Two
     tasks whose resolved `working_dir` lands in the SAME external root serialize (they share one
     mutable repo root whose `EXTERNAL_DIRTY_GATE` reads shared state — empirically confirmed
     2026-06-11: multiple `worker_crash_orphan` blocks from dirty-root races during the bounty-FSM
     epic). JM self-tasks (no `working_dir`, or resolving inside the repo) are EXEMPT — they are
     fully worktree-isolated already.
  3. **Both-`working_dir`-absent ⇒ both are JM self-tasks ⇒ PARALLELIZE** (falls out of decision
     2: exemption applies). Pin this with an explicit oracle case in P1 so the contract cannot
     drift.
* **Hardening to fold into the same whole-file emission** (direct the worker in the brief):
  isolation membership is decided by EXACT resolved-path comparison against a module-level
  `_ISOLATED_EXTERNAL_DIRS = frozenset({'/home/xnihil0zer0/NobleGreedv2'})` (matching
  `external_roots.allow`), tested on `_get_project_dir`'s resolved output — never a substring
  test (a substring match would isolate/exempt ANY path containing "NobleGreedv2" anywhere, e.g.
  a fixtures dir named `NobleGreedv2-samples` inside JM). Pin exact-match with an oracle case in
  P1.
* **Alternatives considered**: a full speculative merge-queue (batching + predictive testing à la
  [Aviator](https://www.aviator.co/blog/what-is-a-merge-queue/)/[Mergify](https://docs.mergify.com/merge-queue/))
  was rejected — JM's commit integration is already globally lock-serialized and task volume is far
  below the scale where speculative batching pays; it would also require new daemon scheduling
  machinery outside whole-symbol patch discipline. Dropping the diff entirely in favor of the
  existing file-granular optimistic admission is the strongest rival — that is exactly what owner
  question 1 adjudicates.
* **Brief**: `brief_hooks_concurrency_isolation.md` (does not exist yet — author it). Frontmatter +
  five sections per the gold standard (`brief_hooks_ngv2_fix_gateresult_fields.md`). Pin in
  `# Required plan shape`: `task_id: concurrency_isolation` VERBATIM;
  `meta_task_type: harness_self_fix` (valid — `META_TASK_POLICY` at `harness/planner/taxonomies.py:1`
  includes it: bypass_fuzzer + skip_smoke_gates); `working_dir` ABSENT (self task);
  `files_touched: ["harness/autowork_parallelism.py"]` (config.yaml reverted in P1, decision 1);
  `verification_command: python3 -m pytest -q tests/test_autowork_parallelism.py`; include the
  validator-floor sentence (`test_spec.regression_tests` must NAME at least two committed-oracle
  test cases so the edge-case floor at `harness/planner/plan_validator.py:280` passes, e.g.
  `test_project_isolation`, `test_transitive_deps_cycle`).
* **Edit-shape directive (state it LOUDLY in the brief)**: with config.yaml reverted this is a
  SINGLE Python file — but it adds a NEW top-level symbol (`_get_project_dir`), and new-symbol +
  BYPASS_FUZZER + patches-symbol is a known `auto_commit_failed` shape (memory:
  [[brief-staleness-reconciler]]). Direct the worker to emit the WHOLE FILE (single-file
  whole-file emission, never a `__JANUSMASK_PATCHES__` symbol patch).
  `harness/autowork_parallelism.py` is 85 lines — whole-file is cheap and safe.
* **Oracle**: `tests/test_autowork_parallelism.py::test_project_isolation` REWRITTEN in P1 to the
  settled (inverted) semantics — RED on HEAD AND on the current working-tree diff (both lack the
  external-isolation contract); GREEN only once the worker lands the decided behavior.
* **Gating**: `harness/autowork_parallelism.py` is NOT in `_NEVER_AUTO_APPROVE`
  (`harness/orchestrator.py:2295`), but `harness_self_fix` still requires the operator decision
  file `state/control/decisions/concurrency_isolation.json` (approve) —
  `commit_accepted_output`'s path-scope gate enforces `meta_task_type=harness_self_fix AND
  approval_ok` for `harness/**` (`harness/git_integration.py:82`).
* **Activation requires a daemon restart**: the running daemon imported `can_run_parallel` at
  startup (`harness/autowork_daemon.py:21`; call sites `:258`, `:1654`, `:1659`). Python's import
  cache means the landed change is INERT in the live process (`parallel_cap` is unchanged per
  decision 1, so only the function import matters). After the commit lands: wait for in-flight
  tasks to drain, stop pid 1258348, restart
  `python -m harness.autowork_daemon --state-dir state --config harness/config.yaml`. Schedule the
  restart at a quiet moment.
* **Action**: P1 → author brief → decision file → append `concurrency_isolation` to
  `auto_promote.allowlist` → daemon dispatches → drain + restart daemon.

### T2 — Z3 Solver Adapter for NGv2 Invariant Constraints (P2 ✅ done — unblocked)

* **Design constraint (committed contract — do not violate)**: `ngv2/z3_bridge.py` is stdlib-only
  BY DESIGN. Its module docstring pins: "This module is a PURE, stdlib-only shell … An optional
  injected `solver_fn` callable lets a solver be wired in WITHOUT this module ever importing
  `z3`", and the committed oracle `tests/test_z3_bridge.py` pins `z3_used is False` on every
  non-injected path while exercising the `solver_fn` seam (`make_mock_solver`/
  `make_scripted_solver`). The seam: `Z3Bridge(solver_fn=...)` routes every `check_invariants` call
  through the injected callable (`ngv2/z3_bridge.py:76-89`). The only consumer is
  `ngv2/backtrack.py:58` via an `Optional` injected verifier; nothing constructs `Z3Bridge` with a
  real solver today.
* **Task**: NEW module `ngv2/z3_solver_adapter.py` exposing
  `make_z3_solver() -> Optional[SolverFn]` — guarded in-body `import z3` (return `None` or raise a
  typed `Z3Unavailable` when absent), translating the two committed constraint sets
  (`'grounding'`: `(codeql_found OR joern_found) -> confidence >= HIGH`; `'gate'`:
  `(submitting AND live_test_required) -> live_test_passed`, per `CONSTRAINT_SETS` in
  `ngv2/z3_bridge.py:23`) into z3 Bool/Implies assertions, returning a `SolverFn` compatible with
  `Z3Bridge(solver_fn=...)`. `ngv2/z3_bridge.py` itself is NOT touched.
* **Solver choice — alternatives considered**: keep direct `z3-solver` behind the existing seam.
  [pySMT](https://github.com/pysmt/pysmt) (solver-agnostic API, portfolio + incremental support)
  was the strongest rival and loses here: it adds a second abstraction layer over the SolverFn seam
  the codebase already committed, plus another dependency, to decide two propositional implications
  where solver choice is performance-irrelevant.
  [cvc5](https://www-cs.stanford.edu/~preiner/publications/2022/BarbosaBBKLMMMN-TACAS22.pdf) ships a
  z3py-compatible Python API and is a viable later drop-in — and because the adapter is the ONLY
  z3-aware module, swapping solvers later is one new adapter module with zero `z3_bridge` changes.
  Incremental solving (push/pop) is deliberately out of scope: each `check_invariants` call is a
  fresh tiny formula; statelessness keeps the SolverFn deterministic and trivially testable.
* **Oracle method — exhaustive differential check (adopt this; it strictly dominates
  spot-checking)**: both constraint-set state spaces are tiny — `grounding` is
  2 (`codeql_found`) × 2 (`joern_found`) × 4 (`confidence` ranks) = 16 states; `gate` is 2³ = 8
  states. The oracle should enumerate EVERY state and assert
  `Z3Bridge(solver_fn=make_z3_solver()).check_invariants(cs, state).satisfied ==
  Z3Bridge().check_invariants(cs, state).satisfied` (rule fallback as the reference
  implementation), in the spirit of differential testing (McKeeman, *Differential Testing for
  Software*, Digital Technical Journal 1998). 24 deterministic cases, hand-authorable, no fixture
  bloat — and it kills the entire rule-vs-solver divergence class rather than two sampled points.
* **Brief**: `brief_hooks_ngv2_z3_solver_adapter.md`, frontmatter
  `working_dir: "/home/xnihil0zer0/NobleGreedv2"`, `# Required plan shape` pinning
  `task_id: ngv2-z3-solver-adapter` VERBATIM, `meta_task_type: data_model` (external target — the
  diff-fuzzer cannot resolve external imports, so a fuzzer-bypassed type is required; `data_model`
  is bypass_fuzzer per `META_TASK_POLICY`), `files_touched: ["ngv2/z3_solver_adapter.py"]`, NEW
  module ⇒ single-file WHOLE-FILE dispatch directive (LOUD: never `__JANUSMASK_PATCHES__` for a new
  module — memory: [[phase2-session4-pipeline-rebuild]]), validator-floor sentence naming ≥2 oracle
  test cases.
* **RED oracle** (hand-author, COMMIT TO NGv2 MASTER FIRST — external-build recipe, memory:
  [[ngv2-phase0-external-build-proven]]): `tests/ngv2/test_z3_solver_adapter_wired.py` —
  (a) `make_z3_solver()` returns a callable when z3 is importable; (b) the exhaustive differential
  sweep above, with `z3_used is True` asserted on the injected path; (c) the z3-absent path returns
  `None` deterministically (monkeypatch `z3` out of `sys.modules` + block the import). ⚠️ Do NOT
  write the availability cases as bare `pytest.skipif(no z3)` — a fully-skipped oracle is vacuously
  green and the accept gate would pass a do-nothing submission. P2 must land BEFORE this oracle is
  committed so (a)/(b) run for real. Case (b) running the adapter through the real `Z3Bridge` seam
  satisfies the wiring requirement (memory: [[implementation-is-not-wired-defect]]); if a live
  composition point is wanted later (e.g. a grounding gate constructing the bridge with the
  adapter), make that a SEPARATE follow-up brief, not scope creep here.
* **Verification**: `python -m pytest tests/ngv2/test_z3_solver_adapter_wired.py -q`,
  `working_dir=/home/xnihil0zer0/NobleGreedv2`.

### T3 — Multi-Language Tree-Sitter Verifier for NGv2 (P3 ✅ done — unblocked)

* **Design constraint (committed contracts — do not violate)**: `ngv2/ast_verifier.py` ("Only the
  standard library is imported" — module docstring) and `ngv2/ast_constraint.py` ("depends on no
  third-party packages") are stdlib-only by contract, with committed oracles
  (`tests/test_ast_verifier.py`, `tests/ngv2/test_ast_verifier_marker_wired.py`). Tree-sitter
  capability therefore lands as a PARALLEL verifier module, never as an edit to those two.
* **Task**: NEW module `ngv2/treesitter_verifier.py` — guarded in-body `import tree_sitter` +
  per-language grammar loading, mirroring the `z3_bridge` optional-dependency pattern; public
  surface ~`TreeSitterVerifier.verify(code: str, language: str) -> ASTResult`-shaped (reusing the
  `Violation`/`ASTResult` dataclass SHAPES — importing them from `ast_verifier` is allowed: only
  `ast_verifier` promises no-sibling-imports, not its consumers; decide import-vs-redefine in the
  brief) detecting at minimum: return-constant success stubs and process-execution calls
  (`system`/`exec*`/`Runtime.exec`/`child_process`) in C, Java, JS.
* **Rule representation — use tree-sitter S-expression queries, not manual tree walks**: encode
  each detection rule as a `tree_sitter` query pattern (e.g.
  `(call_expression function: (identifier) @fn (#eq? @fn "system"))`) evaluated via
  `Query`/`QueryCursor`, with rules held in a module-level per-language dict. This is the
  architecture [semgrep](https://github.com/semgrep/ocaml-tree-sitter-semgrep) and
  [ast-grep](https://ast-grep.github.io/advanced/tool-comparison.html) build on top of tree-sitter:
  rules-as-data are declarative, independently testable, and adding a language/rule never touches
  traversal logic — which matters for blind jailed workers, since the brief can embed the exact
  query strings and the worker cannot mis-implement a recursive walk.
* **Packaging — official per-language grammar wheels, NOT a language pack**: P3 installs
  `tree-sitter` core plus `tree-sitter-c`, `tree-sitter-java`, `tree-sitter-javascript` — all
  maintained by the [tree-sitter org](https://github.com/tree-sitter/py-tree-sitter), each with the
  compiled grammar bundled INSIDE the wheel (zero runtime downloads → safe for the offline jail and
  deterministic verification). Alternatives considered:
  [tree-sitter-language-pack](https://github.com/kreuzberg-dev/tree-sitter-language-pack) (305+
  languages, single dep) loses because its current line fetches parsers on demand at runtime —
  a network dependency inside what must be a hermetic verification path; revisit only if the
  language matrix grows large, and then only with a pre-warmed offline cache verified at install
  time. [semgrep](https://semgrep.dev/docs/contributing/semgrep-core-contributing) loses as a
  CLI-not-library with a heavy dependency tree; ast-grep adds a non-Python Rust binary +
  per-call subprocess; srcML covers C/C++/Java but not JS. Note `tree-sitter-languages`
  (grantjenks) is unmaintained — do not use it. [UNVERIFIED: exact current version numbers of the
  grammar wheels; P3 records them at install time.]
* **Brief**: `brief_hooks_ngv2_treesitter_verifier.md`,
  `working_dir: "/home/xnihil0zer0/NobleGreedv2"`, `task_id: ngv2-treesitter-verifier` VERBATIM,
  `meta_task_type: data_model`, `files_touched: ["ngv2/treesitter_verifier.py"]`, NEW module ⇒
  WHOLE-FILE single-file dispatch directive (LOUD), validator-floor sentence. Given the surface
  area (3 languages × rule set), consider decomposing: leaf 1 = core + C rules, leaf 2 = Java/JS
  rules — if so, author ONE root epic brief and let JM decide the tree (memory:
  [[ngv2-epic4-authored]]).
* **RED oracle** (hand-author, commit to NGv2 master FIRST, AFTER P3 installs the deps — same
  vacuous-skip warning as T2): `tests/ngv2/test_treesitter_verifier_wired.py` — differential
  extraction fixtures: a C snippet with `system("id")` + constant-return stub, a Java snippet with
  `Runtime.getRuntime().exec(...)`, a JS snippet with `child_process.execSync(...)`; assert each
  yields the expected rule/violation and a clean snippet per language yields none; one Python
  snippet cross-checked against the existing stdlib `ASTVerifier` verdict as the differential
  anchor.
* **Verification**: `python -m pytest tests/ngv2/test_treesitter_verifier_wired.py -q`,
  `working_dir=/home/xnihil0zer0/NobleGreedv2`.

---

## Prerequisites & owner-decision items

### P1 — Rewrite + commit the T1 oracle to the settled contract (hand-authorable, no pipeline run)

* **Why**: (a) memory [[untracked-test-poisons-patches-commit]] — the oracle must be committed
  before any `harness_self_fix` worker run; (b) the owner decisions (T1, settled 2026-06-11)
  invert the working-tree diff, so the oracle must pin the DECIDED contract, not the diff.
* **Action**: `git checkout -- harness/config.yaml` (decision 1: cap stays 5). Rewrite
  `tests/test_autowork_parallelism.py::test_project_isolation` + add cases pinning:
  (i) two tasks with `working_dir` resolving to the SAME external root
  (`/home/xnihil0zer0/NobleGreedv2`) ⇒ `can_run_parallel` False (serialize);
  (ii) both-`working_dir`-absent (two bare JM self-tasks) ⇒ True (parallelize — decision 3);
  (iii) one external + one bare self-task ⇒ True (different projects);
  (iv) `test_project_isolation_exact_path` — a non-external path merely *containing*
  "NobleGreedv2" (e.g. `<repo>/fixtures/NobleGreedv2-samples`) is NOT isolated (exact resolved-path
  membership in `_ISOLATED_EXTERNAL_DIRS`, never substring);
  (v) existing file-overlap/dependency cases stay green. Run the suite (the new cases must be RED
  against HEAD); commit the test file (tests are hand-authorable — no decision file needed).
* **Sequencing**: strictly before T1 dispatch.

### P2 — ✅ DECIDED + EXECUTED 2026-06-11: `z3-solver` installed in the NGv2 venv

* **Decision**: approved (owner-delegated). **Installed**: `z3-solver 4.16.0.0` into
  `/home/xnihil0zer0/NobleGreedv2/.venv`; verified live — `z3.get_version_string() == 4.16.0`,
  `Solver` correctly returns `unsat` for `Implies(a,b) ∧ a ∧ ¬b`.
* **Remaining action**: land the `requirements.txt` line `z3-solver>=4.16` in NGv2 — a one-line
  non-Python external edit that rides as a trivial `config_schema` pipeline leaf (folding it into
  the T2 brief would make T2 two-file ⇒ verbatim-manifest routing; the separate tiny leaf is
  simpler).
* **Sequencing**: T2 oracle commit is unblocked NOW; the requirements leaf can land any time
  before or with T2.

### P3 — ✅ DECIDED + EXECUTED 2026-06-11: `tree-sitter` + grammar wheels installed in the NGv2 venv

* **Decision**: approved (owner-delegated). **Installed + version-pinned**: `tree-sitter 0.25.2`,
  `tree-sitter-c 0.24.2`, `tree-sitter-java 0.23.5`, `tree-sitter-javascript 0.25.0`.
* **Verified API snippet (ran live 2026-06-11 — embed this VERBATIM in the T3 brief's `# Inputs`;
  note the 0.25 idiom uses `Query`/`QueryCursor` CONSTRUCTORS, not the older `lang.query()`)**:
  ```python
  from tree_sitter import Language, Parser, Query, QueryCursor
  import tree_sitter_c
  lang = Language(tree_sitter_c.language())
  parser = Parser(lang)
  tree = parser.parse(b'int main(){ system("id"); return 0; }')
  q = Query(lang, '(call_expression function: (identifier) @fn (#eq? @fn "system"))')
  caps = QueryCursor(q).captures(tree.root_node)   # -> {'fn': [<node 'system'>]}
  ```
* **Remaining action**: land the three `requirements.txt` lines (one `config_schema` leaf, can be
  the same leaf as P2's line).
* **Sequencing**: T3 oracle commit is unblocked NOW; independent of P2.

---

## Out of scope — already implemented at HEAD (do not redo)

* **Path-aware AST validation for non-Python targets**: `poll_for_submission` resolves
  `target_path = _submission_target_path(state_dir, task_id)` (`harness/orchestrator.py:1038`,
  helper at `:1000`) and passes `{'code': code, 'path': target_path}` at all four interceptor call
  sites (`harness/orchestrator.py:1060,1076,1098,1111`), so non-`.py` submissions get the
  interceptor's non-Python exemption. Oracle
  `tests/adversarial/test_punb3_interceptor_non_py_target.py` (committed `ad53b64`) — 2 passed,
  re-run 2026-06-11.
* **Robust git worktree cleanup**: landed via pipeline as `PHASE_STAGING_RM_NOTIMEOUT` (commit
  `87187d4`). `remove_staging_worktree` (`harness/git_integration.py:1557-1606`): prune → 3-attempt
  bounded retry of `git worktree remove -f` with `timeout=60` per call, prune between attempts,
  per-attempt exceptions never propagated → `shutil.rmtree(ignore_errors=True)` fallback.
  `create_staging_worktree` (`harness/git_integration.py:1453`) prunes stale worktrees and
  force-removes pre-existing paths before `worktree add`. Exit-128 from a held handle can neither
  hang nor crash the pipeline. Killing handle-holders by PGID was evaluated and REJECTED: it could
  kill the live daemon's own children (worker CWDs sit inside staging worktrees), and the fallback
  chain already absorbs the failure mode. If it is ever revived: `harness/git_integration.py` IS in
  `_NEVER_AUTO_APPROVE` (`harness/orchestrator.py:2295`) — per-task operator decision mandatory.
* **Retry/backoff machinery**: `_retry_blocked_tasks` (`harness/autowork_daemon.py:884-946`)
  already matches the resilience-pattern guidance of retrying only transient failures
  ([Azure Architecture Center, Circuit Breaker pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/circuit-breaker)):
  deterministic outcomes (`synthesis_or_ast_failed`, `embedded_tests_failed`,
  `narrow_fuzz_failed`) get budget 1, transient outcomes get 3 attempts with escalating backoff
  tiers (300s → 3600s → 86400s), exhaustion parks the task permanently (`.exhausted` +
  `selfheal_skip` marker = circuit-open), and a separate per-task dispatch circuit breaker
  quarantines specs dispatched 10× within 300s. No retry work item exists.

---

## Execution sequence

1. **P1** (revert config.yaml; rewrite + commit the T1 oracle to the settled decisions) → **T1**
   via the RUNNING daemon (brief + decision file + allowlist slug) → drain in-flight tasks →
   **restart the daemon** so the new scheduling semantics actually load.
2. **T2** and **T3** are independent chains, both unblocked (P2/P3 executed 2026-06-11), and may
   proceed in parallel with each other and with T1; land the shared requirements.txt
   `config_schema` leaf first or alongside. NGv2 working tree must be clean at dispatch time
   (`EXTERNAL_DIRTY_GATE`, `harness/orchestrator.py:2833-2847`).
3. Gating runs are SERIAL: do not use xdist for gates (`-n auto` flakes non-hermetic classes —
   memory: [[test-tiering-bootstrap]]; test-fast is a screen, the serial run is the gate). Gate
   each landing with the task's own `verification_command`, then a serial
   `python3 -m pytest -q` (JM) / `python -m pytest -q` (NGv2) full-suite check.
