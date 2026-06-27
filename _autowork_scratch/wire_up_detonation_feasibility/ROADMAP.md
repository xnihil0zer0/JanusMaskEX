# Wire-Up Dynamic-Detonation Gate — Feasibility & Design Roadmap

Author: architecture feasibility study (read-only; constructed /tmp probes; no repo edits)
Date: 2026-06-23
Subject: Option 2 ("dynamic-detonation") for the wire-up runtime gate — factory emits a
per-leaf `integration_contract` + authors `runtime_oracles` that drive each new top-level
symbol THROUGH a LIVE_ROOT entrypoint, so the gate observes `executed_from_live_root=True`
and rejects genuine orphans.

---

## 1. VERDICT: **GO-WITH-VARIANT** (Option 2 as literally stated is a NO-GO)

Option 2 **as stated** — *"author a runtime_oracle that drives each new top-level symbol through a
LIVE_ROOT entrypoint so the gate observes execution from a live root"* — is **NOT feasible as the
universal acceptance bar.** The gate's soundness rule (`executed_from_live_root` = the symbol's
**IMMEDIATE caller's code-object file** is one of the 4 LIVE_ROOT files) is satisfiable for only a
**minority (~25-30%) of real symbols**, because most legitimately-wired symbols are called by an
intermediate harness module, not by code physically living in `orchestrator.py` /
`orchestrator_worker.py` / `autowork_daemon.py` / `planner/cli.py`. Forcing the rest to
`wire_exempt` would make `wire_exempt` swallow ~70% of all new symbols — **the gate becomes theater.**

**The variant that DOES retain teeth (recommended):**

> **Static-reachability is the FLOOR (mandatory for every new symbol); dynamic detonation is the
> BAR only for symbols that CLAIM to be on a live path** (`integration_contract` present).
> `wire_exempt` is **narrowed to "intentionally not-yet-wired / pure-data"** and is *adversarially
> validated* against the static import+call graph, not self-asserted.

Concretely, every new top-level symbol must satisfy **exactly one** of:

1. **STATICALLY REACHABLE** — there exists a static call/import path from a LIVE_ROOT to the symbol
   (transitive, via the existing `wire_up._resolved_graph` + a new symbol-level call-graph). This is
   the floor: catches the *real* permanent orphans (`_one_sided_fuzz`, `effective_pool_size`,
   `assert_pool_invariant`) which have **zero** non-test callers — empirically confirmed.
2. **DETONATED** — a declared `integration_contract` whose `runtime_oracle`, run jailed under
   `observe_symbol_execution`, produces `executed_from_live_root=True` for the symbol. This is the
   *stronger* bar, **available** (not mandatory) for the ~25-30% whose immediate caller is a
   LIVE_ROOT file, and is the only way to defeat a "statically reachable through dead code" lie.
3. **WIRE-EXEMPT** — explicitly justified + machine-checkable (see §3). Reserved for: symbols a
   sibling task wires later (staged build, §6), pure library/data helpers with a declared
   non-LIVE_ROOT internal caller, and config readers. Adversarially gated so it cannot be the escape
   hatch.

This variant keeps the cheap, sound, high-coverage check (static reachability) as the gate's TEETH
and reserves expensive/flaky detonation for the cases where static reachability is *gameable* (a
symbol statically reachable only through never-executed code). That is the right division of labor.

### Why pure Option-2 fails — the make-or-break number

The gate's `executed_from_live_root(name)` returns True **iff the symbol's immediate caller frame's
`co_filename` is one of the 4 LIVE_ROOT files.** I measured, two independent ways, how many harness
top-level callables can EVER satisfy that:

| Measure | Immediate caller CAN be a LIVE_ROOT file | Immediate caller is NEVER a LIVE_ROOT file |
|---|---|---|
| Name appears as a call-target anywhere in a live-root file (OVER-count) | 277 / 980 = **28%** | 703 / 980 = **72%** |
| Tighter bare-name-call proxy (distinct names) | 227 / 887 = **26%** | 660 / 887 = **74%** |

Both converge on **~25-30% reachable / ~70-75% structurally un-detonatable**, and the 28% is an
*over*-count (it matches any same-named attribute call, including unrelated methods), so the true
detonatable fraction is lower. The ~70% are called only from non-live-root modules (`state.py`,
`ast_enforcer.py`, `cross_examiner.py`, `sandbox.py`, `state_reconciler.py`, …). For ALL of those, a
**perfectly honest** oracle driving the real call chain still yields `executed_from_live_root=False`,
because the immediate caller's file isn't a LIVE_ROOT. **Empirically proven by PROBE 3 below.**

Recent factory output confirms the split is live, not historical: of the last 80 "Integrate
validated code" commits, **36 new non-test production top-level symbols** landed; **33% in a
live-root file, 67% in another harness module.** And of the 3 "confirmed wired" subjects the backtest
handed me, **only 1 of 3 is gate-passable as-is** (see §2).

---

## 2. CONSTRUCTED-ORACLE PROOFS (the central feasibility evidence)

All probes import the REAL `harness.wire_up` + real harness modules from the repo, drive a real
LIVE_ROOT entrypoint (`run_pipeline`) or a real production caller, and read
`observe_symbol_execution`. Probe scripts: `/tmp/wireprobe/probe.py`, `/tmp/wireprobe/probe2.py`.
Python 3.13.0 (`co_qualname` present, so the gate's top-level-only rule is exact).

### Subjects chosen at different depths from a LIVE_ROOT

| # | Symbol | Immediate caller | Caller's file | Depth | `executed_from_live_root` |
|---|---|---|---|---|---|
| 1 | `_save_final_output` | `run_pipeline` | `harness/orchestrator.py` (LIVE_ROOT) | 1 | **True** ✅ |
| 2 | `_restrict_sidecar_to_declared` | `_auto_commit_accepted` | `harness/orchestrator.py` (LIVE_ROOT) | 2 | **True** ✅ |
| 3 | `detect_and_heal_stalls` | `reap_orphaned_workdirs` | `harness/state_reconciler.py` (NOT live-root) | 3 (daemon→…→here) | **False** ❌ (but it IS wired) |
| 4 | `effective_pool_size`, `assert_pool_invariant` (orphans) | test | test file | — | **False** ✅ (correctly rejected) |

#### PROBE 1 — `_save_final_output` (baseline, depth-1)
```
save_final_output: executed=True  executed_from_live_root=True
   reached_from = /home/xnihil0zer0/JanusMaskJR/harness/orchestrator.py
```
**How hard:** moderate. Reused the established `_drive_run_pipeline` pattern from
`tests/harness/test_wire_up_runtime_observe.py`: drive `run_pipeline` for ONE bypass iteration with
**~8 collaborators mocked at source** (`run_both_agents`, `_validate_submission`, `get_next_task`,
`smoke_import`, `run_embedded_tests`, `run_narrow_fuzz`, `control_gate.await_decision`,
`time.sleep`→`_StopLoop`) and `_save_final_output` left UNMOCKED so its real body runs and is
observed through a genuine production edge.

#### PROBE 2 — `_restrict_sidecar_to_declared` (depth-2, the generalization test)
```
restrict_sidecar: executed=True  executed_from_live_root=True
   reached_from = /home/xnihil0zer0/JanusMaskJR/harness/orchestrator.py
```
**How hard:** moderate-plus. Same `run_pipeline` drive, but this time `_auto_commit_accepted` was
**left UNMOCKED** (so it really calls the target) — I had to (a) write a real sidecar JSON at
`state/output/<tid>.files.json` with a key to drop, and (b) patch `_resolve_files_touched` to a
deterministic list so the `if sidecar_path.exists():` branch reaches line 2783. `_auto_commit_accepted`
then ran for real, dropped the undeclared key, and died at the later `git rev-parse` (expected — no
git in tmp) AFTER the target call. **This proves the pattern generalizes to symbols not directly
called by the entrypoint — as long as the immediate caller lives in a LIVE_ROOT file.**

#### PROBE 3 — `detect_and_heal_stalls` (the killer case)
```
detect_and_heal_stalls: executed=True  executed_from_live_root=False
   reached_from = /home/xnihil0zer0/JanusMaskJR/harness/state_reconciler.py
```
This symbol **IS statically wired** (autowork_daemon `_iteration` → `_reclaim_zombie_briefs` →
`reap_orphaned_workdirs` → here). I drove it through its real production caller. It executed, but
`executed_from_live_root=False` **because its immediate caller `reap_orphaned_workdirs` lives in
`state_reconciler.py`, not a LIVE_ROOT file.** **No oracle can flip this to True without changing
where the symbol is CALLED FROM** (i.e. relocating the call into a live-root file — a code change,
not a test). This is the empirical proof that pure Option-2 false-rejects the ~70% majority.

#### PROBE 4 — orphans (must stay False)
```
effective_pool_size:   executed=True  from_live_root=False  caller=<test file>
assert_pool_invariant: executed=True  from_live_root=False  caller=<test file>
```
Both confirmed as permanent orphans (zero non-test callers in the whole tree). Under the
recommended VARIANT, the **static-reachability floor** catches these regardless of any oracle —
which is exactly the desired teeth.

#### Side-finding — methods are invisible to the gate
`observe_symbol_execution` only records calls whose `co_qualname == co_name` (module-top-level
functions). A new **method** on a class (`Foo.mymethod`) is NEVER observed (probe-confirmed). This is
consistent with `new_top_level_callables` (also top-level only), so new methods are simply out of the
symbol gate's scope — neither flagged nor checkable. Worth stating explicitly in any "what the gate
covers" doc; do NOT attempt to extend detonation to methods (huge scope, low value).

### Probe takeaways for the design
- The detonation pattern is **REAL and generalizes** to LIVE_ROOT-file-caller symbols (Probes 1+2).
- It is **structurally impossible** for the majority (Probe 3) — not an authoring-skill problem, a
  call-site-location fact.
- Authoring cost even for the "good" cases is non-trivial: ~8 source-mocks + targeted real-collaborator
  un-mocking + fixture state. Heavy paths (`_jailed_popen` via `differential_fuzz`) need a real
  subprocess spawn (bwrap-jailed if available) + filesystem_root I/O — flaky and slow at gate time.

---

## 3. ABUSE / GAMING OF `wire_exempt` — making it adversarially validated

Today `wire_exempt` is a **self-declared set** read straight off the task (`task['wire_exempt']` or
`constraints['wire_exempt']`), coerced to a set, and any listed symbol is unconditionally suppressed.
That is a universal escape hatch: a leaf gaming the gate simply lists its own new symbol. **This must
change or the gate is theater regardless of detonation.**

Design — `wire_exempt` becomes a **claim with a typed reason + machine evidence**, validated at the
gate, fail-closed:

**Schema** (per symbol, not a bare set):
```json
"wire_exempt": {
  "_one_sided_fuzz": {"reason": "staged_sibling", "wired_by_task": "diff-fuzz-wiring-impl"},
  "_norm_path":      {"reason": "pure_helper",    "internal_caller": "harness/foo.py::bar"},
  "_flag_enabled":   {"reason": "config_reader"}
}
```

**Allowed reasons + their adversarial check (all checks computed gate-side, never trusted from the
task):**

| reason | When legitimate | Gate-side validation (fail-closed) |
|---|---|---|
| `staged_sibling` | A peer task in the SAME plan adds the call that wires it | `wired_by_task` MUST be a task id in this plan's `required_task_ids`/graph AND that task's `files_touched` must include a LIVE_ROOT-reachable module. Re-checked at plan completion (§6); a *single*-task plan can NEVER use this reason. |
| `pure_helper` | Library/data util called only by other harness code | The declared `internal_caller` must (a) exist as a real symbol, (b) actually reference this symbol (static call-graph edge), and (c) itself be statically reachable from a LIVE_ROOT. I.e. the helper is reachable but its immediate caller isn't a live-root file (the Probe-3 class). **This is the legitimate home for the ~70%.** |
| `config_reader` / `flag_reader` | `_*_enabled`/config accessor inert until a knob flips | Symbol body must be pure (no new top-level side-effecting call); name/shape heuristic + AST check that it only reads config and returns. Capped — abuse-prone, so keep the AST check strict. |
| `data_only` | dataclass/constant/enum, not a callable path | Not actually a callable per `new_top_level_callables`, so usually never even flagged; if flagged (lambda alias), require it be assigned-not-called. |

**The hard rule that gives `wire_exempt` teeth:** a `pure_helper` / `staged_sibling` claim is
**rejected** unless the gate can independently confirm the symbol is **statically reachable from a
LIVE_ROOT** (transitive call/import graph). So the only thing `wire_exempt` can suppress is a symbol
the *static floor already accepts* — it downgrades "must detonate" to "static reachability suffices,"
it can NEVER suppress a true orphan. A leaf listing a genuine orphan under `pure_helper` fails the
reachability re-check and is rejected. **This collapses the escape hatch:** `wire_exempt` is no longer
"trust me," it's "the static graph agrees with you."

This requires a new gate-side primitive: **symbol-level static reachability**
(`harness/wire_up.py::symbol_reachable_from_live_root(repo_root, module_rel, symbol) -> bool`),
built on the existing `_resolved_graph` (module edges) + a new intra/inter-module **call-graph** over
top-level defs. This primitive is also the §1 floor. It is the single most important new capability —
more important than the jailed detonator — because it is cheap, sound, deterministic, and covers
100% of symbols (not 30%).

---

## 4. WORKSTREAM A — CONTRACT SCHEMA + EMISSION

### Confirmed schema the gate already reads (orchestrator.py:2293-2315)
```json
"constraints": {
  "integration_contract": {
    "entrypoints":    ["harness/orchestrator.py"],   // each MUST be in LIVE_ROOTS
    "symbols":        ["brand_new"],                  // bare top-level names
    "runtime_oracle": "tests/harness/test_x_runtime.py"  // pytest module path, non-empty
  }
}
```
`_contract_valid = bool(entrypoints) and all(ep in LIVE_ROOTS) and bool(runtime_oracle)` — **purely
static today (no observation).** `wire_exempt` is read EITHER as a top-level task field OR
`constraints['wire_exempt']`, coerced to a set.

### How it gets populated — recommendation
**Brief-declared, planner-passthrough.** Rationale established by the pipeline-mapping pass:
- `harness/planner/staging.py::stage_task` serializes the matched plan-task dict **verbatim with NO
  field filtering** (only mutates `working_dir`). So **any field the planner emits on the task
  survives into task.json.** No staging change needed.
- BUT brief frontmatter is a **closed-set parse** (`brief_loader.py`): unknown keys (incl.
  `integration_contract`/`wire_exempt`) are silently dropped, and the blind_draft plan schema never
  emits `constraints`. So the brief→task path is currently severed for these fields.

**Minimal reliable mechanism (two seams):**
1. **`harness/planner/brief_loader.py`** — extend `_coerce_optional_brief_fields` (and the
   `PlanningBrief` dataclass) to parse two new optional frontmatter blocks: `integration_contract`
   (dict) and `wire_exempt` (dict, the §3 typed form). Mirror exactly how `required_task_ids` /
   `required_child_slugs` are already parsed (closed-set, validated shapes).
2. **`harness/planner/blind_draft.py`** — in the plan-draft schema/prompt assembly (~296) and the
   per-task normalization, **stamp** the brief's declared `integration_contract`/`wire_exempt` onto
   the matching task's `constraints` (match by `required_task_ids` / slug). The planner agent is NOT
   asked to *invent* the contract (it would hallucinate live roots) — the human brief declares it and
   the planner just threads it through. This matches the owner rule "the only hand-authored artifact
   is the brief."

**Do NOT** make the planner-agent infer the contract (entrypoint inference is exactly the kind of
guess that produces lying contracts). **Do NOT** derive it at test_authoring time (chicken-and-egg:
the oracle needs the contract to know what to drive).

Files a brief would touch to build A: `harness/planner/brief_loader.py`,
`harness/planner/blind_draft.py` (both non-LIVE_ROOT modules — note these are themselves in the
~70%, so their own new helpers will need `pure_helper` exemptions: dogfood the §3 mechanism).

---

## 5. WORKSTREAM B — LIVE-ROOT ORACLE AUTHORING (test_authoring)

The test_authoring stage (`orchestrator.py` prompt ~1475 "TEST-AUTHORING DISPATCH"; standalone role
`harness/test_author.py`) must learn to produce **a live-root-driving oracle OR a correct
`wire_exempt` claim.** Today it writes a hermetic UNIT test that calls the symbol directly (immediate
caller = test file → False). That is the entire reason 113/114 tests/harness oracles can't drive a
live root.

**What the stage must produce when `integration_contract` is present on the task:**
- A pytest module that, for each contract `symbol`, drives the declared `entrypoint` (a LIVE_ROOT
  function such as `run_pipeline`) for one bounded iteration, leaving the target symbol UNMOCKED, and
  asserts `obs.executed_from_live_root(symbol, LIVE_ROOTS) is True` under `observe_symbol_execution`.
- The canonical template is **already in the tree**: `tests/harness/test_wire_up_runtime_observe.py`
  `_drive_run_pipeline`. The prompt must **inject this driver pattern verbatim** as the reference
  scaffold (the ~8 source-mocks + un-mock-the-target idiom). Agents will not reinvent it reliably;
  hand them the skeleton.

**Prompt/spec changes (`harness/orchestrator.py` test-authoring block + `harness/test_author.py`
`build_author_prompt`):**
1. Add a "LIVE-ROOT DETONATION ORACLE" clause activated when the task carries an
   `integration_contract`: state the entrypoint, the symbols, the LIVE_ROOTS, and paste the
   `_drive_run_pipeline`-style scaffold + the `observe_symbol_execution`/`executed_from_live_root`
   assertion shape.
2. Keep the existing non-vacuity gate (must FAIL a mutant) AND add a **detonation non-vacuity gate**:
   the authored oracle must FAIL (not error) when the target symbol is replaced by a no-op / when run
   without the un-mock — i.e. it must genuinely *observe* execution, not assert `True`.
3. If the symbol is NOT detonatable (Probe-3 class), the stage must instead emit the §3 `pure_helper`
   `wire_exempt` claim with the real internal caller — and the brief should pre-declare which path.

**Flakiness / latency / jailing concerns (this is where the cost lives):**
- The oracle runs **jailed at gate time AND at verification time.** A `run_pipeline`-drive oracle that
  mocks ~8 collaborators is fast and deterministic. But a symbol on the fuzz path (`_jailed_popen`)
  forces `differential_fuzz` → real subprocess spawn (bwrap-jailed) + filesystem_root I/O → **slow
  (seconds), flaky, and needs bwrap present.** Recommendation: for such heavy-path symbols, prefer the
  `pure_helper` exemption (their immediate caller `Sandbox.execute` is in sandbox.py, non-live-root,
  so they CAN'T detonate anyway — Probe-style confirmed by the call-trace).
- `observe_symbol_execution` clobbers `sys.settrace`; under pytest with coverage.py active it
  restores byte-for-byte (designed for this), but the jailed gate runner should run the oracle with
  coverage OFF to avoid tracer contention and latency.
- **Timeout budget:** the gate's jailed oracle re-run needs a bounded timeout (brief proposes 120s);
  fail-CLOSED to "not observed" on timeout. Under the recommended variant, a timeout does NOT
  auto-reject (static floor still applies) — it just denies the *detonation upgrade*, which is the
  correct fail-safe.

---

## 6. WORKSTREAM D — STAGED-BUILD TOLERANCE

The risk: task T1 adds symbol `S` to module M; sibling task T2 (same plan) adds the call that wires
`S` from a live-root-reachable module. If the gate evaluates T1 in isolation, `S` looks like an
orphan and T1 is rejected, even though the plan as a whole wires it.

**Seam — evaluate the staged-sibling exemption at PLAN COMPLETION, consult the task graph:**
- The `staged_sibling` `wire_exempt` reason (§3) defers the verdict: at T1's gate, the claim is
  *accepted provisionally* iff `wired_by_task` is a real sibling in this plan's
  `required_task_ids`/graph (the enforcement layer for `required_task_ids` already exists —
  `validate_plan`'s `missing_required_task`, landed c6b28e0 — so the task-graph is available).
- Add a **plan-completion re-check** (new seam, cleanest in `harness/state_reconciler.py` or a
  brief-completion ledger hook — the "Layer 2 brief-completion ledger" that `required_task_ids`
  enforcement explicitly left TODO): once ALL sibling tasks of the plan are accepted, re-run
  **symbol_reachable_from_live_root** for every `staged_sibling`-exempted symbol against the FINAL
  merged tree. If still unreachable → emit `orphan_symbol_unwired_post_plan` (report first, then
  enforce). This closes the gap where T2 never lands but T1's exemption stays.
- **A single-task plan can never claim `staged_sibling`** (no sibling to point at) — prevents the
  trivial dodge.

This avoids the brittle alternatives (don't try to evaluate mid-plan ordering, don't add a TTL grace
marker that silently expires). The task graph is the ground truth; use it.

---

## 7. WORKSTREAM C — GATE-SIDE (jailed observe, now PRIMARY)

The candidate mechanism in `brief_hooks_wire_up_contract_runtime_hardening.md` is **sound and
should be adopted** — with the framing change that it is now the **upgrade bar**, not the sole
suppressor:

- New primitive `harness/wire_up.py::observe_oracle_from_live_root(oracle_path, symbols, *,
  staging_path, worktree_root, state_dir, sandbox_enabled, jail_env, jail_extra_ro, jail_extra_rw,
  timeout=120) -> set` — runs the oracle in a **bwrap jail with vcmd parity**
  (`agent_jail.build_jail_argv(..., bind_credentials=False)`, `--unshare-net --unshare-ipc`, rooted
  at `staging_path`, base/prefix venv binds), under `observe_symbol_execution`, and returns the set
  of symbols observed `executed_from_live_root`. **Fail-CLOSED to `set()`** on sandbox-off /
  jail-build / exec / timeout / parse failure. Imports only `from harness import agent_jail` (no
  `orchestrator`/`load_config` — circular-import hazard).
- The in-process option (run the oracle inside the orchestrator) is correctly REJECTED: it imports
  attacker-influenced oracle code into the trust-core accept chokepoint and clobbers `sys.settrace`
  in a hot path.

**What changes now that observation is PRIMARY (vs. a hardening of a declared check):**
1. The suppression criterion in `_run_wire_up_gate` becomes the §1 disjunction, not just the brief's
   `_contract_valid and S in _observed`:
   ```
   uncovered = [S for S in new_syms
                if not symbol_reachable_from_live_root(staging_path, rel, S)   # FLOOR
                and not (contract_valid and S in observed)                     # DETONATION upgrade
                and not wire_exempt_validated(S, task, staging_path)]          # §3 checked exemption
   ```
   The **static floor must be the first clause** — it's the cheap, sound, 100%-coverage check; the
   jailed detonator only runs to defeat "reachable through dead code" lies.
2. **Path/mount resolution is the #1 false-positive risk** (brief BLOCKER-1): the jailed runner must
   import the STAGED `harness.wire_up` and resolve LIVE_ROOTS inside `staging_path` (PYTHONPATH/cwd =
   staging_path first), or honest oracles silently fail-closed. The brief's BLOCKER-1 is *exactly*
   the "can we author a live-root oracle at all in the gate's jail" question — which is why brief #1
   below must PROVE it end-to-end before anything else is built.
3. Detonation is computed **only when the contract claims it** (symbol in some contract's `symbols`),
   so the common case (static-reachable, no contract) never pays the jailed-subprocess cost.

---

## 8. ORDERED PIPELINE-BRIEF ROADMAP

Sequenced so the **foundational/riskiest piece is validated by brief #1**, not the last. The two
genuinely make-or-break unknowns are: (R1) *can the gate's jailed runner author+observe a live-root
oracle at all?* and (R2) *is symbol-level static reachability sound + cheap enough to be the floor?*
Both are front-loaded.

> Legend — stage types: `test_authoring` (TA), `harness_self_fix` (HSF, TRUST-CORE files need an
> operator decision file even with auto_approve). Patch mech: `PATCHES` = single `__JANUSMASK_PATCHES__`
> symbol patch (split one-file-per-task per the multi-file rule); `submission.py` for TA.

### Brief 0 (PRE-WORK, non-pipeline, owner+me): freeze the VARIANT decision
Not a dispatchable brief — a decision record. Confirm GO-WITH-VARIANT (static floor + detonation
upgrade + validated wire_exempt). Everything below assumes it. **Riskiest unknown:** owner may want
pure Option-2; this study says that's a NO-GO — needs sign-off before spending build budget.

### Brief 1 — `wire-up-symbol-static-reachability-primitive` ⟵ **FIRST + de-risks R2 (the FLOOR)**
- **Stage:** TA (oracle) + HSF (impl) pair. Files: `harness/wire_up.py` (HSF, R-anchored on
  `check_wired`/`_resolved_graph`); `tests/harness/test_symbol_static_reachability.py` (TA).
- **Patch:** PATCHES (one new top-level fn `symbol_reachable_from_live_root`, R-anchored).
- **Delivers:** the §1/§3 FLOOR — symbol-level static reachability over a new top-level-def call-graph
  + the existing module `_resolved_graph`. Oracle MUST prove: the 3 confirmed wired subjects
  (`_restrict_sidecar_to_declared`, `detect_and_heal_stalls`, `_jailed_popen`) read **reachable**, and
  the 4 confirmed orphans (`_one_sided_fuzz`, `_capture_golden`, `effective_pool_size`,
  `assert_pool_invariant`) read **unreachable**. (These are the ground-truth test subjects this study
  already validated by hand — the oracle encodes them.)
- **Depends on:** nothing (pure, stdlib + existing graph).
- **Riskiest unknown:** does a sound static call-graph (handle aliased imports, `getattr`-dispatch,
  re-exports) avoid both false-orphans AND false-reachable? This is R2 — validate it FIRST because the
  whole variant rests on the floor being trustworthy.

### Brief 2 — `wire-up-jailed-oracle-detonation-poc` ⟵ **de-risks R1 (the make-or-break authoring Q)**
- **Stage:** TA (oracle) + HSF (impl). Files: `harness/wire_up.py`
  (`observe_oracle_from_live_root`, R-anchored on `observe_symbol_execution`);
  `tests/harness/test_observe_oracle_from_live_root.py` (TA).
- **Patch:** PATCHES.
- **Delivers:** the §7 jailed runner. The oracle MUST PROVE (per brief BLOCKER-1) the **honest path**:
  a real `_drive_run_pipeline`-style oracle, run through the jailed runner against a real
  JanusMask-worktree staging tree, **positively observes** `_restrict_sidecar_to_declared`
  `executed_from_live_root=True` (this study already proved the un-jailed in-process version — Probe
  2 — so the new risk is purely the JAIL/path-mount layer). AND fail-closed empty set for
  lying/missing/timeout/sandbox-off.
- **Depends on:** none structurally; sequence AFTER brief 1 so we know the floor exists.
- **Riskiest unknown:** **R1 — staging-tree path/mount resolution.** Does the jailed child import the
  STAGED harness and resolve LIVE_ROOTS inside `staging_path`? If this can't be made to work,
  detonation is dead and only the static floor survives (still a viable, teeth-ful gate — so this
  brief failing is NOT fatal to the program, which is why the floor is brief 1).

### Brief 3 — `wire-up-exempt-validation-primitive`
- **Stage:** TA + HSF. Files: `harness/wire_up.py` (`wire_exempt_validated` / reason-checker);
  `tests/harness/test_wire_exempt_validation.py`.
- **Patch:** PATCHES.
- **Delivers:** §3 adversarial `wire_exempt` validation — a listed symbol is suppressed ONLY if the
  static floor (brief 1) confirms reachability via the declared internal caller, or `staged_sibling`
  points at a real plan task. Oracle proves a fake `pure_helper` claim over a true orphan is REJECTED.
- **Depends on:** brief 1 (uses the floor primitive).
- **Riskiest unknown:** the `staged_sibling` task-graph lookup at gate time — is the plan graph
  available in `_run_wire_up_gate`'s scope, or does it need threading through?

### Brief 4 — `wire-up-contract-emission-brief-passthrough`
- **Stage:** HSF ×2 (split). Files: `harness/planner/brief_loader.py` (parse frontmatter
  `integration_contract`/`wire_exempt`); `harness/planner/blind_draft.py` (stamp onto matching task
  `constraints`).
- **Patch:** PATCHES per file (one-file-per-task split).
- **Delivers:** Workstream A — briefs can declare the contract; planner threads it to task.json
  verbatim (staging already passes it through). Oracle proves a brief-declared contract lands in the
  task's `constraints.integration_contract`.
- **Depends on:** nothing in 1-3 (independent plumbing) — but dispatch after 1-2 so the schema it
  emits is the one the gate consumes.
- **Riskiest unknown:** matching a brief's contract block to the right task in a multi-task plan
  (by `required_task_ids`/slug) — mis-stamping would attach a contract to the wrong symbol.

### Brief 5 — `wire-up-detonation-oracle-authoring-prompt`
- **Stage:** HSF ×2. Files: `harness/orchestrator.py` (test-authoring DISPATCH block — TRUST-CORE,
  operator decision file); `harness/test_author.py` (`build_author_prompt`).
- **Patch:** PATCHES.
- **Delivers:** Workstream B — when a task carries an `integration_contract`, the test_authoring prompt
  injects the `_drive_run_pipeline` scaffold + the `executed_from_live_root` assertion + the detonation
  non-vacuity requirement (and, for non-detonatable symbols, the `pure_helper` exemption guidance).
- **Depends on:** briefs 2 (the gate must accept the oracle shape) + 4 (the contract must exist on the
  task to trigger the clause).
- **Riskiest unknown:** can the agent reliably produce a passing detonation oracle from the scaffold,
  or does it need the exact module/entrypoint pre-baked? May require iterating the prompt.

### Brief 6 — `wire-up-gate-variant-wiring` (REPORT mode)
- **Stage:** HSF. File: `harness/orchestrator.py` `_run_wire_up_gate` (TRUST-CORE, operator decision
  file). Patch: PATCHES on the existing `_run_wire_up_gate` symbol.
- **Delivers:** Workstream C — rewire the `uncovered` criterion to the §1/§7 disjunction (static floor
  ∨ detonation-observed ∨ validated-exempt). Ships behind the existing default-OFF
  `wire_up_runtime_gate` knob, REPORT-only. Resolve brief BLOCKER-2 (the two enforce tests with
  non-existent oracles must be updated to the variant's behavior — own them here).
- **Depends on:** briefs 1, 2, 3 (all three suppression clauses must exist).
- **Riskiest unknown:** the locals-scope problem (brief: `_venv_jail_env`/`verify_extra_ro` are
  worker-spawn locals NOT visible in `_run_wire_up_gate`; derive jail env from `_cfg`/`sys.prefix` +
  `_vcmd_scrubbed_env`).

### Brief 7 — `wire-up-staged-sibling-plan-completion-recheck`
- **Stage:** TA + HSF. File: `harness/state_reconciler.py` (or brief-completion ledger hook) — the
  plan-completion re-check. Patch: PATCHES.
- **Delivers:** Workstream D — re-run `symbol_reachable_from_live_root` for `staged_sibling`-exempted
  symbols once all plan siblings land; emit `orphan_symbol_unwired_post_plan`.
- **Depends on:** briefs 1, 3.
- **Riskiest unknown:** detecting "plan complete" reliably (which seam owns brief/plan completion).

### Brief 8 — `wire-up-runtime-gate-shadow-soak` (no code; OPERATIONAL)
- Run REPORT-mode over real traffic; measure the false-orphan rate and the wire_exempt-claim
  distribution. **GATE for flipping `wire_up_runtime_gate_enforce`** — do not flip until shadow soak
  shows a clean, explainable report stream (per the owner rule: BUILT ≠ WORKS; done = observed-working,
  never a green gate).
- **Depends on:** briefs 1-7 landed + the knob flipped to REPORT.
- **Riskiest unknown:** does the static floor produce a tolerable false-orphan rate on real
  factory output, or does the call-graph need refinement (back to brief 1)?

### Brief 9 — `wire-up-runtime-gate-enforce-flip` (CONFIG, owner-gated)
- Flip `wire_up_runtime_gate_enforce: true` after a clean soak. Single config edit, owner sign-off.

---

## 9. THE SINGLE BIGGEST RISK + how the roadmap front-loads it

**Biggest risk:** that the gate, in trying to be a *runtime* gate, becomes a *toothless* gate —
because the runtime-detonation criterion is structurally unsatisfiable for ~70% of real symbols
(Probe 3), the team is tempted to make `wire_exempt` a self-declared catch-all to keep the pipeline
moving, and orphans then slip through the exemption. This is the exact failure the owner-memory warns
about: a cheap proxy ("contract present" / "wire_exempt listed") Goodharted as a stand-in for "wired."

**How the roadmap front-loads it:**
- It **rejects pure Option-2** up front (Brief 0 decision) so we never build a 30%-coverage gate.
- It makes the **static-reachability FLOOR the very first brief** — the cheap, sound, 100%-coverage
  check that is the actual teeth — so the gate has bite even if detonation (briefs 2,5) never works.
- It makes `wire_exempt` **adversarially validated against that floor** (brief 3) — closing the escape
  hatch *before* the gate is wired (brief 6), so suppression can never exceed what the static graph
  independently confirms.
- It validates the two true make-or-break unknowns (R1 jailed-oracle authorability, R2 static-graph
  soundness) in **briefs 1 and 2**, not at the end, using the seven concrete ground-truth subjects
  this study already verified by hand.

---

## 10. WHAT I NEED YOUR DECISION ON BEFORE BRIEF #1

1. **Confirm GO-WITH-VARIANT** (static floor mandatory + detonation as an upgrade bar for
   live-path-claimants + adversarially-validated `wire_exempt`). Pure Option-2 as briefed is a NO-GO;
   I will not author briefs for it. *If you insist on pure detonation-only, stop — I'll bring evidence,
   not briefs.*
2. **`wire_exempt` reason taxonomy (§3)** — confirm the four reasons (`staged_sibling`, `pure_helper`,
   `config_reader`, `data_only`) and the hard rule that every non-`staged_sibling` exemption must
   pass the static-reachability floor. This is the anti-gaming lynchpin; I want it nailed before
   brief 3.
3. **Methods are out of scope** — confirm we explicitly DON'T try to detonate or statically-check new
   class methods (the observer can't see them; `new_top_level_callables` doesn't enumerate them). I
   recommend stating this as a known coverage gap, not closing it.
4. **Brief-declared contract (§4) vs any planner inference** — confirm the contract/exemption is
   authored in the BRIEF (frontmatter) and only threaded by the planner, never inferred. (Aligns with
   "the only hand-authored artifact is the brief.")
5. **Heavy-path symbols** (`_jailed_popen` & the fuzz path) — confirm we route these to `pure_helper`
   exemption rather than authoring slow/flaky subprocess-spawning detonation oracles. They can't
   detonate anyway (caller in sandbox.py), so this is forced — but I want explicit sign-off that we
   accept "statically reachable" as sufficient for them.

---

## STACK-ANCESTOR VARIANT (owner-confirmed 2026-06-23)

**Owner directive:** replace the runtime gate's IMMEDIATE-CALLER live-root rule with a
STACK-ANCESTOR rule. A watched symbol counts as "executed from a live root" iff a LIVE_ROOT-file
frame is an **ANCESTOR anywhere on the call stack** (the symbol's `f_back` chain) at the moment the
symbol executes — not merely if the symbol's *immediate* caller's code-object file is a LIVE_ROOT.
This supersedes the §1 framing that detonation can only ever cover the ~30% whose immediate caller
is a live-root file. (It does NOT remove the static-reachability floor or the adversarial
`wire_exempt` validation — those still stand; this only changes the *runtime* criterion's reach.)

### The rule change (precise)

- **OLD (immediate-caller):** `executed_from_live_root(name)` = True iff
  `self._callers[name]` (the FIRST observed `frame.f_back.f_code.co_filename`, captured at
  `wire_up.py:405-406`) `_path_matches` a LIVE_ROOT seed. Only ONE frame — the immediate caller — is
  ever consulted (`wire_up.py:448-466`, esp. `:460 caller = self._callers.get(name)`).
- **NEW (stack-ancestor):** True iff ANY frame in the target's `f_back` ANCESTRY chain (captured at
  `'call'` time) `_path_matches` a LIVE_ROOT seed, reusing the EXACT same `_path_matches` rule
  (`wire_up.py:473-505`). Immediate-caller becomes the depth-1 special case of the general rule.

### Effect

- **Detonation coverage rises from ~30% (immediate-caller) toward the genuinely-reachable majority.**
  The §1 measurement ("~25-30% have a live-root immediate caller; ~70% don't") was a property of the
  *immediate-caller* rule only. Under stack-ancestor, every symbol whose real production call chain
  *originates* in a LIVE_ROOT file — i.e. the statically-wired set the §1 floor accepts — can now be
  detonated to `True`, because driving its real chain puts a LIVE_ROOT frame in its ancestry. The
  Probe-3 "killer case" (`detect_and_heal_stalls`, reachable daemon→`reap_orphaned_workdirs`→here)
  flips from `False` to `True` (see PROOF below) — it is no longer a false-reject.
- **The `wire_exempt` set shrinks correspondingly.** The §3 `pure_helper` reason existed mostly to
  house "the Probe-3 class": statically-reachable symbols whose immediate caller isn't a live-root
  file (the ~70%). Under stack-ancestor those become genuinely **detonatable**, so the bulk of the
  `pure_helper` population moves into the DETONATED bar. `wire_exempt` narrows to its true residue:
  `staged_sibling` (call lands in a peer task), genuine `config_reader`/`flag_reader` inert accessors,
  and `data_only`. The anti-gaming hard rule (every non-`staged_sibling` exemption must still pass the
  static-reachability floor) is unchanged.

### Soundness is preserved (gaming still rejected) — empirically

The variant remains sound precisely because it requires a true **ancestor**, not mere presence in the
trace. Probe (Python 3.13.0, real `harness.wire_up.observe_symbol_execution` + real
`harness.state_reconciler`, watchdog armed via `JM_WATCHDOG_ENABLED=1`, LIVE_ROOT-named stand-in frame
`orchestrator.py` calling the REAL `reap_orphaned_workdirs`→`detect_and_heal_stalls` edge; tmp probe
deleted after run):

```
[A real-chain]            detect_and_heal_stalls: executed=True  immediate_caller_live_root=False  STACK_ANCESTOR_live_root=True
        immediate_caller_file = .../harness/state_reconciler.py
        ancestry_depth=3  live_root_ancestor_frames=['orchestrator.py']
[B direct-test]           detect_and_heal_stalls: executed=True  immediate_caller_live_root=False  STACK_ANCESTOR_live_root=False
        immediate_caller_file = <test file>            ancestry_depth=1  live_root_ancestor_frames=[]
[C presence-not-ancestor] detect_and_heal_stalls: executed=True  immediate_caller_live_root=False  STACK_ANCESTOR_live_root=False
        immediate_caller_file = <test file>            ancestry_depth=1  live_root_ancestor_frames=[]
[D orphan]                detect_and_heal_stalls: executed=True  immediate_caller_live_root=False  STACK_ANCESTOR_live_root=False
        immediate_caller_file = <test file>            ancestry_depth=2  live_root_ancestor_frames=[]
```

- **A** — the genuinely-wired killer subject: immediate-caller rule = **False** (caller lives in
  `state_reconciler.py`), stack-ancestor = **True** (an `orchestrator.py` LIVE_ROOT frame is an
  ancestor at depth 3). This is the coverage gain.
- **B** — a unit test calling the symbol directly: BOTH False. Only the test frame is in the ancestry.
- **C** — the subtle gaming attempt: a test invokes a live-root entrypoint for UNRELATED work (which
  returns and POPS off the stack), then SEPARATELY calls the orphan. The live-root frame is *present
  earlier in the trace* but is **NOT an ancestor** of the target's frame, so stack-ancestor = **False**.
  This is the case a naive "live-root seen anywhere in the trace" rule would wrongly pass.
- **D** — orphan (test→mid→target, no live-root frame anywhere): BOTH False.

**The exact ancestry check the implementation MUST use:** walk the TARGET FRAME's `frame.f_back`
chain (parent → grandparent → … to the top) captured AT THE `'call'` EVENT for that frame, and test
each ancestor's `f_code.co_filename` with `_path_matches`. It must NOT use a flat "was any
LIVE_ROOT frame ever seen during the observed window" set — Case C proves that flat-presence is
gameable (the live-root frame had already returned). Ancestry = the literal `f_back` lineage of the
specific frame that is executing the watched symbol.

### The B-observer extension needed (small, additive)

`observe_symbol_execution` ALREADY has the raw material: its trace callback fires on every `'call'`
event with the live `frame`, and it already reads `frame.f_back` (`wire_up.py:405`). The only thing it
does NOT yet do is walk PAST the immediate parent. The extension is mechanical:

1. **Capture (in the existing `_trace` `'call'` branch, ~5–7 lines):** when a watched top-level name
   fires for the first time, in addition to recording `self._callers[name] = back.f_code.co_filename`,
   walk `f = frame.f_back; while f: chain.append(f.f_code.co_filename); f = f.f_back` and store
   `self._ancestry[name] = chain`. Initialize `self._ancestry = {}` in `__init__` alongside
   `self._callers`. Guarded by the same `try/except: pass` so it can never crash a driven entrypoint.
2. **New query method (~8–10 lines):**
   `executed_with_live_root_ancestor(self, name, live_root_files) -> bool` — return False if
   `name` not watched/not executed; else iterate `self._ancestry.get(name, [])` and return True on the
   first frame filename that `_path_matches` any seed (reusing the existing static `_path_matches`).
   This is the stack-ancestor analogue of `executed_from_live_root` (`wire_up.py:448-466`); the latter
   is retained as the depth-1 view.

Total: **roughly 15 lines net**, no new dependency, no settrace change (settrace already supplies
frames with a full `f_back` lineage — empirically confirmed: ancestry_depth=3 captured for the real
chain). `reached` / `executed` / `reached_from` are untouched. Feasibility: **CONFIRMED** — the
observer needs an EXTENSION, not a redesign.

### Adjusted detonation-primitive brief (re-pointed)

The brief that builds/exercises the B-observer detonation primitive (roadmap §8 Brief 2,
`wire-up-runtime-observe-detonation-primitive`, and the gate-consumption wording in Brief 6) MUST now
target the **stack-ancestor** criterion, NOT immediate-caller:

- It implements `observe_symbol_execution.executed_with_live_root_ancestor` (+ the `_ancestry` capture
  above) and its RED oracle asserts the four-case truth table proven here:
  real-chain ⇒ True; direct-test ⇒ False; live-root-present-but-not-ancestor ⇒ False; orphan ⇒ False.
- The oracle's anti-gaming assertion is specifically Case C (the live-root entrypoint runs and returns
  BEFORE the orphan is called) ⇒ stack-ancestor MUST be False — this pins "ancestor, not mere
  presence."
- The gate-wiring brief (§8 Brief 6) consumes `executed_with_live_root_ancestor` (not
  `executed_from_live_root`) as the DETONATED criterion; `executed_from_live_root` stays as the
  depth-1 legacy view but is no longer the bar.
- Because the §1 ~30% ceiling no longer applies, the §3 `wire_exempt` `pure_helper` guidance (and the
  Brief 5 authoring prompt) should steer statically-wired-but-non-live-root-immediate-caller symbols
  toward **detonation via their real chain** first, and reserve `pure_helper` for symbols whose real
  chain genuinely never originates at a LIVE_ROOT.

All other roadmap structure (static floor as the mandatory FLOOR, adversarial `wire_exempt`
validation, default-OFF knob + shadow soak before enforce-flip) is UNCHANGED.
