---
epic: true
---

<!--
# STATUS: 🟢 DISPATCHED — PHASE A ONLY (owner-authorized 2026-06-09)
Dispatch copy of autocompiler_research/brief_hooks_autocompiler.md (the archival prototype).
Preconditions now SATISFIED:
  1. ✅ RED oracles hand-authored + committed at e567269 — 9 contract oracles
     tests/autocompiler/test_<name>.py + 9 wiring oracles test_<name>_wired.py, all
     verified RED at HEAD. config/autocompiler.yaml (same commit) registers the Phase-A
     modules for dynamic wiring so the ON wire_up_gate accepts them (mitigation verified).
  2. The decomposition below is NON-BINDING — JM decides the final tree.
  3. DISPATCH SCOPE: **PHASE A ONLY.** Decompose and build ONLY the nine Phase-A leaves.
     Phases B/C/D below are CONTEXT for a later increment — DO NOT emit child briefs for
     them in this run. Phase C needs harness_self_fix + operator decision files and Phase D
     is owner hand-edit; neither is authorized here.

All file paths, symbols and line anchors verified against HEAD 2026-06-09 (this session).
-->

# Title

JanusMaskJR Autocompiler — Population-Based Evolutionary Compilation over Hybrid Oracles. Turn JM's
single-shot, fail-closed dual-agent factory into a **memory-bearing evolutionary compiler**: instead
of discarding a clean near-miss candidate when one of ≤20 fuzz inputs diverges, candidates accumulate
in a rated **population**, near-misses are scored (not thrown away), and **selection + crossover**
steer the generation budget toward the promising lineage — keeping every existing correctness
guarantee (differential equivalence, AST validity, the RO-parent test gate) as the load-bearing
verifier. The evolutionary scaffolding only re-allocates compute; the oracle still decides truth.
Capabilities: (1) population DB + Elo + P-UCB selection + AST crossover; (2) hybrid empirical oracle +
AST write-containment + anti-gaming gates feeding a fitness vector; (3) an optional function-level
JS/TS target beachhead; (4) flakiness-reducing determinism + post-decode schema validation, all
behind a new default-OFF `autocompiler.*` flag tree. **YOU (the planner) decide the leaf tree;** a
NON-BINDING suggested grouping (Phases A–D) is given at the end.

# Scope

JM today (verified): two agents each emit a candidate; acceptance = differential equivalence under the
fuzzer (`harness/orchestrator_worker.py:598` `fuzz_result.equivalent`) + per-candidate AST validity
(`harness/orchestrator.py:1586` `_validate_submission`); a single divergent fuzz input (cap 20,
`harness/diff_fuzzer.py:625`) discards the **entire** candidate; the budget is spent on **one lineage**
with **no persisted cross-attempt memory** (`valid_cache` is local to `main()`). A near-miss — clean,
surgical, fails one input — is lost with zero retained fitness.

The autocompiler reorganizes the post-synthesis region of the worker around a **persistent population
of candidates** with a smooth, Elo-derived fitness landscape, so the search can exploit near-misses
and recombine partial successes. This mirrors the AlphaProof Nexus design (population DB, Elo via
pairwise Flash-rater tournaments, P-UCB selection, file/AST crossover, goal decomposition), translated
onto JM's REAL seams. Four pillars (each a deterministic, oracle-driven capability):

1. **Evolutionary core** — rate-and-recombine instead of one-shot-or-die.
2. **Hybrid oracle + write-containment** — make the fitness signal trustworthy and un-gameable
   (EVOLVE-BLOCK containment; vacuity/stub/complexity gates; the fitness-vector contract).
3. **JS/TS beachhead** — a function-level differential runner reusing the Python pipeline (LATER —
   needs the `agent_jail` mount, an owner hand-edit).
4. **Decoding + determinism + wiring** — the default-OFF flag tree, the determinism seam, post-decode
   schema validation, and the additive hook points.

Each capability is enforced by WITHHOLDING + CHECKING (pure gate functions), never by prompt — the JM
design principle. The verifier stays load-bearing; evolution never bypasses it.

# Inputs

FIXED inputs — do NOT rebuild any of these.

1. The research corpus: `autocompiler_research/AUTOCOMPILER_EPIC_REPORT.md` (the design + the four
   verified claim corrections), `auto_compiler_nexustranslation_report.md`,
   `auto_compiler_adversarial_critique.md`, and the four `autocompiler_research/addendum_*.md`
   (constrained decoding, loop invariants, sandbox determinism, adversarial testing).
2. The REAL JM seams the new code plugs into (treat as fixed; reuse, do not reimplement):
   - `harness/git_integration.py::_ast_merge` (`:103`) — the AST crossover primitive (additive by-name
     top-level merge); `create_staging_worktree`/`merge_staging_to_parent`/`_verify_from_ro_parent`
     (`:1451`/`:1666`/`:1606`) — per-candidate isolation + RO-parent test gate; the
     `# JANUSMASK_DELETE:` comment-tokenizer (`:840-857`) — the EVOLVE-marker extraction precedent.
   - `harness/diff_fuzzer.py` — `FuzzResult`/`FuzzFailure` (`:46`), `differential_fuzz` (`:641`) —
     the empirical oracle + the only fitness source available today (failure bucketing lives in
     `harness/task_decomposer.py::_classify_failures` `:51`, NOT in diff_fuzzer).
   - `harness/orchestrator.py` — `run_both_agents` (`:1169`), `_auto_commit_accepted` (`:2407`, the
     UNCHANGED terminal accept the population winner must funnel through), the G-MUTATION-GATE
     (`:3147-3309`), `_wire_up_gate_enabled` (`:2022`, the fail-closed flag idiom to clone).
   - `harness/orchestrator_worker.py` — `main()` (`:152`), the post-fuzz accept at `:598`, the
     `_print_json_line` accept chokepoint (`:73`) and `_reap_spent_briefs_safe` (`:45`, the try/except
     bridge precedent).
   - `harness/task_decomposer.py` — `_classify_failures`/`_decompose_by_*` (reactive decomposition to
     layer Elo-ranked re-selection ON TOP of; do NOT modify its load-bearing `decompose_task` body).
   - `harness/sandbox.py` — `sandbox_child_env` (`:115`, the determinism mount seam), the seccomp+fork
     execution model (`:665-668`/`:785`) that BLOCKS `execve`/`fork` (→ JS cannot run here).
   - `harness/agent_jail.py::build_jail_argv` — the bwrap jail (already tight) JS must route through.
   - `harness/config.yaml` + `harness/config_loader.py` — the flag tree home.
   - `overseer/gates.py::GateResult(ok, reason, fix_hint)` (`:28`) — the pure-gate idiom to mirror;
     `overseer/procedure_state.py` — the durable JSON-state pattern.

# ALREADY TRUE — do NOT rebuild (codebase-verified)

- **AST-level crossover EXISTS** as `_ast_merge` — the evolver delegates to it via a `git_seam`.
- **Per-candidate isolation EXISTS** (staging worktrees + RO-parent gate).
- **EVOLVE-BLOCK containment is FEASIBLE** — the comment-tokenizer pattern already ships.
- **The default-OFF flag idiom is PROVEN** (`_wire_up_gate_enabled` + the `_reap_spent_briefs_safe`
  try/except bridge). New work clones it.
- **A NEW top-level package dodges the deny-list** exactly as `overseer/` does (`_SENSITIVE_APPLY_GLOBS`
  = `harness/**`, `config/**`, `scripts/**`, `services/**` only — `harness/git_integration.py:16`).

# What is NET-NEW vs reframed (the four corrections — see report §2)

- The choke is NOT "identical edits"; it is the **discarded near-miss + no cross-attempt memory**. The
  population/Elo layer is the fix.
- **No vacuity/stub detector exists** in `ast_enforcer._ValidationVisitor` (`:25`) → net-new AST gates.
- **No formal/Lean oracle** is realistic short-term → fitness is built on the **empirical fuzzer only**
  (1 counterexample = hard disproof; N clean rounds = soft proof).
- **No in-process model SDK exists** → constrained decoding is reframed as **post-decode schema
  validation + truncation repair** over the emitted NDJSON submission, NOT an API `response_schema`.

# Correctness regimes (the build boundary)

DETERMINISTIC logic (the population DB, fitness/Elo/selection math, the AST containment/vacuity gates,
the JS codec/version-validator/fork-policy, the decode validator, the flag reader) is fully
JM-rebuildable and MUST be **pure/stdlib-only over INJECTED seams** (`model_seam` for a rater/agent
spawn, `run_seam` for a test run, `git_seam` for staging/merge/`_ast_merge`, plain filesystem reads
under an injected `state_dir`). It NEVER spawns a real process, model, network, or un-injected
subprocess — all such I/O flows through seams so the hand-authored oracles drive it hermetically (the
`overseer/gates.py` discipline). The INTEGRATION edits modify EXISTING symbols **additively** behind
`if ac_enabled():` and must preserve every current behaviour and passing test byte-for-byte when OFF.

THE CARDINAL PROJECT RULE this epic must never violate: NEVER hand-edit production outside the
pipeline. The free `autocompiler/**` package routes through the normal pipeline; the sensitive
`harness/**` edits route through `meta_task_type=harness_self_fix` + a `state/control/decisions/<id>.json`
approval; the irreducible `_NEVER_AUTO_APPROVE` files (`agent_jail.py`, `orchestrator.py`,
`autowork_daemon.py`, `git_integration.py`, `paths.py`, `interceptors.py`, `selfheal.py`,
`dbus_proxy.py`, `services/**`) are owner hand-edit, cleared FIRST.

# Wire-up gate (load-bearing — discovered AFTER first authoring; corrected 2026-06-09)

`autowork.wire_up_gate` is now **ON** (`harness/config.yaml`, flipped by the wire-up epic the same day
this brief was first drafted). Two hard consequences for Phase A, whose modules are orphan-by-design
until Phase C wiring:

1. **Accept gate**: `_run_wire_up_gate` (`orchestrator.py:2041-2084`, called at `:3338`) runs
   `check_wired(staging_path, <new module>)` and REJECTS any new non-test module that is neither
   reachable from a live root nor referenced from `config/**` (`wire_up.py:354-368`). Test imports do
   NOT count as importers. Mitigation (the gate's own sanctioned "dynamic wiring" classification,
   `wire_up.py::_grep_config`): the Phase-A module dotted paths are registered in
   **`config/autocompiler.yaml`** (committed BEFORE dispatch) ⇒ `check_wired` returns
   `wired=True (config)`. Phase C later upgrades them to genuinely live-wired.
2. **Plan validator**: every MODULE-CREATING leaf must name a `*_wired` test in its
   `verification_command` (`plan_validator.py:164-185`). Each Phase-A leaf therefore has TWO
   pre-committed oracles: the contract oracle `tests/autocompiler/test_<name>.py` AND the wiring oracle
   `tests/autocompiler/test_<name>_wired.py` (asserts `check_wired(repo_root,
   'autocompiler/<name>.py').wired` — RED while the module is absent, GREEN once it exists alongside
   the committed config registration).

# Per-leaf contract (oracle-first)

Each leaf's `verification_command` MUST name BOTH of its pre-committed RED oracles as
`python -m pytest tests/autocompiler/test_<name>.py tests/autocompiler/test_<name>_wired.py -q`.
Those oracles are the authoritative contracts,
HAND-AUTHORED + committed (and verified RED) BEFORE any leaf is dispatched. NEW modules are single-file
WHOLE-FILE emissions; a NEW top-level symbol in an existing file rides as an **R-anchored** trailing
node (per the documented gotcha); integration leaves are existing-symbol edits to ONE file each (do NOT
bundle multiple files — multi-file emission is fragile). Keep each harness edit a **small NEW helper +
one-line call site**, never a rewrite of a large symbol (`main()` AST-truncates and rolls back).

# Suggested decomposition (NON-BINDING — you decide the final tree; THIS RUN = PHASE A ONLY)

All `autocompiler/**` modules are NEW files in a FREE top-level package (normal pipeline). Build
**Phase A first and alone** to prove the loop; Phases B–D are listed as CONTEXT ONLY and are OUT OF
SCOPE for this run — do NOT emit child briefs for them.

Every Phase-A child brief MUST: (a) target exactly ONE new file, emitted WHOLE-FILE (never patches —
patches cannot create new files); (b) carry
`verification_command: python -m pytest tests/autocompiler/test_<name>.py tests/autocompiler/test_<name>_wired.py -q`
naming its two pre-committed RED oracles (committed at `e567269`; their docstrings + assertions ARE
the authoritative contract — implement exactly what they pin); (c) include a "# Required plan shape"
block: ONE impl task, ≥2 edge_cases mirrored in regression/property tests, the meta_task_type from
the table below.

### Phase A — Evolution core + oracle gates (FREE package, pure, hermetic, highest value / lowest risk)

| slug | target file | kind | meta_task_type | oracle | contract |
|---|---|---|---|---|---|
| `ac-flags` | `autocompiler/flags.py` | NEW whole-file | `config_schema` | `tests/autocompiler/test_flags.py` | `ac_enabled(key, state_dir=None)` fail-closed `False`; any missing key / config error ⇒ False |
| `ac-population-db` | `autocompiler/population.py` | NEW whole-file | `data_model` | `tests/autocompiler/test_population.py` | `PopulationDB.add/get/save/load` round-trips `Candidate` JSON under injected `state_dir`; unknown DB ⇒ empty, not raise |
| `ac-fitness-vector` | `autocompiler/fitness.py` | NEW whole-file | `data_model` | `tests/autocompiler/test_fitness.py` | pure `compute_fitness(FuzzResult, gate_results, mutation_vacuous, pathology) -> dict`; `error|hard_disproof` ⇒ prune-floor; deterministic, JSON-safe |
| `ac-elo` | `autocompiler/elo.py` | NEW whole-file | `data_model` | `tests/autocompiler/test_elo.py` | `expected_score`/`update_elo` match the K-factor formula; `tournament_round(pairs, rater_seam)` uses the injected rater only |
| `ac-selection` | `autocompiler/selection.py` | NEW whole-file | `planner_tooling` | `tests/autocompiler/test_selection.py` | `p_ucb(cands, c, total_n)` = argmax `Elo + c·sqrt(ln N / n_i)`; unseen (n=0) explores; ties deterministic |
| `ac-crossover` | `autocompiler/crossover.py` | NEW whole-file | `harness_plumbing` | `tests/autocompiler/test_crossover.py` | `ast_crossover(a,b)` composes non-overlapping symbols via injected `_ast_merge` seam; `file_crossover` picks per-file winners; no real git |
| `ac-containment` | `autocompiler/containment.py` | NEW whole-file | `validation` | `tests/autocompiler/test_containment.py` | `extract_evolve_ranges(src)` (tokenizer; malformed ⇒ `[]`) + `check_write_containment(parent,cand,ranges)->GateResult` (node outside range ⇒ ok=False) |
| `ac-vacuity` | `autocompiler/vacuity.py` | NEW whole-file | `validation` | `tests/autocompiler/test_vacuity.py` | `check_vacuity_stub` / `check_complexity_floor(min_by_type)` / `check_no_exception_swallow` → `GateResult`; reuse `should_run_embedded_tests` to dodge the `test_*`-API false positive |
| `ac-loop` | `autocompiler/loop.py` | NEW whole-file | `orchestration` | `tests/autocompiler/test_loop.py` | pure `step(db, seams) -> db'`: select→operate→run_seam→fitness→insert→rate; never spawns a process/model |

### Phase B — Determinism + JS/TS beachhead (FREE package; JS execution deferred to Phase D mount)

| slug | target file | kind | meta_task_type | oracle | contract |
|---|---|---|---|---|---|
| `ac-determinism` | `autocompiler/determinism.py` | NEW whole-file | `data_model` | `tests/autocompiler/test_determinism.py` | pure `_SITECUSTOMIZE_CONTENT` + writer (deterministic time/random/urandom/uuid); pure-string, no spawn |
| `ac-decode-validator` | `autocompiler/decode.py` | NEW whole-file | `validation` | `tests/autocompiler/test_decode.py` | reasoning-field-first schema; truncated JSON repaired, incomplete `edits` dropped; never raises |
| `ac-js-node-version` | `autocompiler/js/node_version.py` | NEW whole-file | `validation` | `tests/autocompiler/test_node_version.py` | resolves exact `~/.nvm/.../bin/node` subpath; rejects non-`^v\d+\.\d+\.\d+$` and any `..`-escaping `.nvmrc` (safe_subpath-style) |
| `ac-js-codec` | `autocompiler/js/js_codec.py` | NEW whole-file | `data_model` | `tests/autocompiler/test_js_codec.py` | round-trips `undefined`/`NaN`/`Infinity`/`null` distinctly via `__sentinel__` tags; `Object.is` compare hook |
| `ac-js-fork-policy` | `autocompiler/js/js_fork_policy.py` | NEW whole-file | `data_model` | `tests/autocompiler/test_js_fork_policy.py` | pure `child_process.fork` argv + process-group SIGKILL plan; no spawn |
| `ac-js-runner` | `autocompiler/js/js_runner.js` | NEW non-Python WHOLE-FILE | `harness_plumbing` | `tests/autocompiler/test_js_runner_e2e.py` | per-batch `fork`, `await`+`Promise.race` timeout (never-resolving Promise ⇒ timeout not hang), results→**FD 3**, sentinel codec, no stdout pollution |
| `ac-js-sandbox-seam` | `autocompiler/js/js_sandbox.py` | NEW whole-file | `io_adapter` | `tests/autocompiler/test_js_sandbox.py` | `execute_js_batch(...) -> list[ExecutionResult]`; spawn injected so oracle is hermetic |

### Phase C — Wiring (SENSITIVE `harness/**`; `harness_self_fix` + operator decision; additive, default-OFF)

| slug | target file | kind | meta_task_type | oracle | contract |
|---|---|---|---|---|---|
| `ac-config-tree` | `harness/config.yaml` | EDIT (additive yaml) | `harness_self_fix` | `tests/autocompiler/test_config_tree.py` | adds default-OFF `autocompiler:` subtree (master `enabled:false` + sub-keys); `load_config` exposes it |
| `ac-wire-determinism` | `harness/sandbox.py::sandbox_child_env` | EDIT R-anchored additive | `harness_self_fix` | extend `tests/test_sandbox.py` | flag OFF ⇒ child env byte-identical; ON ⇒ deterministic time across two `execute()` calls |
| `ac-wire-decode` | `harness/orchestrator_worker.py` (accept chokepoint) | EDIT R-anchored try/except bridge | `harness_self_fix` | `tests/autocompiler/test_worker_decode.py` | flag OFF ⇒ JSON line emitted identically; bridge can never raise back into `_print_json_line` |
| `ac-wire-evolution` | `harness/orchestrator_worker.py` (post-fuzz region) | EDIT R-anchored `_maybe_run_evolution` helper + 1-line call | `harness_self_fix` | `tests/autocompiler/test_worker_evolution.py` | flag OFF ⇒ single-shot accept path byte-identical; ON ⇒ routes through `autocompiler.loop.step`, winner still funnels through unchanged `_auto_commit_accepted` |
| `ac-wire-js-dispatch` | `harness/diff_fuzzer.py::differential_fuzz` | EDIT-symbol | `harness_self_fix` | `tests/autocompiler/test_lang_dispatch.py` | `task['language']=='js'` → `execute_js_batch`; default `'python'` unchanged |

### Phase D — Owner hand-edit (irreducible `_NEVER_AUTO_APPROVE`; cleared FIRST; not pipeline-dispatchable)

| slug | target file | kind | gate | contract |
|---|---|---|---|---|
| `ac-js-jail-mount` | `harness/agent_jail.py::build_jail_argv` | EDIT-symbol | OWNER hand-edit, sign-off FIRST | binds ONLY pinned `~/.nvm/versions/node/<v>/bin` ro for the JS execute path; no global `~/.nvm` tree; preserves `--unshare-net --unshare-ipc` |

### Epic plan record

`plan_autocompiler_epic.json` (shape per `plan_overseer_procedure_gates_epic.json`):
`{"plan_kind":"epic","epic":true,"epic_slug":"autocompiler","source_brief_path":"autocompiler_research/brief_hooks_autocompiler.md","source_brief_sha256":"…","child_briefs":[…],"child_slugs":[…]}`.
Each child carries `slug/title/scope/non_goals/inputs/deliverables/dependencies/interfaces` and a
`verification_command` naming its pre-committed RED oracle. Plan-shape constraints (verified at
`harness/planner/plan_validator.py`): no duplicate `task_id` (`:136`), ≥2 `edge_cases` mirrored in
regression/property tests (`:230`), literal `"integration"` in `non_goals` for every EDIT leaf (`:224`),
and the WIRING-ORACLE rule (`:164-185`): every MODULE-CREATING leaf must name a `*_wired` test in its
`verification_command` (or carry a paired `test_authoring` sibling with a matching `mutation_target`).
Dependency order: `ac-flags → {ac-population-db, ac-fitness-vector, …Phase A pure modules} → ac-loop`;
Phase B after A; Phase C after the Phase-A modules it imports; Phase D last, owner-gated.

# Deliverables

A decomposed leaf tree (one `brief_hooks_<slug>.md` per leaf) plus `plan_autocompiler_epic.json`,
covering: the evolution core + oracle gates (Phase A), determinism + JS beachhead (Phase B), the
default-OFF wiring (Phase C), and the owner-gated JS jail mount (Phase D). Each leaf names its own
pre-committed RED oracle under `tests/autocompiler/`. End state when fully built and the flag is flipped
ON: the worker's post-synthesis region runs a population loop that rates near-misses, recombines
partial successes via `_ast_merge`, and accepts the population winner through the UNCHANGED
`_auto_commit_accepted` gate — with the existing single-shot path preserved byte-for-byte when OFF.
**THIS RUN delivers the decomposition AND the nine built Phase-A modules (each turning its two
pre-committed RED oracles GREEN). Phases B–D are NOT built here.**

# Non-Goals

THIS RUN builds Phase A ONLY: no Phase-B/C/D child brief is emitted, no `harness/**` or
`_NEVER_AUTO_APPROVE` file is touched, no runtime flag is flipped (the `autocompiler:` config subtree
does not exist yet, so `ac_enabled` is fail-closed False everywhere — the built modules are inert
until the owner-gated Phase-C wiring). Do NOT author new tests: all oracles are pre-committed at
`e567269`. No new in-process model API/SDK call path — JM is CLI-subprocess only (verified); constrained
decoding is realized as **post-decode validation + truncation repair**, NOT an API `response_schema`
and NOT a logit-level Outlines/Gemma constraint (a separate local-inference build, out of scope). No
formal/Lean oracle lane (far-future). No replacement of the dual-agent agreement contract or the
diff-fuzzer accept gate — the population layers ON TOP, behind `autocompiler.population.*`, OFF. No
tree-sitter AST-splicing of JS (not installed) — JS ships whole-file only, function-level, single-
threaded (`worker_pool_size:1`) for the beachhead. No modification of `task_decomposer.decompose_task`'s
body or any `_NEVER_AUTO_APPROVE` file except the single owner-cleared `agent_jail` mount (Phase D). All
integration leaves are additive and preserve every current path and passing test; `"integration"` is
load-bearing in each EDIT leaf's `non_goals` (plan-validator requirement).
