# JanusMaskJR → Autocompiler: Synthesis Report & Epic Design

**Date:** 2026-06-09 · **Status:** RESEARCH + DECOMPOSITION ONLY (owner-gated; nothing dispatched, no flag flipped)
**Companion artifact:** [`brief_hooks_autocompiler.md`](./brief_hooks_autocompiler.md) (the prototype epic brief this report justifies)

This report synthesizes four parallel research-and-verify subagents, each grounded in the **real** JanusMaskJR codebase (exact symbols + line anchors), into a single coherent plan for turning JM from a rigid lock-step dual-agent build pipeline into an **autocompiler**: a system that reliably compiles a high-level spec/brief into verified working code via **population-based evolutionary search** under **hybrid oracles**, with **AST write-containment**, optional **multi-language (JS/TS)** targets, and **flakiness-eliminating determinism** — all additive and default-OFF.

It supersedes the framing in the two earlier root docs ([`auto_compiler_nexustranslation_report.md`](../auto_compiler_nexustranslation_report.md), [`auto_compiler_adversarial_critique.md`](../auto_compiler_adversarial_critique.md)) on the four points the codebase verification corrected.

---

## 1. What "autocompiler" means here

JM today is a **single-shot, fail-closed** factory: two agents (`claude`, `gemini`) each emit a candidate; acceptance requires they be **differentially equivalent** under the fuzzer and **AST-valid**; a single divergent fuzz input discards the *entire* candidate and the run either decomposes once or marks blocked. The generation budget is spent on **one lineage** with **no persisted cross-attempt memory** (`valid_cache` is local to `main()`).

The autocompiler keeps every existing guarantee but replaces *one-shot-or-die* with a **graduated, memory-bearing search**: candidates accumulate in a population, near-misses are *rated* rather than discarded, and selection/crossover steer compute toward the promising lineage — exactly the AlphaProof Nexus design (population DB + Elo + P-UCB + goal decomposition), translated onto JM's real seams. The verifier stays the load-bearing component (per the AlphaProof finding that the *compiler/oracle* — not the evolutionary scaffolding — carries correctness); evolution only re-allocates the budget.

---

## 2. Verified / Refuted claims (the four corrections that reshape the design)

| # | Prior-doc claim | Verdict | Evidence (real anchor) |
|---|---|---|---|
| 1 | The choke is "both agents must emit **identical edits**" | **REFUTED** | Acceptance is differential-equivalence + per-candidate AST validity, not textual agreement: `orchestrator_worker.py:598` (`fuzz_result.equivalent`), `orchestrator.py:1169` (`run_both_agents`), `:1586` (`_validate_submission`). The real waste is that a clean near-miss (fails one of ≤20 fuzz inputs, `diff_fuzzer.py:625`) is discarded with **zero retained fitness** and no cross-attempt memory (`valid_cache` local to `main()`). Elo/population closes *that* gap. |
| 2 | AST-level crossover must be built | **REFUTED (already exists)** | `git_integration.py::_ast_merge` (`:103`) does additive, by-name, namespaced top-level merge (funcs/classes/assigns/imports) — a ready crossover primitive. Staging worktrees + RO-parent gate (`:1451`/`:1606`) give per-candidate isolation. |
| 3 | Constrained decoding via Gemini `response_schema` / local Outlines | **REFUTED (no SDK boundary)** | JM has **no in-process model client** — every model call is a **CLI subprocess** (`orchestrator.py:162 _build_agent_command`, `:519 Popen`) consumed as NDJSON (`agent_streamer.py`). Repo-wide search for `generate_content`/`response_schema`/`httpx`/`api.anthropic` over `harness/**`+`overseer/**` = 0 hits. → Reframe as **post-decode schema validation + truncation repair** over the emitted submission (reasoning-field-first hazard still applies). A logit-level constraint would be a separate local-inference build (out of scope). |
| 4 | Formal (Lean/AlphaProof) oracle as a near-term lane | **REFUTED short-term** | Zero Lean/proof infra in `harness/`. The empirical differential fuzzer is mature and live (`diff_fuzzer.py`, 839 LoC; `FuzzResult`/`FuzzFailure`). → Build fitness on the **empirical** oracle now (1 counterexample = hard disproof; N clean rounds = soft proof); treat formal as far-future optional. |

**Also confirmed (enabling facts):**
- **EVOLVE-BLOCK containment is feasible** — the comment-tokenizer pattern already ships: `# JANUSMASK_DELETE:` extraction via `tokenize` at `git_integration.py:843-857`. Mapping `# JM-EVOLVE-BLOCK/VALUE` → line ranges is a near-clone.
- **No vacuity/stub detector exists** in `ast_enforcer.py::_ValidationVisitor` (`:25`) → net-new (but vacuity *is* caught empirically today by the G-MUTATION-GATE `orchestrator.py:3147-3309` and `test_author.oracle_is_non_vacuous:101`).
- **Flag idiom is proven**: `_wire_up_gate_enabled` (`orchestrator.py:2022`) — `load_config()` → fail-closed `False`; call site is a strict `if _enabled():` no-op wrapper (`:3338`). `_reap_spent_briefs_safe` (`orchestrator_worker.py:45`) is the try/except-bridge precedent.

---

## 3. The hard architectural constraint (sandboxes) and the multi-language scope cut

There are **two** sandboxes and they must not be conflated:

1. **Agent-synthesis jail** — `agent_jail.py::build_jail_argv` — bwrap, **already tight**: `~/.nvm` is `--ro-bind` (`:180`, justified anti-hijack), XDG tmpfs-masked with only `bus`+`keyring` re-bound (`:297`), D-Bus through a filtering `xdg-dbus-proxy` (`dbus_proxy.py:46`), `--unshare-net --unshare-ipc` on the execute path. The adversarial critique's "global `~/.nvm` mount" warning is **already mitigated here**.
2. **Fuzz code-execution sandbox** — `sandbox.py::Sandbox.execute` — **NOT bwrapped**; plain `Popen` under **rlimits + libseccomp that block `execve`/`socket`/`fork`** (`:665-668`) **+ per-input `os.fork()`** (`:785`).

**Consequence:** a Node spawn needs `execve`+`fork`, which the fuzz sandbox's seccomp **forbids by design**. → **JS execution must route through the bwrap `agent_jail`, not `sandbox.py`.** And `agent_jail.py` is in the irreducible `_NEVER_AUTO_APPROVE` set (`orchestrator.py:2286`) → that one edit is **owner hand-edit, cleared first**. This makes JS/TS a *later* phase, not the beachhead.

**Recommended sequencing (beachhead-first):** the **evolution core + oracle gates (Phase A)** is the highest-value, lowest-risk increment — it lives entirely in a new free package, is pure/hermetic, and proves the population loop behind a default-OFF flag without touching a single sensitive file. **Determinism + JS (Phase B) and the wiring edits (Phase C/D) follow only after Phase A is proven.**

---

## 4. Where the code lands (deny-list map → unified `autocompiler/` package)

Verified write-policy tiers:
- **Free (normal pipeline)** — anything **not** under `harness/**`, `config/**`, `scripts/**`, `services/**` (the `_SENSITIVE_APPLY_GLOBS`, `git_integration.py:16`). A **new top-level `autocompiler/` package** is free, exactly as `overseer/` is — so **all pure substrate lands there and is freely JM-rebuildable.**
- **Sensitive (`harness_self_fix` + operator decision file)** — `harness/sandbox.py`, `harness/diff_fuzzer.py`, `harness/orchestrator_worker.py`, `harness/config.yaml`, `harness/agent_streamer.py`.
- **Irreducible (`_NEVER_AUTO_APPROVE` → owner hand-edit FIRST)** — `agent_jail.py`, `orchestrator.py`, `git_integration.py`, `autowork_daemon.py`, `paths.py`, `interceptors.py`, `selfheal.py`, `dbus_proxy.py`, `services/**`.

Every new module follows the `overseer/gates.py` discipline: a **pure function returning a typed `GateResult(ok, reason, fix_hint)` over INJECTED seams** (`run_seam`, `git_seam`, `model_seam`) — it never spawns a real process/model/network, so hand-authored oracles drive it hermetically. The few sensitive edits are **additive `if ac_enabled():` wrappers / try-except bridges** that are byte-for-byte no-ops when the flag is OFF.

---

## 5. The four pillars (design summary)

**Pillar 1 — Evolutionary population core.** New `autocompiler/{population,fitness,elo,selection,crossover,loop}.py`. `PopulationDB` persists `Candidate(id, code, files, fitness, elo, n_selected, parent_ids)` as JSON under an injected `state_dir` (the `procedure_state.py` durable pattern). Elo from pairwise Flash-rater tournaments (rater = injected `model_seam`); P-UCB selection; crossover delegates to `_ast_merge` via `git_seam`. A pure `loop.step(db, seams) -> db'` transition. Terminal accept still funnels through the **unchanged** `_auto_commit_accepted` so the population winner reuses the exact staging-merge + RO-parent gate (no validator bypass).

**Pillar 2 — Hybrid oracle + write-containment.** New `autocompiler/{containment,vacuity,fitness_gate}.py`. `extract_evolve_ranges` (tokenizer clone of the `JANUSMASK_DELETE` precedent) + `check_write_containment` (AST-diff: any added node outside an EVOLVE range ⇒ violation); `check_vacuity_stub` / `check_complexity_floor` / `check_no_exception_swallow` (close the stub-catching loophole). A pure `compute_fitness(FuzzResult, gate_results, mutation_vacuous, pathology) -> vector` is the contract Pillar 1 consumes; hard rules (`integrity_crash | hard_disproof | !containment | !vacuity` ⇒ prune) keep gamed candidates out of the population. Reuses `embedded_test_runner.should_run_embedded_tests` (`:52`) to avoid re-introducing the NGv2 `test_*`-named-API-fn false positive.

**Pillar 3 — JS/TS beachhead + sandbox hardening.** Smallest viable: a **function-level JS differential runner** reusing the entire Python input-gen/compare/FuzzResult path, swapping only leaf execution. New `autocompiler/js/{node_version,js_codec,js_fork_policy,js_sandbox}.py` (pure) + `js_runner.js` (the only real Node I/O: per-batch `child_process.fork`, `await`+`Promise.race` timeout, results to **FD 3** to dodge `console.log` stdout pollution, undefined/NaN/Infinity `__sentinel__` codec so JS `undefined`≠`null`). **JS runs inside `agent_jail`**, binding only the pinned `~/.nvm/versions/node/<v>/bin` ro. No tree-sitter splicing (not installed) — JS ships whole-file only.

**Pillar 4 — Decoding, determinism, wiring.** `autocompiler/flags.py` (`ac_enabled(key)`, fail-closed) gates everything under a new default-OFF `autocompiler:` config subtree. `autocompiler/determinism.py` (pure `sitecustomize` content mounted at the `sandbox_child_env` seam) — the cleanest low-risk win. `autocompiler/decode.py` (post-decode reasoning-first schema validate + truncation repair). Wiring is additive `if ac_enabled():` hooks at `sandbox_child_env` (`sandbox.py:115`), the worker accept chokepoint (`orchestrator_worker.py:73`, mirroring `_reap_spent_briefs_safe`), and a `task['language']` dispatch in `diff_fuzzer.differential_fuzz`.

---

## 6. Risks & honest scope notes

- **Fitness is binary-ish today.** `FuzzResult` (`diff_fuzzer.py:46`) caps at 20 failures and has **no path-coverage / shrink-complexity** field. The richer fitness vectors the prior report imagined are **not extractable now**; Phase A can only derive divergence-rate + `_classify_failures` bucket-count (`task_decomposer.py:51` — NOT in diff_fuzzer, a misattribution corrected 2026-06-09). Path coverage is a separate fuzzer extension (dependency, not in this epic).
- **The wire-up gate is now ON (post-authoring correction, 2026-06-09).** `autowork.wire_up_gate: true` landed the same day this report was drafted. The accept gate (`orchestrator.py:2041-2084` via `:3338`) rejects any new non-test module not reachable from a live root and not referenced in `config/**` (`wire_up.py:354-368`), and the plan validator demands a `*_wired` oracle for every module-creating leaf (`plan_validator.py:164-185`). Phase-A modules are orphan-by-design until Phase C ⇒ without mitigation every Phase-A accept would be rejected. Mitigation adopted: register the Phase-A dotted module paths in `config/autocompiler.yaml` (the gate's sanctioned dynamic-wiring classification) + pre-commit a `tests/autocompiler/test_<name>_wired.py` wiring oracle per leaf alongside the contract oracle.
- **Circular validation.** Fitness fed by a self-authored oracle is untrusted; the `author != implementer` boundary (`test_author.author_session_dir:109`, scrubs `JANUSMASK_*`) must gate fitness too. The AST-only gates (vacuity/complexity) exist precisely to give a non-circular signal.
- **Whole-file & single-symbol discipline.** New `autocompiler/*.py` = WHOLE-FILE emission; the harness edits must be **single new helper + one-line call site** (never a rewrite of `main()`, which AST-truncates and rolls back the accept). The whole-file drift guard blocks multi-symbol re-dispatch → keep each leaf single-symbol/single-file.
- **Determinism is bounded.** Absolute determinism is impossible (GIL/libuv/ASLR/static-linking/FMA per `addendum_sandbox_determinism.md`); the layer reduces flakiness, it does not eliminate it. JS determinism (libuv thread pool) needs a *separate* node preload — out of beachhead; pin `worker_pool_size: 1`, single-threaded JS targets only.
- **Owner gates stay paused.** This epic is **decomposition/prototype only** — it authors no oracle, dispatches no build, flips no flag. The two `-wire` leaves route through `harness_self_fix` + decision; the `agent_jail` JS mount is owner hand-edit cleared first; nothing touches an irreducible file without explicit sign-off.

---

## 7. Deliverables of this research effort

1. This report.
2. [`brief_hooks_autocompiler.md`](./brief_hooks_autocompiler.md) — the prototype **epic brief** (format based on `brief_hooks_overseer_procedure_gates.md`): a single root brief describing the capability set and handing the decomposition decision to JM, with a NON-BINDING suggested leaf tree (Phases A–D), per-leaf oracle-first contracts, real target files, meta_task_types, and the safety posture. **Not dispatched.**
