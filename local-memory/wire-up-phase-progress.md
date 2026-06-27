---
name: wire-up-phase-progress
description: "Runtime-reachability wire-up phase (B/C/Phase3) — COMPLETE+VERIFIED; dormant enforce arm + the gates before flipping it ON"
metadata: 
  node_type: memory
  type: project
  originSessionId: abc9547b-8d8a-4bd6-b44d-ee0591b3fcfc
---

🎯★ MEASURED PORTABILITY + SOAK/ENFORCE AUDIT 2026-06-23 (4-agent scripted, owner-commissioned; SUPERSEDES the "declared roots ≈ ~2-3d narrow fix / converts NGv2 into a soak surface" framing below). Scripts in `_autowork_scratch/wireup_portability_audit_2026-06-23/{agent1..4}/`. Integrated into the two research docs as **contract P-WIREUP + exit criteria X13–X16** (NGv2-closure-deliverables-and-acceptance-contract.md §2/§3/§4/§7/§8) and **gap G13 + §8B** (NobleGreedv2-end2end-gap-analysis.md). KEY MEASURED CORRECTIONS:
- **"declared/target roots fixes the FP storm" is FALSE.** Floor over 600 NGv2 symbols: 100% would_be_orphan w/ hardcoded JM roots → only **62.5%** w/ discovered NGv2 roots (89.7% pkg-rooted). The dominant blockers are NOT a missing roots list: (1) **source-root/package-prefix keying + tree pollution** — `discover_modules` has NO `_SKIP_DIRS` for `tmp/`/`targets/`/research → 8151 modules, a single floor call >120s; `ngv2/`-rooting → 2 edges/184 (vacuous), `NobleGreedv2/`-rooting → 239 edges; (2) **~118/184 NGv2 modules are dynamically registered** (registry/importlib/entry_points), statically unreachable by design (floor docstring admits it). → **Tier-0 per-project source-root+exclude config is the REAL prerequisite, not roots.** NGv2 is a HIGH-FP surface, NOT a clean soak vehicle.
- **JM-self (the only clean-ish surface) post-B7-recheck FP = 33.3%** (1/3), naive intro 71.4% (5/7, mostly staged-build noise B7 rescues). The 1 surviving FP = `orchestrator.py::_promote_fallback_candidate`, genuinely wired via **module-alias-attribute** (`orch.sym(...)`) which the floor's cross-module rule (needs explicit `from … import`) misses → a static-analysis FN that never self-heals. ★ This is the dominant enforce-readiness lever (fix → ~0%). (The automated scorer's "0% post-B7" is itself a victim of the same blind spot — hand-verified truth = 33.3%; done≠green number.) All 4 known permanent orphans correctly flag TP.
- **NEW enforce-path defect the prior plan missed: `wire_exempt` RAW BYPASS.** `orchestrator.py:2323` computes `uncovered` from the raw `task['wire_exempt']` name set and **never calls `validate_exemption` in the enforce path** (validate_exemption runs only in the non-blocking shadow report, :2362, hardcoded 'pure_helper'). So under enforce ANY brief-named wire_exempt symbol is excused with zero floor check — the catch-all is live+unmitigated. MUST fix before any enforce flip.
- **README:200 "the wire-up gate reads entrypoints as extra live roots" is FALSE** — entrypoints are ⊆-`LIVE_ROOTS`-gated (`_contract_valid`, orchestrator.py:2317) and feed `detonate_oracle` only; never seeded into the floor BFS. Contract-injection plumbing exists (`_inject_integration_contracts`, plan_normalizer.py:1145) but 0 briefs ever declared one.
- **X1/P1.1 correction:** `p11-build-evidence-perphase-impl` IS NGv2 HEAD ed91619 (+2 lines) but GAMED its oracle (`_PHASE_COUNT_KEY` still 3-of-7; oracle seeds the 4 keys into state['evidence']). X1 unclosed.
- **Trust-core map:** `wire_up.py`/`state_reconciler.py`/`plan_normalizer.py`/`rebuild/discover.py` = NON-trust-core (auto-approvable); `orchestrator.py` = irreducible (decision file). So put resolve_roots+source-root logic in `wire_up.py`; orchestrator diff ≈4 lines (:2317/:2347/:2362/:1483).
- **Soak protocol:** flip `wire_up_runtime_gate: true` (REPORT-only, provably inert — enforce stays off; emit+commit+restart). JM-self ONLY. Metric = post-B7 static-floor FP w/ observation-path structurally excluded + staged-build re-scored at HEAD + permanent orphans=TP. **Enforce-enablement gate:** ≥60 qualifying JM-self accepts WITH B7 active, post-B7 FP<5%, perm-orphan TP recall 100%, 0 genuinely-wired hard-rejects in trailing 20; prereqs = B7 consumer + alias-attr FN fix + wire_exempt-via-validate_exemption (+ Tier-0+roots before NGv2). Flip = `wire_up_runtime_gate_enforce: true` (owner-gated), 1-line revert.

⚠️★ PORTABILITY FINDING 2026-06-23 (2-agent read-only audit, "make the gate portable / can NGv2 be the soak"): the static-reachability pivot (path-forward option 1 below) WAS subsequently built — `symbol_reachable_from_live_root` (wire_up.py:689) + stack-ancestor `executed_with_live_root_ancestor` (:475) + `detonate_oracle` (:572) + `validate_exemption` (:667) — see [[ngv2-wire-up-detonation-program]]. BUT it is **NOT portable**: the new floor seeds BFS from the **hardcoded JM `LIVE_ROOTS`** (wire_up.py:37) with **no `discover_live_roots` reconciliation and no rootless no-op** (unlike the OLD `check_wired`). CONSEQUENCES (code+empirically proven): (a) on ANY external project (NGv2) ~100% of symbols compute `would_be_orphan=True` — even NGv2's real `run_hunt` entrypoint — so **report-only on NGv2 = a useless FP storm; NGv2 is NOT a valid soak vehicle as-built**; meaningful soak data only comes from **JM-self/harness accepts** where LIVE_ROOTS are real. (b) The OLD `wire_up_gate: true` *self-disables* (`external_reconciled` no-op → wired=True) on external/rootless targets — that's why P1.3's NGv2 dead code (loopback_listener/auth_bootstrap/sink_instrument, 0 prod importers) LANDED unflagged. (c) **B7 staged-sibling recheck is DEFINED-BUT-UNCONSUMED** — `validate_exemption` returns `ExemptionVerdict(requires_recheck=True)` for category `staged_sibling` (wire_up.py:662-665,682-683) but ZERO consumers in orchestrator/state_reconciler; the live gate hardcodes category `'pure_helper'` (orchestrator.py:2362) → a "built in leaf N, wired in N+k" symbol is flagged at landing, no recheck. PORTABILITY EFFORT (to make "did I wire this up?" work in any project — the owner's original intent): Tier-1a′ per-project `wire_up.roots` config + route target-derived roots into the floor/contract/exemption (~2-3 build days, orchestrator.py=trust-core+decision-file; ALSO converts NGv2 into a real soak surface) → Tier-2 wire B7 consumer in state_reconciler (~1 brief, non-trust-core) → Tier-1b ecosystem-aware auto-discovery of roots (entry_points/__main__/pytest/library-public-API/framework-registries + app-vs-library project-type, ~3-5 briefs, FP-tuning-heavy). Runtime detonation BAR portability descopes onto NGv2 P2.1 env-FSM; cross-language onto P3.2. Owner offered the sequence; not yet greenlit.

✅ WIRE-UP PHASE BUILD COMPLETE 2026-06-23 (B → C → Phase3 all LANDED + VERIFIED observed-working) —
⚠️ BUT enforce CANNOT be enabled as-built (factory emits no contract; 89-100% false-positive). See the 🛑
EMPIRICAL BLOCKER below. The gate SCAFFOLD works; the SUPPRESSION CRITERION is the wrong fit for this factory.
It closed the gap that the wire-up gate fired ONLY for brand-new *module files* (`harness/wire_up.py::check_wired`
`continue`s on `_tracked_in_parent`), so a new zero-caller symbol added to an EXISTING module landed unflagged.
The phase added a runtime-reachability gate that observes whether a new symbol is actually executed from a
LIVE_ROOT entry point. `LIVE_ROOTS` (wire_up.py:37) = orchestrator.py, orchestrator_worker.py,
autowork_daemon.py, planner/cli.py. The three briefs were strictly sequential (all touch `_run_wire_up_gate`).

- **B `wire_up_runtime_observe_primitive`** — ✅ 21e306d oracle / 6fb413f primitive. Adds
  `observe_symbol_execution` (ctx-mgr: `.executed(name)`, `.reached_from(name)`, `.reached`,
  `executed_from_live_root(name, live_root_files)` = immediate-caller code-object in a LIVE_ROOT file) +
  `new_top_level_callables(parent_src, child_src)` AST-diff. Observed-working: /tmp probe 11/11 + faithful
  unmocked oracle 13/13.
- **C `wire_up_runtime_reachability_gate`** — ✅ cce32f5 oracle / 9a724b6 wiring. Wired the primitive into
  `_run_wire_up_gate` **REPORT-ONLY** (never reject — `continue`); per-symbol LIVE_ROOT-validated contract:
  suppress only when wire_exempt OR (`_contract_valid` AND symbol∈`symbols`), `_contract_valid = bool(entrypoints)
  and all(ep in LIVE_ROOTS) and bool(runtime_oracle)`. Observed-working: real-gate hermetic probe, 5 scenarios.
- **Phase3 `wire_up_runtime_gate_enforce`** — ✅ oracle / 6bdaa84 wiring / 08faa6a config. Adds the FAIL-CLOSED
  reject arm behind TWO default-OFF knobs (`wire_up_runtime_gate` gates the whole symbol check; the nested
  `wire_up_runtime_gate_enforce` gates only the divert-to-reject) under `autowork:` in config.yaml, both `false`.
  On enforce-ON + uncovered → existing reject machinery (`_rollback_rejected_commit` + `remove_staging_worktree`
  + `_mark_blocked` + `phase='rejected'` row + `return True`); enforce-OFF → byte-identical Phase-C report-only.
  Readers `_wire_up_runtime_gate_enabled` / `_wire_up_runtime_gate_enforce_enabled` (orchestrator.py:2169–2213)
  are fail-safe→False. OBSERVED-WORKING (NOT a green gate): faithful oracle (identity-asserts the REAL
  `_run_wire_up_gate`, derives expectations from the real AST diff, asserts rolled-back git ref / removed
  worktree / relocated task file — monkeypatch stubs ONLY the two boolean readers; no answer-key leak) +
  independent /tmp probe through the REAL readers + REAL gate reproduced BOTH arms (OFF=report/commit-survives;
  ON=rejected/rollback/blocked, child→parent sha). See [[done-means-observed-working-not-a-green-gate]].

Brief A (static per-file caller gate) SKIPPED per owner — superseded by C's per-symbol gate.

🛑 EMPIRICAL BLOCKER — ENFORCE CANNOT BE ENABLED AS-BUILT (proven 2026-06-23 by a read-only backtest over real
history; this SUPERSEDES the earlier "shadow soak + _contract_valid hardening" plan, which was based on a wrong
premise). Flipping `wire_up_runtime_gate_enforce` ON today would BRICK the factory. Root facts:
  - **No contract emitted:** 0 of 5226 on-disk `task.json` carry `integration_contract`/`runtime_oracle`/
    `entrypoints`/`wire_exempt`; the planner (plan_normalizer/blind_draft) NEVER writes them. Gate reads
    `task['constraints']['integration_contract']` from state/tasks/current_task.json. So `_contract_valid` is
    ALWAYS False → `uncovered = ALL new top-level callables` → enforce rejects EVERY new-symbol commit.
  - **Declaration-based FP = 89%** (50/56 genuinely-wired symbols in a 26-commit sample wrongly rejected; only
    6 genuine orphans correctly flagged).
  - **Observation hardening is WORSE (~100% FP)** — so my earlier `_contract_valid`-hardening recommendation is
    INVALID for this factory: leaf oracles are unit tests that call the symbol DIRECTLY (immediate caller = the
    test file, never a LIVE_ROOT) → `executed_from_live_root=False` → false-reject. Only 1 of 114
    tests/harness files drives a live root (the gate's own self-test). /tmp-probe-confirmed on
    `_restrict_sidecar_to_declared`.
  - **Staged-build pattern:** factory routinely lands a primitive in commit 1, wires it in commit 2 (e.g.
    `new_top_level_callables` 6fb413f→9a724b6) → enforce at commit 1 wrongly blocks the legitimately-uncalled symbol.
  - **4 PERMANENT real orphans = the gate's genuine value:** diff_fuzzer.py::`_one_sided_fuzz`,`_capture_golden`;
    agy_pool.py::`assert_pool_invariant`,`effective_pool_size` (zero callers in HEAD).
  ✅ SALVAGEABLE: the gate scaffold (`_run_wire_up_gate` report/enforce modes + knobs), the AST diff
  (`new_top_level_callables`), and the enforce rollback machinery all WORK — only the SUPPRESSION CRITERION is
  wrong. The backtest's own ground truth = **STATIC call-graph reachability from LIVE_ROOTS**, which scored 50/56.
  PATH FORWARD (asked owner 2026-06-23): (1) pivot criterion to STATIC reachability + staged-build tolerance
  [RECOMMENDED — low-FP, tractable, reuses scaffold]; (2) make planner emit `integration_contract` + factory
  author live-root-driving oracles [true dynamic detonation, big program, aligns with NGv2 live-env thesis];
  (3) keep report-only as an active shadow signal, don't enforce. The contract-runtime-hardening brief
  (brief_hooks_wire_up_contract_runtime_hardening.md, 3 OPEN BLOCKERS) is now MOOT under option (1)/(3).
  See [[implementation-is-not-wired-defect]], [[dont-conflate-built-with-works]],
  [[never-claim-capability-works-without-empirical-proof]].

🪲 LATENT DEFECT SURFACED 2026-06-23 (Phase3 config task false-blocked on it; recommended NEXT pipeline fix —
   NOT yet dispatched, owner to decide): a sibling task whose vcmd is a SHARED oracle that an impl sibling turns
   GREEN has no auto-induced dependency edge on that impl sibling. Phase3's config task (`...-config`) depended
   only on the oracle (#1), not the wiring (#2); it raced ahead, ran its (still-RED) vcmd, and blocked. Fixed
   this instance by clean re-dispatch once wiring was on HEAD (vcmd 13→13 green). Durable fix (planner-level,
   preferred): when ≥2 sibling tasks share one `verification_command` oracle and one is the impl that turns it
   green, validate_plan should auto-induce a dependency edge from the other sibling(s) onto that impl — generalizes
   the existing `required_task_ids`/ordering enforcement. See [[required-task-ids-enforcement]].

🐌 PLANNER-LATENCY REGRESSION (introduced 2026-06-21 by our own e6a3091) — ✅ FIXED 2026-06-23, EMPIRICALLY
   CONFIRMED. Root cause: the blocking tmux/PTY claude backend returns AFTER the draft is written, so
   `poll_start_wall` > draft mtime, so the outbox freshness gate discarded the FRESH VALID draft → `run_agent_phase`
   max_retries=3 re-spawn storm (blind_drafts ~1682s, clamped at the 1800s wall → SIGKILL before persist). Fix:
   `run_agent_phase` captures `spawn_start_epoch=time.time()` right before `spawn_agent` and threads it into
   `poll_for_submission` → freshness gate uses spawn-start not poll-start (oracle da191d5 + impl 6d90768, +6/−4 to
   orchestrator.py; backward-compat, headless unchanged). Landed via a one-time owner-cleared config scaffold
   (1800→4000 wall, then reverted) to break the catch-22. PROOF: Phase-3's own plan `blind_drafts` = **256s**
   (was ~1682s), 6.5× faster, run persisted clean. ★OPERATIONAL LESSON (orphan-planner race): before bouncing the
   daemon, check for an in-flight planner/worker child FIRST; if you SIGKILL anyway, reap the orphaned planner by
   PID (its `bwrap --die-with-parent` child cascades the jailed-agy teardown — never signal agy directly).
   See [[never-claim-capability-works-without-empirical-proof]], [[daemon-supervisor-respawn]].

🧹 Minor tidy (non-urgent): ~21 stale `.slot` sidecars accumulate in `state/control/autowork/running/` for
   completed tasks (no matching `.pid` → inert, `_agy_pool_busy_slots` ignores them) — the daemon isn't reaping
   spent slot sidecars. Mild state clutter, candidate for a reconciler reap_for_task parity fix later.
