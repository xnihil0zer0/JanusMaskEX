---
name: ngv2-wire-up-detonation-program
description: "ACTIVE program: rebuild the wire-up runtime gate as static-floor + stack-ancestor detonation + validated wire_exempt (owner-confirmed path); roadmap + workstreams + risks"
metadata:
  node_type: memory
  type: project
  originSessionId: abc9547b-8d8a-4bd6-b44d-ee0591b3fcfc
---

🚀 ACTIVE PROGRAM (owner-confirmed 2026-06-23): make the wire-up runtime-reachability gate actually
ENABLE-ABLE. Pure dynamic detonation (owner's first pick) was PROVEN toothless by backtest+feasibility
(see [[wire-up-phase-progress]] 🛑 blocker): the immediate-caller `executed_from_live_root` rule is
structurally satisfiable for only ~26-30% of harness symbols (~70% are called only from non-live-root
modules — a call-site fact, not an authoring gap; proof: `detect_and_heal_stalls` is daemon-wired but its
immediate caller is `reap_orphaned_workdirs` in state_reconciler.py → False). Pure detonation ⇒ ~70%
forced to wire_exempt ⇒ exempt becomes a catch-all ⇒ theater.

📍 PROGRESS: brief #1 (static-reachability FLOOR) LANDED + VERIFIED observed-working 2026-06-23 (commits
b27ede3 oracle / 2e8f2e9 primitive). Independent verifier: `symbol_reachable_from_live_root` (wire_up.py:537,
real import-graph BFS + class/method-body AST symbol-scan) classifies all 7 ground-truth subjects correctly
(3 reachable→True incl `_jailed_popen` via method-body descent; 4 orphans→False), oracle non-vacuous (12 passed,
module-level-shortcut trap present), right-reason traces confirmed. The FLOOR has teeth.
Brief #2 (stack-ancestor OBSERVER method `executed_with_live_root_ancestor`) LANDED + VERIFIED observed-working
2026-06-23 (commits 81e9c19 oracle / 3279cd3 primitive, +35/−0 additive). Per-name `self._ancestry.get(name,[])`
f_back lineage walk (NOT flat-set, NOT cross-name items()). All 5 oracle cases pass vs the real observer; the
adversarial review CAUGHT a cross-name `items()` leak (`xname_ancestry`) the original A/B/C/D missed → added Case E
(multi-name isolation). Mutation cross-check confirms teeth: flat-set mutant dies on Case C, cross-name mutant dies
ONLY on Case E. `executed_from_live_root` byte-unchanged (sibling oracle 13/13). ★The detonation observer primitives
are DONE. Brief #3 (JAILED DETONATION RUNNER `detonate_oracle`) LANDED + VERIFIED observed-working 2026-06-23
(commits 1665218 oracle / d8e4899 primitive). Feasibility GO'd first (nested bwrap WORKS in the gate-jail config).
Runs a leaf oracle_source under the observer in build_jail_argv(bind_credentials=False), PYTHONPATH=repo_root,
parses last-line stdout JSON, returns per-symbol executed_with_live_root_ancestor, all-False on crash/timeout
(SAFE direction). Operator-shell verify (real bwrap): live-root→True, direct→False; BOTH security teeth hold —
cred-drop (~/.gemini absent in-jail vs present on host) + net-isolation (if_nameindex=['lo'] in-jail vs 7 host
ifaces). Adversarial review CAUGHT a --unshare-net off-host-exfil hole (cred-dropped-but-networked cheat passed the
cred-only oracle) → added Case 3b net-isolation via socket.if_nameindex (a PURE SYSCALL — /sys/class/net is NOT
mounted in the jail, so a /sys-based check would be toothless), effect-observed, verified non-flaky. R-anchored on
symbol_reachable_from_live_root. Oracle 12 passed/0 skipped (security cases RAN). ★DETONATION MACHINERY COMPLETE
(FLOOR #1 + OBSERVER #2 + RUNNER #3, all verified observed-working). Brief #4 (ADVERSARIAL EXEMPT-VALIDATION — the
program's BIGGEST RISK, keep wire_exempt from becoming a catch-all) LANDED + VERIFIED observed-working 2026-06-23
(commits 57a12a7 oracle / 5ab79d8 primitive; ~18min e2e, planning 685s = the dominant cost). validate_exemption(
category,symbol,module_rel,repo_root,*,roots) -> ExemptionVerdict(honored,requires_recheck,reason) is a clean 3-branch
delegation: staged_sibling→(False,True) ALWAYS defers (never consults floor); {pure_helper,config_reader,data_only}→
honored=bool(symbol_reachable_from_live_root); unknown→(False,False,'rejected'). INDEPENDENT adversary drove the REAL
landed fn (NOT the committed oracle): all 4 known orphans floor=False→honored=False under pure_helper; reachable→
honored=True; ★Case-7 composition DECISIVE — monkeypatching the module-level floor FLIPS the verdict (stub False→
honored False even on a reachable symbol; stub True→honored True even on an orphan) ⇒ it genuinely CALLS the floor,
NOT fixture-hardcoded against the _inject_oracle_sources answer-key leak; garbage rejected; roots=[] starves the floor
(threaded, not ignored). The catch-all hole is CLOSED. Brief #5 (CONTRACT EMISSION) LANDED + VERIFIED
observed-working 2026-06-23 — brief-declared integration_contract flows brief-frontmatter → load_brief →
planner cli main → normalize_plan → task.json constraints (a NEW surface in planner/plan_normalizer + brief_loader +
cli, NOT wire_up.py). Composition: plan-#5 (briefloader field+frontmatter-parse 8247a1c/9d10d42 + normalizer
injection f66762c/1c46738) + a CORRECTIVE RED-PAIR (oracle a420db6 + cli-impl 807c2ec). ★The cli-oracle had a
{}-vs-None sentinel bug (briefloader defaults integration_contracts to {} not None) → reshaped to a red-pair; my
brief spec said thread `getattr(brief_obj,'integration_contracts',None)` (yields {} for no-contract → fails the
no-contract test asserting `in (None,'__UNSET__')`), but the impl LLM SELF-CORRECTED on attempt-2 retry to
`getattr(...) or None` ({}→None) → oracle 6/6 green. E2E OBSERVED-WORKING (real load_brief + real normalize_plan,
no stubs): contract injected at `task['constraints']['integration_contract']` (plan_normalizer.py:1158-1164,
deepcopy) BYTE-MATCHING the gate's read (orchestrator.py:2297-2309 entrypoints/symbols/runtime_oracle); contracts=None
injects nothing (guard plan_normalizer.py:1147). ⚠️HONEST CAVEAT: this is the EMISSION PLUMBING only — the factory
does NOT yet AUTHOR integration_contracts in real briefs (0/5226 tasks), and the gate further requires
entrypoints⊆LIVE_ROOTS for _contract_valid. Making contracts get authored+used = brief #6 (detonation oracle-authoring
prompt) + #7 (gate wiring). Brief #6 (DETONATION ORACLE-AUTHORING PROMPT) LANDED + VERIFIED
observed-working 2026-06-23 — oracle 740a755 + impl 91ee6f9 (1-file orchestrator.py red-pair;
TRUST-CORE impl decision-file authorized). prepare_task_prompt (orchestrator.py:1475-1484) now
appends a contract-gated LIVE-ROOT detonation clause ONLY for test_authoring tasks whose
integration_contract passes a REAL validity predicate: entrypoints non-empty ∧ all(e∈LIVE_ROOTS)
∧ symbols non-empty ∧ runtime_oracle non-empty str. INDEPENDENT verify drove the REAL committed
fn (oracle NOT imported): 10/10 cases — clause PRESENT for valid+test_authoring, ABSENT for all 5
invalid-contract variants (bad-entrypoint/empty-symbols/empty-RO/empty-entrypoints/mixed),
no-contract, and non-test_authoring (harness_self_fix+implementation). B5 mixed proves a true
SUBSET check (presence-only cheat would emit → killed). decode_check ok:false on both commits =
benign (default-off post-hoc telemetry json.loads'ing a source-patch emission). ★Robustness note:
the oracle worker HUNG once (transient Claude PTY stall, 30min) → watchdog_kill → blocked/ →
auto-retry attempt-2 clean. Surfaced the [[daemon-idle-sleep-outlasts-retry-backoff]] latency gap
(idle 1800s > retry backoff 300s; woke via allowlist touch). NEXT: brief #7 = gate-variant wiring
(REPORT mode) — wire validate_exemption + the static-floor/detonation primitives into the live
_run_wire_up_gate (roadmap §8 Brief 6; TRUST-CORE orchestrator.py). Gate stays REPORT-only; enforce
flip owner-gated after low-FP soak.

✅ BRIEF #7 COMPLETE + VERIFIED observed-working 2026-06-23 (Option B; oracle 984cec7 + impl 96559fa). The
landed _run_wire_up_gate (orchestrator.py:2340+) emits an ADDITIVE report-only `wireup_symbol_verdict` row per new
top-level symbol — floor_reachable / contract_detonated / exempt_honored / would_be_orphan, composed from the 3
wire_up primitives, gated on _wire_up_runtime_gate_enabled, wrapped inert (never raises). INDEPENDENT adversary
drove the REAL committed fn at HEAD over hermetic trees (NOT the oracle): event FIRES (contract locals _entrypoints
:2308/_csymbols:2311/_oracle:2314/_contract_valid:2317 in scope — no NameError); orphan-case all-false+would_be_orphan
=true; reachable-case floor=true+orphan=false; ADDITIVITY proven (insert-only 32/0 diff; orphan_symbol_unwired STILL
fires; return False unchanged; no rollback; gate-OFF = strict no-op, zero rows); never raises under forced-primitive
failure. Config knobs still false (report-only, untouched). Build hit NO idle-sleep stall (oracle→impl dispatched
instantly). Slug removed; brief+plan+decision hand-archived → _autowork_scratch/2026-06-23_wireup_gate_report_annotate_spent/
(auto-archive STILL did not fire — 3rd recurrence #5/#6/#7). ★NEXT (owner ordering directive: #7 built clean → finish #7
then BOTH hygiene fixes, see [[daemon-idle-sleep-outlasts-retry-backoff]]): (1) idle-sleep>backoff cap, (2) spent-brief
auto-archive miss (reap_spent_briefs gating) — both as pipeline briefs. THEN resume roadmap: staged-sibling
plan-completion recheck → soak → enforce flip (owner-gated, low-FP validated). Gate stays REPORT-only throughout.

(history) Brief #7 scoping detail: Scoped FEASIBLE (1-file orchestrator.py impl on _run_wire_up_gate:2241;
all 4 primitives exist; detonate_oracle self-jails). First attempt = "Option A" (REPLACE the suppress
predicate with the FLOOR→contract-detonation→validate_exemption disjunction + migrate the 3 wire-exempt
tests it breaks). A failed to PLAN twice (4-task multi-file red-pair too complex for the dual-blind planner:
missing_integration_test, then "Merged plan failed validation"). PIVOTED to "Option B" (the independent
review's recommendation, robust): clean 2-task red-pair — KEEP the existing verbatim-wire_exempt suppress
predicate + orphan_symbol_unwired row UNCHANGED (no existing test breaks), ADD a NEW per-symbol REPORT verdict
event (floor_reachable / contract_detonated / exempt_honored / would_be_orphan) computed from the 3 primitives.
Gathers the SAME soak FP data; the actual suppress-swap is deferred to the owner-gated enforce-flip brief.
Brief A retired → _autowork_scratch/2026-06-23_wireup_gate_variant_OPTION_A_retired/. ★GOTCHA (cost 2 plan
failures): the `missing_integration_test` excuse is checked PER-TASK against `spec.non_goals` (plan_validator.py:
250-256, `any('integration' in ng.lower())`), NOT the brief's `# Non-Goals` section — multi-task briefs MUST
explicitly instruct EVERY task's spec.non_goals to carry an `integration`-bearing entry. ★Detonation gets no
behavioral unit coverage in either option (hermetic detonate_oracle fail-closes to False; accepted Non-Goal;
its first real test is the enforce-flip soak). ★The "full adversarial suite red-gate" lore is STALE — current
harness gates a harness_self_fix only on its own per-task vcmd (auto-scoped to changed test files), not the
whole suite (orchestrator.py:2940-2999/3045). Gate stays REPORT-only.

CONFIRMED DESIGN — "GO-WITH-VARIANT + STACK-ANCESTOR":
- **FLOOR (necessary condition):** symbol-level STATIC call-graph reachability from LIVE_ROOTS (orchestrator.py,
  orchestrator_worker.py, autowork_daemon.py, planner/cli.py). Cheap, sound, 100% coverage; not statically
  reachable ⇒ definite orphan ⇒ reject. Backstop + cheap pre-filter (caught the 4 real permanent orphans:
  diff_fuzzer `_one_sided_fuzz`/`_capture_golden`, agy_pool `assert_pool_invariant`/`effective_pool_size`).
- **BAR (proof of life, STACK-ANCESTOR rule):** for a symbol claiming a live path, require DETONATION — run the
  leaf's runtime_oracle (JAILED via agent_jail.build_jail_argv(bind_credentials=False)) under B's
  `observe_symbol_execution` and require a LIVE_ROOT frame to be an ANCESTOR on the call stack when the symbol
  runs (NOT just the immediate caller). Sound: a unit test calling the symbol directly has no live-root ancestor →
  rejected; an orphan can't get one → rejected. But it makes detonation cover MOST genuinely-reachable symbols
  (vs ~30% for immediate-caller). ✅ VALIDATED feasible 2026-06-23: a ~15-line ADDITIVE extension to B's settrace
  observer (the `'call'` branch already reads `frame.f_back` at wire_up.py:405-406; add an ancestry-walk + method
  `executed_with_live_root_ancestor` matching each ancestor via the existing `_path_matches`). Real-chain probe:
  `detect_and_heal_stalls` → stack-ancestor=True (depth-3 orchestrator.py ancestor) while immediate-caller=False.
  ★ANTI-GAMING (brief #2's oracle MUST pin Case C): check the TARGET FRAME's literal `f_back` lineage, NOT a flat
  "any live-root frame seen during the run" set — the flat form is GAMEABLE (a live-root entrypoint that runs+returns,
  then a separate orphan call, would falsely pass; rejected ONLY under true f_back ancestry).
- **wire_exempt (narrowed + ADVERSARIALLY VALIDATED against the static floor):** taxonomy
  `staged_sibling`/`pure_helper`/`config_reader`/`data_only`; every non-`staged_sibling` exemption MUST pass the
  static floor — exempt can only ever downgrade "must detonate" → "static suffices", NEVER suppress a true orphan.

CONFIRMED DEFAULTS (owner-accepted): contract is BRIEF-DECLARED → planner-threaded → task.json (never inferred);
methods (`co_qualname`≠`co_name`) = a KNOWN coverage gap, not closed now; heavy subprocess-spawning paths
(`_jailed_popen`, fuzz path) route to `pure_helper` exempt (can't detonate anyway + slow/flaky).

ROADMAP (9 briefs, riskiest front-loaded): `_autowork_scratch/wire_up_detonation_feasibility/ROADMAP.md`
(514 lines; authored for immediate-caller — being re-pointed to stack-ancestor). Order ≈ static-floor primitive →
stack-ancestor jailed-detonation primitive+PoC → adversarial exempt-validation → contract emission (brief→planner→
task.json) → detonation oracle-authoring prompt → gate variant wiring (REPORT mode) → staged-sibling plan-completion
recheck → soak → enforce flip (owner-gated, only after low-FP validated). The pre-Option-2 hardening brief
`brief_hooks_wire_up_contract_runtime_hardening.md` (3 OPEN BLOCKERS) is MOOT/superseded by this program.

★BIGGEST RISK (front-loaded): wire_exempt degenerates into a self-declared catch-all → orphans slip through →
the exact "system Goodharts a cheap proxy for works" failure ([[done-means-observed-working-not-a-green-gate]]).
Mitigation baked into the order: static FLOOR ships first (teeth even if detonation never works); exempt is
adversarially validated against the floor BEFORE the gate is wired. Gate stays REPORT-only through a soak; enforce
flip is owner-gated and only after the false-positive rate is empirically validated low. Same author→adversarial-
review→build→VERIFY-observed-working loop as B/C/Phase3. See [[implementation-is-not-wired-defect]],
[[dont-conflate-built-with-works]], [[delegate-everything-preserve-oversight-context]].
