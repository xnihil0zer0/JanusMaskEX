# Intervention Analysis — Lane 4: Automation Surface & NGv2 Compatibility

**Scope:** the JanusMask pipeline source (`harness/`, `harness/planner/`, `config/`)
and the NobleGreedv2 runtime compatibility boundary. Lanes 1–3 count interventions
in transcripts/git/archives; this lane reads the pipeline code so the final report
can recommend concrete, *safe* automation: where a handler could be injected, what
already exists, and what NGv2 contract a change must not break.

Companion artifacts in `scripts/intervention_analysis/`:
- `lane4_seam_map.py` — greps the seams, emits `seam -> [file:line]` JSON.
- `lane4_seam_map.json` — generated map (regenerate via
  `PYTHONPATH=. python scripts/intervention_analysis/lane4_seam_map.py --out ...`).

---

## 1. Daemon automatic control loop

`harness/autowork_daemon.py` is the autonomous engine. `run_daemon()`
(lines 2277–2395) loops calling `_iteration()` (1890–2050) until shutdown.

```
run_daemon()                                        2277-2395
  ├─ break if _full_stop_path() exists              2355  (state/control/autowork/full_stop)
  ├─ pause/resume telemetry                          2358-2363 (state/control/autowork/pause)
  └─ loop:
     _iteration()                                    1890-2050
       ├─ _reap_running()                            1891   (collect live worker pids)
       ├─ _auto_promote()                            1933 -> 1343-1635
       │    ├─ disabled? full_stop?  -> {}           1357
       │    ├─ _harvest_selfheal_briefs()            1397   (re-integrate self-heal briefs)
       │    ├─ _retry_blocked_tasks(max_attempts=3)  1376 -> 883-971
       │    ├─ stage_task() for each unstaged task   1509   (planner.staging.stage_task)
       │    └─ pick ONE unplanned brief (newest mtime) -> _run_planner_subprocess()  1559 -> 1270
       ├─ _decide()                                  1938 -> 1764-1798
       │    ├─ compute_brief_status() candidates     1766
       │    ├─ collect_dispatchable_tasks()          1769   (skip retry/current; dep-gate)
       │    ├─ prioritize()                          1771
       │    ├─ PAUSE/full_stop check                 1773   (existence => return [])
       │    └─ can_run_parallel() admit non-conflicting 1782/1787
       ├─ spawn workers                              1991 (seq Claude) / 2043 (parallel)
       │    -> _spawn_worker(): python -m harness.orchestrator_worker  1092-1111
       ├─ _check_inactivity_watchdog()               2383 -> 2846-2931
       └─ sleep heartbeat(idle) | poll(active)       2386/2388
```

Worker integrate / accept happens **inside `orchestrator_worker` / `orchestrator`**,
not the daemon: `_auto_commit_accepted` (orchestrator.py:2286), the wire-up gate
(`_run_wire_up_gate` orchestrator.py:1913), and spent-brief archival
(`_reap_spent_briefs_safe` orchestrator_worker.py:45, gated by
`autowork.archive_spent_briefs`).

**Key correction to a common assumption:** the daemon *dispatch* loop pauses on the
**existence** of `state/control/autowork/pause` or `.../full_stop`
(`_decide` daemon.py:1773). The *legacy* `control_gate.check_pause()`
(control_gate.py:48–66) instead reads `state/control/orchestrator.flag` and only
pauses when its content is literally `"paused"`. These are two different pause
channels — automation must target the daemon's pause-file existence check.

---

## 2. Intervention point → existing code seam table

| Intervention point | Existing code seam | file:line | Automatable? | NGv2 boundary? |
|---|---|---|---|---|
| Dispatch PAUSE | `_decide` checks `_pause_flag_path` existence | autowork_daemon.py:1773 (path 289) | Y | N |
| Emergency FULL-STOP | `_full_stop_path` existence | autowork_daemon.py:2355,1357,1773 (path 299) | Y | N |
| Legacy phase pause | `check_pause` reads `orchestrator.flag=="paused"` | control_gate.py:48-66 | Y | N |
| Brief allowlist gate | `_auto_promote_allowlist` / `_auto_promote_brief_eligible` | autowork_daemon.py:2548-2570, 2663; brief_status.py:116,143 | Y (already file-driven) | N |
| Master promote disable | `_auto_promote_disabled` | autowork_daemon.py:2542 | Y | N |
| Approval decision file | `await_decision` / `_apply_approval_granted` reads `state/control/decisions/<id>.json` | control_gate.py:85-117; orchestrator.py:2139-2156 | Y (poll-driven) | N |
| Auto-approve sensitive harness | `_auto_approve_sensitive_eligible` (ceiling counter) | orchestrator.py:2040-2138 | **Already half-automated** | N |
| Phase requires approval | `require_approval_for` reads `config.control.require_approval` | control_gate.py:68-70 | Y (config list) | N |
| Plan auto-correction (PRIMARY) | `normalize_plan` pass pipeline | plan_normalizer.py:1013-1047 | **Already the injection seam** | N (but emits NGv2-bound code) |
| Plan rejection (human fixes) | `validate_plan` -> `PlanViolation` | plan_validator.py:161-340 | Y (add normalize pass to pre-empt) | N |
| Stage a task | `stage_task` | planner/staging.py:47-146 | Y | N |
| Spawn worker | `_spawn_worker` -> orchestrator_worker | autowork_daemon.py:1092-1111 | Y | N |
| Retry blocked task | `_retry_blocked_tasks(max_attempts=3)` | autowork_daemon.py:883-971 | **Already half-automated** (budget=3, 1 for deterministic outcomes) | N |
| Self-heal harvest | `_harvest_selfheal_briefs` / `_synthesize_selfheal_plan` | selfheal.py:225-414 / 50-131 | Y (rule plug-in) | N |
| Self-heal auto-promote eligibility | `_selfheal_auto_promote_enabled` (`selfheal_auto_promote`) | selfheal.py:25-39 | **Already half-automated** (flag OFF) | N |
| Wire-up / orphan gate | `_run_wire_up_gate` / `check_wired` | orchestrator.py:1913-1954; wire_up.py:317-380 | Y | **Partial** (rootless no-op for external = NGv2) |
| Accept-commit | `_auto_commit_accepted` | orchestrator.py:2286 | Y | N |
| Archive spent brief | `_reap_spent_briefs_safe` (`archive_spent_briefs`) | orchestrator_worker.py:45-143 | **Already half-automated** (flag OFF) | N |
| Pre-tool interceptors | `InterceptorRegistry.pre_tool_use` (first non-None wins) | interceptors.py:118-156 (dispatch 352-356, 943-957 in orchestrator) | Y (`registry.register`) | N |
| Pre-tool hook (worker jail) | `claude/pre_tool.py` deciders | harness/hooks/claude/pre_tool.py; shim hook_pre_tool.py:32-49 | Y | N |
| Sidecar / stale-blocked cleanup | `stage_task` evicts blocked/retry/exhausted | planner/staging.py:86-92 | **Already automated** | N |
| Inactivity watchdog -> self-heal | `_check_inactivity_watchdog` | autowork_daemon.py:2846-2931 | **Already automated** (>20min stall) | N |
| Dispatch-spin circuit breaker | `_dispatch_timestamps` (10/300s -> quarantine) | autowork_daemon.py:1964-1983 | **Already automated** | N |

---

## 3. Injection seams available for new auto-intervention handlers (no new architecture)

These are the four canonical, *reusable* (per owner directive) plug-in points. A
new auto-handler should attach to one of them rather than special-case the daemon.

1. **Planner normalize-pass pipeline — `normalize_plan` (plan_normalizer.py:1013-1047).**
   The 13 existing passes are pure, deep-copy, idempotent functions invoked in
   sequence at lines 1032–1046. A new auto-correction = a new `_pass(plan, repo_root)`
   function appended to that sequence. This is the prime seam for any
   "planner keeps doing X, auto-fix it" intervention (e.g. the stray-mutation-target
   and multifile-split fixes already live here). Called from cli.py:357 before
   `validate_plan` (cli.py:360). **Gotcha:** a new pass can break sibling passes'
   tests — run the *whole* planner suite.

2. **Self-heal harvest/eligibility rules — selfheal.py.**
   `_harvest_selfheal_briefs` (225-414) scans agent outboxes and
   `_synthesize_selfheal_plan` (50-131) turns a diagnosis into a corrective plan.
   Eligibility is gated by `_selfheal_auto_promote_enabled` (25-39, flag
   `autowork.selfheal_auto_promote`, currently OFF) plus HMAC provenance
   (`_selfheal_provenance_valid` 188-224). A new "auto-recover from failure class Y"
   rule plugs into the synthesis logic; turning the flag ON closes the loop.

3. **Control-gate FSM + decision-file channel — control_gate.py.**
   Phases `('synthesis','fuzzing','cross_examination','ast_validation','accepted',
   'rejected','decomposition')`. `require_approval_for` (68-70, config-driven list)
   selects which phases block; `await_decision` (85-117) polls
   `state/control/decisions/<id>.json`. An auto-approver can *write* those decision
   files; the same channel is consumed by orchestrator's `_apply_approval_granted`
   (orchestrator.py:2139). `_auto_approve_sensitive_eligible` (orchestrator.py:2040)
   already auto-grants sensitive-harness commits under a persisted ceiling counter —
   the template for any new auto-approval policy.

4. **Interceptor registry / pre-tool hooks — interceptors.py:118-156.**
   `registry.register(MyInterceptor())` (interceptors.py:159-160) adds a runtime
   pre/post-tool handler; first non-None `{"decision": ...}` wins. Dispatched at
   orchestrator.py:352-356 (pre_invocation) and 943-957 (submit_code). The jailed
   worker side has a parallel surface in `harness/hooks/claude/pre_tool.py`
   (tool allowlist line 58, read-path gate 119-126, rate limits in
   `_state_gates.py` MAX_SUBMISSIONS=5 / MAX_CLARIFICATIONS=2).

Secondary seams: `stage_task` (re-stage policy), `_retry_blocked_tasks` (budget
policy), the wire-up accept-gate (`_run_wire_up_gate`), and the allowlist file
itself (an auto-handler can append eligible slugs — though MEMORY warns the
self-heal agent must NOT edit it; promotion is an operator decision today).

---

## 4. NGv2 "do-not-break" contract list

**The single most important compatibility fact:** the JanusMask harness has **zero
runtime import of `ngv2.*`**. A repo-wide grep of `harness/**` for `ngv2.`,
`NobleGreedv2`, or NGv2 imports yields only one *comment* (sandbox.py:140) and
env-var plumbing (`JANUSMASK_WORKING_DIR`). NGv2 is an **external build target**:
JanusMask *builds* NGv2 source via the pipeline (planner → stage → worker →
integrate, with `working_dir = /home/xnihil0zer0/NobleGreedv2`), and NGv2 *runs
independently* via its own `python -m ngv2.*` entrypoints. The only hard-coded link
is `_ISOLATED_EXTERNAL_DIRS = {'/home/xnihil0zer0/NobleGreedv2'}`
(autowork_parallelism.py:65), which forces external-root tasks to serialize.

**Consequence for automation:** any handler that is *JM-internal* (normalize passes,
selfheal, control-gate, interceptors, accept-gate, allowlist) **cannot break NGv2 at
runtime** — there is no live call edge. The only NGv2 risk is the pipeline *emitting
code that violates NGv2's own internal contracts*. Those contracts are:

| Contract | Defined in | Must preserve |
|---|---|---|
| Phase worker entry | `ngv2/workers/<phase>.py::run_stage(context, seams) -> list[dict]` | signature + `context`/`seams` dict keys (all 7 phases: hunt, triage, verify, poc, detonate, novelty, report) |
| Worker runner | `ngv2/workers/_runner.py::main/parse_args/build_context/build_seams/run_phase` + `__all__` | argv flags `--session-id --repo --target --out`; seam keys (`llm_client`, `may_confirm`, `writer`, `repair`, `detonation`, `novelty_gate`, ...) |
| Phase→command map | `ngv2/stage_command_map.py::command_for_phase` | argv shape `python -m ngv2.workers.<phase> --session-id .. --repo .. --target .. --out ..`; env `NGV2_SESSION_ID`, `NGV2_SESSION_DB`; purity (no IO/mutation) |
| Live entrypoint | `ngv2/run_hunt.py::run_hunt/main/parse_args` | `python -m ngv2.run_hunt --session-id --repo --target --db --out`; seeds at `hunt`; terminal park (never auto-submit) |
| Conductor seams | `ngv2/conductor_seams.py::build_default_seams` | seam dict keys (`ctx, load_state, plan, command_for_phase, spawn, harvest, persist, build_evidence, run_gates, advance, run_conductor_step`); cross-process payload threading (`prior_findings`, `parked_package.poc`, `evidence.detonation_report_raw`) |
| Session store | `ngv2/session_db.py::SessionDB.get_session/save_session`; `ngv2/session_api.py::SessionApi.advance(session_id, approval_decision=None)` | method names + signatures; `NGV2_SESSION_DB` resolution in `_runner._load_session_row` |
| L0 artifacts | `ngv2/contracts.py` (`Finding`, `PoC`, `LiveTestReport`, `Bounty`, `Target`; `SEVERITIES`, `VERDICTS`) | field names + `to_dict`/`from_dict`/`validate` round-trip |
| PoC synthesis | `ngv2/poc_writer.py::write_poc`; `poc_repair_loop.repair_poc` | callable contract used as the `poc` phase `writer`/`repair` seam |

**Pipeline-side guards that already protect this boundary (keep them):**
- `plan_normalizer._force_smoke_gated_leaf_impl` / `_canonicalize_oracle_paths`
  (plan_normalizer.py:347, 546) handle external `ngv2.*` builds the diff-fuzzer
  cannot import — these are NGv2-aware passes; a new normalize pass must not
  regress them.
- The wire-up gate's **rootless no-op** (`check_wired` wire_up.py:378-379) returns
  `wired=True` for external targets with no live root — i.e. it *deliberately does
  not* flag NGv2 modules as orphans. An automation change to the wire-up gate is the
  one accept-gate seam that crosses the NGv2 boundary and must keep this behavior.

**Bottom line:** automate freely on the JM-internal seams (§3.1–3.4); for anything
touching emitted NGv2 code or the wire-up gate, validate against the contract table
above (run NGv2's own `python -m ngv2.workers.<phase>` smoke + the workers' oracle
suite) before landing.
