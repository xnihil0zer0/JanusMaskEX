# Wire-Up Phase — Implementation Recommendations

**Date:** 2026-06-09
**Problem:** The build pipeline produces ORPHANED modules — a leaf passes its own isolated oracle (unit-green), gets committed, and is marked DONE while **zero live (non-test) code imports or calls it**. "IMPLEMENTATION ≠ WIRED." Confirmed orphans to date: `agy_pool.py`, the procedure-gates FSM (pre-P6), the `claude-tmux` backend.

**Goal:** Add a deterministic **WIRE-UP PHASE** that (a) requires every new-module leaf to ship a *wiring-assertion* oracle, (b) statically verifies a live importer exists before the module merges to the real branch, and (c) hard-blocks "DONE" until wiring is proven — surfacing the computed next action every turn, consistent with the existing FSM.

Synthesized from 4 parallel research passes (detail in `wire_up_research_1_chokepoints.md` … `_4_fsm_phase.md`).

---

## 1. The core finding

There is **no reachability/importer check anywhere in `harness/`** (grep-confirmed). The only post-apply verification is the leaf's *isolated* oracle + the mutation gate, both of which a standalone module passes while orphaned. That is the entire defect.

The fix has three independent, composable layers. Each can ship behind a default-OFF flag and each closes the gap at a different lifecycle stage (earliest → latest):

| Layer | Stage | Mechanism | Blast radius |
|---|---|---|---|
| **A. Wiring oracle requirement** | plan-validation (pre-spawn) | Reject any new-module leaf whose tests don't import a live entrypoint | Catches the defect *before* a worker is even dispatched |
| **B. Reachability gate** | accept / integrate (pre-merge) | Static import-graph BFS from live roots; reject if no live importer | Catches it regardless of what the worker authored |
| **C. WIRE_UP FSM phase** | overseer dispatch procedure | New phase holds the lattice so RESTORE/`Complete` (==DONE) is unreachable until WIRED | Hard-blocks the human/agent-driven path |

Ship **A + B** for autonomy coverage; add **C** for the interactive overseer path. They are belt-and-suspenders, not alternatives.

---

## 2. Layer B — the reachability gate (the load-bearing piece)

### 2.1 Reuse, don't reinvent
`harness/rebuild/discover.py:module_import_graph()` is already a production-grade, pure-stdlib AST import-graph builder returning `{module_rel -> set(intra-project modules it imports)}`. It walks the **full** tree, so it catches **function-local imports** — which is how most wiring in this repo actually works (e.g. `agy_pool`'s real wiring is a function-local import + qualified call). `discover_modules()` already partitions non-test/non-seed modules. This is trusted code (`order_modules`, `loop.py`, `harvest.py` all use it).

### 2.2 Live roots (BFS seeds)
Top-level entrypoints have inbound-import-degree 0 *by definition* — so the check must **seed from roots and BFS inward**, never flag roots themselves. Roots, derived from `config/*hooks*.json` + `__main__` blocks + bootstrap:
`orchestrator`, `orchestrator_worker`, `autowork_daemon`, `planner.cli`, the claude/gemini hooks, `webui_control`, the `overseer`/`services` entrypoints.

### 2.3 The check
```
def check_wired(repo_root, new_module_rel, *, exclude=()):
    graph = module_import_graph(repo_root)        # {mod -> imports}
    # invert: who imports X?
    importers = defaultdict(set)
    for m, deps in graph.items():
        for d in deps:
            importers[d].add(m)
    # BFS from LIVE_ROOTS over the import graph, skipping test/oracle files
    live = set(); frontier = list(LIVE_ROOTS)
    while frontier:
        m = frontier.pop()
        if m in live or is_test_or_oracle(m): continue
        live.add(m)
        frontier += list(graph.get(m, ()))
    # the module's OWN oracle does not count as a live importer (anti-laundering)
    live_importers = (importers[new_module_rel] - set(exclude)) & live
    if not live_importers:
        return GateResult.fail("orphan_unwired", module=new_module_rel)
    return GateResult.ok(importers=sorted(live_importers))
```

**Key rules:**
- **Exclude the module's own oracle** from the importer set — otherwise the test that proves the contract launders the module as "wired." This is the single most important anti-cheat move.
- **Hard-fail** on zero live importers (the dominant orphan class: wiring leaf never authored). Deterministic, zero false-negatives.
- **Soft-warn** on "imported but never called" (static call resolution is approximate — don't hard-block on it).
- **`config/**` grep supplement:** dynamically-registered wiring (config-string entrypoints like the `claude-tmux` backend, hook registrations) is invisible to the import graph. Add a secondary grep over `config/**` for the module/symbol name before declaring ORPHAN.

### 2.4 codebase-memory-mcp = advisory only, NOT the gate
The MCP **is** indexed for this repo (61,460 nodes / 182,575 edges, fresh 2026-06-09) with CALLS/IMPORTS/USAGE/DEFINES/TESTS edges and dead-code detection. **But it was empirically tested and fails both ways:**
- **False positive:** flags live `state.py` (9 real importers) as zero-import, because IMPORTS edges target the imported *symbol*, not the module node.
- **False negative:** misses `agy_pool`'s genuine function-local wiring (0 typed-edge rows; only aggregate `in_degree` caught it).

→ Use the MCP as *optional enrichment* in the failure report, never as the authority. The in-process AST check is the gate.

### 2.5 Insertion point
**`harness/orchestrator.py:3263`** — inside `_auto_commit_accepted` (`:2342`), between the mutation-gate end (`:3262`, all gates green) and `merge_staging_to_parent` (`:3271`). At that point the candidate is committed in the isolated staging worktree but **not yet on the real branch**. On failure, reuse the existing `_rollback_rejected_commit(...)` + `remove_staging_worktree(...)` + `return False` machinery verbatim; the worker then routes to `_mark_blocked` automatically. **One site covers all four accept paths** (stateful/bypass/round1/cross-exam) with **zero changes to `orchestrator_worker.py`**. Emit the failure via the existing `_emit_gate_failure` ledger pattern. Gate runs only when the leaf created a new module (skip for edits to existing files).

---

## 3. Layer A — require a wiring oracle (earliest catch)

### 3.1 Why the current oracle can't catch it
Two test runs exist:
- **Embedded gate** (`harness/embedded_test_runner.py:52` `should_run_embedded_tests`, called `orchestrator.py:3649`) — runs only the candidate's inline `test_*` in a tempdir, **structurally blind to the repo**. Can never see wiring.
- **Committed-oracle gate** (`harness/git_integration.py:1657`) — runs a separate oracle file against `git archive` of parent-HEAD + the staged module on `PYTHONPATH`, fail-closed on `rc!=0` (`:1660`). **This one CAN import live code — it is the real wiring lever.**

### 3.2 The wiring-assertion contract (precedent already in-repo)
The P6 hook leaves shipped exactly this pattern:
- `tests/overseer/test_make_seams_hook_registration.py` imports the **live** entrypoint `turn_runner.make_seams`, calls it as the runtime does, and asserts it writes `procedure_hook.SETTINGS_FRAGMENT` to `work_dir/.claude/settings.json` (`:64-69`) and exports `JANUSMASK_PROCEDURE_PHASE` (`:47-51`). An orphaned `procedure_hook.py` **fails** this test.
- `tests/overseer/test_procedure_hook_env_phase.py:17` asserts the *consumer's behavior changes* off the live env contract.

**Pattern:** import the live *producer/consumer* → drive it as the runtime does → assert the registration / call-edge / behavior-change that connects the new module. Not a mock of the seam — the real seam.

### 3.3 Enforcement
Classify a test as a wiring oracle via `_is_wiring_oracle()`: it imports a live entrypoint that is **not** the leaf and **not** under `tests/`, carries a `test_*_wired` / `registers` / `invokes` marker, and does **not** mock the seam. Then require it at:
- **(3a) Plan-validation** — `harness/planner/plan_validator.py` (~:114, where `test_authoring` already must declare `mutation_target`): emit a `missing_wiring_oracle` violation for any new-module leaf lacking one. **Earliest, cheapest, pre-spawn.**
- **(3b) Accept path** — rejection branch near `orchestrator.py:3650` as a backstop.
- **(3c) FSM** — ORACLE→DISPATCH phase exit in the overseer procedure (see Layer C).

Inject the wiring contract into the blind worker the same way impl contracts already flow: `_inject_oracle_sources` (`harness/planner/plan_normalizer.py:279`) appends oracle source verbatim under the `COMMITTED ORACLE CONTRACT` marker into `spec.implementation_notes`. Add a sibling pass that also injects the wiring requirement.

---

## 4. Layer C — WIRE_UP as an FSM phase (interactive/overseer path)

The procedure FSM lives in repo-root `overseer/` (`procedure.py`, `gate_runner.py`, `gates.py`, `mode_gate.py`, `turn_runner.py`, `mode_prompts.py`).

- `overseer/procedure.py:26` defines `Phase(name, gate, next_action)`; `advance()` (`:68-88`) is a **pure reducer**: fail→`Blocked`, pass→next phase, pass-on-last→`Complete`.
- The **dispatch** procedure (build lifecycle) is `PREFLIGHT → STAGE → BUILD → VERIFY → RESTORE`, and RESTORE's pass yields `Complete` (== DONE).

### Recommendation: insert **WIRE_UP between VERIFY and RESTORE** (a new *phase*, not a new mode)
Because DONE == `Complete` == RESTORE passing, gating DONE means putting a phase **before the terminal**.

- **(a) States** `UNVERIFIED → WIRING_CHECK_RUN → WIRED | ORPHANED` map directly onto `GateResult` with **zero reducer change**: no artifact → `_missing` (hold), ok → advance to RESTORE, fail → `Blocked` (hold).
- **(b) Gate** — add a pure `wired(report)` to `overseer/gates.py` (zero `live_importers` ⇒ ORPHAN) + a `wired` branch in `gate_runner._run_gate`, whose importer-count seam calls the Layer-B `check_wired`. (This unifies B and C on one check.)
- **(c) Hard-block DONE** three redundant ways: the FSM holds WIRE_UP so `Complete` is unreachable; extend the P6 hook `_PHASE_ORDER`/`_GATE_PHASE`/`_verdict` to deny commit/push proxies pre-WIRED (rc=2); and route daemon-path orphans at `orchestrator_worker._reap_spent_briefs_safe` (`:45`) to `_mark_blocked(..., 'orphan_unwired')`.
- **(d) Surfaced next action** — **no new code**: WIRE_UP's `next_action` string flows through the existing `turn_runner.py:318` → `mode_prompts.py:85` render path identically to every other phase ("Current phase / Next action / Last gate FAILED + Fix hint").

---

## 5. Build order (and the process trap to avoid)

> **MEMORY GOTCHA — the wire-up gate must itself be wired.** It would be self-parody to land an orphaned wire-up checker. Every piece below ships with a RED oracle that asserts *wiring*, not isolated function behavior — e.g. the FSM oracle asserts `PROCEDURE_REGISTRY` contains WIRE_UP **before** RESTORE and that `advance` returns `Blocked` on a zero-importer report; the gate oracle asserts `gates.__all__` + `gate_runner` dispatch actually reference it.

Recommended sequence (each a pipeline leaf, hand-authored RED oracle first, default-OFF flag, per the never-hand-edit-production rule):

1. **`check_wired` reachability primitive** — new module reusing `discover.py:module_import_graph`; oracle asserts orphan→fail, live-importer→pass, own-oracle-excluded. *(Foundation for both B and C.)*
2. **Layer B accept gate** — wire `check_wired` at `orchestrator.py:3263` behind `autowork.wire_up_gate` flag; oracle imports the live `_auto_commit_accepted` path and asserts an orphaned candidate is rolled back + `_mark_blocked`.
3. **Layer A plan-validation** — `_is_wiring_oracle` + `missing_wiring_oracle` violation; oracle asserts a new-module leaf without a wiring test is rejected pre-spawn.
4. **Layer C FSM phase** — `wired` gate in `gates.py` + WIRE_UP in the dispatch registry; oracle asserts registry order + reducer `Blocked` behavior + P6 rc=2 pre-WIRED.

Flags stay OFF until the owner flips them (use `scripts/flip_autowork_flags.sh`). Steps 1–2 alone close the autonomous-pipeline hole; 3–4 extend coverage to the interactive overseer.

---

## 6. Known limits (state them; don't let silence imply coverage)
- **Dynamic/config-string wiring** (entrypoints registered by name in `config/**`, plugin tables) is invisible to a static import graph → the `config/**` grep supplement (§2.3) is mandatory, and even it won't catch wiring expressed in non-Python data the runtime resolves reflectively.
- **"Imported but never called"** is only a soft-warn — precise call-reachability needs runtime tracing (the MCP's CALLS edges are approximate and proven unreliable here).
- **The MCP is advisory**, never the gate (§2.4).
- A leaf can still satisfy the wiring oracle with a *trivial* importer (a one-line `import x` added to a live file that does nothing useful). The gate proves *reachability*, not *usefulness* — code review / the mutation gate remains the backstop for "wired but inert."
