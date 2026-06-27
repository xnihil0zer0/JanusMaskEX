# P2.1 `env_readiness_fsm` EPIC — Decomposition Design (READ-ONLY recon, 2026-06-24)

**Author:** orchestrator recon pass. **Status:** design file, NOT briefs. Do not author final briefs from this
without the §5 open-question decisions.
**Sources:**
- `/home/xnihil0zer0/AI-Data/Research-JanusMask/NobleGreedv2-end2end-gap-analysis.md` (gap analysis; §3 FSM, §7 roadmap)
- `/home/xnihil0zer0/AI-Data/Research-JanusMask/NGv2-closure-deliverables-and-acceptance-contract.md` (acceptance contract; P2.1 block lines 311-353, X-criteria 107-124)
- NGv2 engine `/home/xnihil0zer0/NobleGreedv2/ngv2/` (file:line cited throughout).

---

## 1. The exact P2.1 deliverable text + acceptance criteria + FSM design

### 1.1 Quoted deliverable (contract lines 311-353)

> **#### P2.1 — `env_readiness_fsm` — EPIC ☐**
> **Gap:** G1 · **working_dir:** NGv2 · **meta_task_type:** `state_machine` (epic)
> **Intent:** Build the front half of the deterministic, fail-closed env-readiness FSM:
> `DETECT → PROVISION → JAIL-BUILD → HEALTH-PROBE → REACHABILITY-PROBE → BASELINE-CAPTURE`. Every transition
> is a pure gate over the previous state's content-hashed JSON evidence; absent evidence ≠ pass.
> **[Effort flag]** Only **JAIL-BUILD** is a clean reuse; **3 of 9 states are net-new** (PROVISION,
> HEALTH-PROBE service-start, parts of REACHABILITY). Budget as a build, not a wiring job.

Child contracts (verbatim, contract 320-346):
- **P2.1-c1 `fsm_detect`** — classify language(s)/build system, resolve ABI-correct interpreter
  (`.python-version`/`pyproject`), check eligibility at entry. *Testable:* language ∈ {py,js}; build file present;
  `python_bin`/`node_bin` resolved; SHA matches pin; a missing build file → typed `no_build_system`. *Reuse:* extends an existing gate (net-new glue).
- **P2.1-c2 `fsm_provision`** **[NET-NEW — long pole #2]** — build `.venv`/`node_modules` from the target's **own
  lockfile only**, network-restricted (the *opposite* of today's host-side full-network stderr-driven install — rebuild,
  not reuse). Deterministic cascade (Dockerfile→devcontainer→buildpacks/repo2docker→manifest) → agentic ReAct-bash
  fallback; time-machine pip/npm proxy. *Testable:* venv built with ABI-correct interpreter (≡ JanusMask `G3_VENV`);
  deps from lockfile not stderr; **gated on a real import/smoke probe, never on build success** (EnvBench BUILT≠runnable
  lesson); a target that "builds but won't import" → typed `provision_unrunnable`. *Depends on P0.2.*
- **P2.1-c3 `fsm_jail_build`** **[CLEAN REUSE]** — construct detonation jail argv (target ro-bind, one tmpfs scratch,
  net/ipc/pid unshared); **preflight `bwrap_available()` loudly here**. *Testable:* jail constructible; bwrap present →
  else typed `jail_unavailable` (not a silent detonate-time crash).
- **P2.1-c4 `fsm_health_probe`** **[NET-NEW — LONG POLE #1; no service-startup code exists in `ngv2/`]** — import the
  target cleanly inside the jail; for a service target, start it and confirm it **binds loopback** within a timeout;
  check a health route/banner. *Testable:* `import_ok`; service bound on `127.0.0.1` within timeout → else typed
  `service_no_bind` (and a lightweight-VM escalation hook for outbound-net startup). *Negative:* a target that never
  binds → typed terminal, never auto-advance.
- **P2.1-c5 `fsm_reachability_probe`** **[PARTLY NET-NEW]** — prove the sink is live code (not comment/patched), takes
  an externally-influenced arg, and a **benign sentinel** drives the real entry point into the sink region
  (`sink_instrument` is currently dead code). *Testable:* `sink_presence ∧ sink_reachability ∧ benign-ping-reached-sink`;
  a patched/commented sink → typed `sink_not_reachable`.
- **P2.1-c6 `fsm_baseline_capture`** — snapshot FS + capture stdout of a **benign control input**; require the success
  marker/signature **absent** in the control. *Testable:* `control_marker_absent ∧ control_fs_signature_absent` (else
  the oracle is vacuous → refuse).

> **EPIC-level testable conditions:** a **safe fixture target** is refused at the earliest failing state with a typed
> terminal; a **vuln fixture** passes all six states to BASELINE-CAPTURE; each transition is pure (stdlib, no
> clock/net/random) and survives RED-before/GREEN-after replay.
> **Wire-up:** the FSM front half is reachable from `run_hunt` (replaces the implicit "skip to hunt").
> **Dependencies:** P0.1, P0.2, P1.1.
> **Operator gate:** NGv2 external; `required_child_slugs` lists c1–c6 so the planner can't drop one.

### 1.2 Mapped acceptance (X-)criteria (contract lines 107-124, traceability 136)

P2.1's traceability row (contract:136): **G1 → P2.1 (EPIC), P2.2 → env-readiness FSM front half → X1, X2.**
The directly-load-bearing program-exit criteria for THIS epic:

- **X1** (line 109): a **vuln fixture** is `verdict=confirmed` **end-to-end through `run_hunt`** (the autonomous
  conductor), not a hand-driven `drive_*.py`. *Closes G1,G5.* — the epic-level positive: a vuln fixture must traverse
  all six new states (provenance = the FSM) and then continue to a `confirmed`.
- **X2** (line 110): a **safe fixture** (same shape, vuln patched) is **REFUSED with a typed terminal**, not
  `confirmed`, not opaque `blocked`. *Closes G2,G6.* — the epic-level negative: the safe fixture must be refused at the
  **earliest failing state** with a TYPED terminal (e.g. `sink_not_reachable` at c5, or `provision_unrunnable` at c2).
- **X4** (line 112, foundational, owned by P1.1 but every new transition must satisfy it): every FSM transition is
  gated; zero transitions auto-advance on absent evidence. **Each new state P2.1 adds MUST register a gate in
  `gate_executor._TRANSITION_GATES` and a `TypedTerminal` member, or it silently auto-advances** (the X4 contract).
- Secondary touches: **X9** (line 117) teardown asserts target byte-identical to `target_sha` — c3/c6 lay the
  jail-recipe + snapshot groundwork (the teardown half lands in P2.2/the back-half FSM, but the snapshot discipline
  is c6's). **X10** (line 118) jailed/no-net/lockfile-only install — c2 is the env-FSM consumer of P0.2's pattern.

### 1.3 The FSM design (gap analysis §3, lines 171-197)

```
[0 DETECT] → [1 PROVISION] → [2 JAIL-BUILD] → [3 HEALTH-PROBE] → [4 REACHABILITY-PROBE]
          → [5 BASELINE-CAPTURE] → [6 DETONATE] → [7 DIFFERENTIAL-CONFIRM] → [8 TEARDOWN]
                    ↑___________ retry-with-fallback (bounded) ___________|
```

P2.1 = **the front half, states 0–5** (DETECT…BASELINE-CAPTURE). States 6–8 are existing/P1.x/P2.2/back-half.

**Net-new vs extends (gap analysis §3 + §7 [AUDIT] lines 362-369):**
| State | Net-new? | Reuse anchor in `ngv2/` (file:line) |
|---|---|---|
| 0 DETECT | **extends** (net-new glue) | `web_framework_detect.detect_frameworks`, `entrypoint_scan.scan_entrypoints`, `language_patterns`, `contracts.Target{language,repo_root,pinned_commit}` (contracts.py:48-55) — but NO interpreter/ABI resolver or eligibility gate exists yet |
| 1 PROVISION | **NET-NEW (long pole #2)** — *inverse* of today's installer | today = host-side full-network stderr-driven `poc_runner_live._default_pip_installer` (poc_runner_live.py:434, `MAX_DEP_INSTALL_ROUNDS=3`:388) — must be REPLACED, not reused; JM-side P0.2 jailed-install pattern (`target_bootstrap._ensure_venv`, landed `2049f78`) is the template |
| 2 JAIL-BUILD | **CLEAN REUSE** | `poc_runner_live.build_detonation_jail_argv` (poc_runner_live.py:69) + `bwrap_available` (:65) already exist and are robust (incl. shared-loopback netns) |
| 3 HEALTH-PROBE | **NET-NEW (long pole #1)** — no service-startup code in `ngv2/` (grep-confirmed) | building blocks only: `LoopbackListener` (loopback_listener.py:7) shows the bind/serve pattern; nothing starts a TARGET service |
| 4 REACHABILITY-PROBE | **partly net-new** | `sink_instrument.trace_sink_firing` (sink_instrument.py:7, **DEAD — 0 prod importers**), `sink_presence_gate.verify_sink_present`, `sink_reachability_gate.assess_sink_reachability`, `entrypoint_scan` exist; the benign-sentinel driver that runs the real entrypoint is net-new |
| 5 BASELINE-CAPTURE | **extends** | `poc_runner_live.snapshot_tree`/`diff_snapshots` (poc_runner_live.py:141/173) exist; the benign-control negative-control capture as an FSM gate is net-new |

---

## 2. The EXISTING FSM — states, transitions, modules (file:line), and the gap each child closes

**The current FSM has NO env-readiness front half.** `PHASE_ORDER` and `_INITIAL_PHASE` prove it:

| Fact | Evidence (file:line) |
|---|---|
| Phase order (no DETECT/PROVISION/JAIL/HEALTH/REACH/BASELINE) | `transition_planner.py:9` and `gate_executor.py:97`: `PHASE_ORDER = ('source','hunt','triage','verify','poc','detonate','novelty','report','awaiting_submission','submitted','done')` |
| The hunt SKIPS straight to `hunt` (no env stand-up) | `run_hunt.py:61` `_INITIAL_PHASE = 'hunt'`; `_ensure_seeded` seeds `phase='hunt'` (run_hunt.py:81) |
| Planner spawn/advance loop (the worker_phases list) | `transition_planner.plan_next_action` (transition_planner.py:19), `worker_phases` list (transition_planner.py:64-72) — keys: hunt/triage/verify/poc/detonate/novelty/report |
| Per-transition gate table (all 10 transitions gated, fail-closed) | `gate_executor._TRANSITION_GATES` (gate_executor.py:39); `run_gates` skips absent-evidence gates → `advance:False` (gate_executor.py:73-78,93) |
| Typed-terminal enum (13 members) | `gate_executor.TypedTerminal` (gate_executor.py:25-38) — **no env-readiness terminals** (`no_build_system`, `provision_unrunnable`, `jail_unavailable`, `sink_not_reachable`, `baseline_vacuous` are all MISSING) |
| Conductor step dispatch (the wiring backbone) | `hunt_conductor.run_conductor_step` (hunt_conductor.py:14): `plan` → `command_for_phase` → `spawn`/`harvest`/`persist` (spawn_stage action) OR `build_evidence`→`run_gates`→`advance` (apply_gates action) |
| Cross-process evidence threading (persist) | `conductor_seams.persist` (conductor_seams.py:48); `_PHASE_COUNT_KEY` 3-of-7 (conductor_seams.py:20 — `{hunt:findings, poc:pocs, detonate:reports}`); intermediate count_fields (conductor_seams.py:59) |
| Evidence translation for gates | `conductor_seams.build_evidence` (conductor_seams.py:112) — builds `poc_source`/`target_import_names`/`target_source`/`expected_signature`/`sink_name`/`call_sites`/`detonation_report`/`source_ready` |
| Phase → worker command spec | `stage_command_map.command_for_phase` (stage_command_map.py:12); `AGENT_PHASES` (stage_command_map.py:10) — 7 phases, **no env phases** |
| Worker seam builder (per-phase) | `workers/_runner.build_seams` (workers/_runner.py:56); `_make_detonation_seam` (workers/_runner.py:221) passes a `target_spec` of only `{repo_root, env}` (workers/_runner.py:291) — the G1/P2.2 gap |
| Live jail + dep install (the PROVISION anti-pattern) | `poc_runner_live.detonate_live` does HOST-SIDE network pip install on `ModuleNotFoundError` (poc_runner_live.py:331-352, `_default_pip_installer`:434) — full network, OUTSIDE jail — the inverse of PROVISION |

**Gap each child closes:** all six close **G1 (no env stand-up stage anywhere)** — the current FSM begins at `hunt`
with an un-provisioned, un-probed, un-baselined target, which is exactly why every historical confirmation is a mock
(the engine never stood up a real runtime). c4/c5 additionally close G2/G3 substance (sink reachability + service
liveness); c6 closes the G2 vacuous-baseline footgun; c2 closes G8 (jailed install) on the env path.

**The four coordinated touch-points every new state requires** (this is the integration contract — a child that
edits only one of these silently breaks):
1. `PHASE_ORDER` — insert the new phase IN ORDER, in BOTH `transition_planner.py:9` AND `gate_executor.py:97`
   (they are duplicated string tuples; they MUST stay identical or `run_gates`' consecutive-index check desyncs).
2. `transition_planner.worker_phases` (transition_planner.py:64) — add `(phase, count_field, next_phase)` so the
   planner spawns/advances it.
3. `gate_executor._TRANSITION_GATES` (gate_executor.py:39) + a `TypedTerminal` member — register the advance gate
   (else X4 violated: ungated consecutive transition auto-advances).
4. `conductor_seams`: `_PHASE_COUNT_KEY`/`persist` count-threading (conductor_seams.py:20,48) +
   `build_evidence` (conductor_seams.py:112) emitting the new state's evidence key + `stage_command_map.AGENT_PHASES`
   (stage_command_map.py:10) + a new `workers/<phase>.py` module + its `build_seams` branch (workers/_runner.py:56).

> ⚠️ This is the SAME class of cross-process wiring gap that X1 (P1.1) is stuck on (`_PHASE_COUNT_KEY` 3-of-7 →
> autonomous `run_hunt` dead-ends). **Every P2.1 child must wire ALL FOUR touch-points or it reproduces the X1 dead-end.**
> A shared-contract leaf (§3 c0) should land the integration scaffold first.

---

## 3. Per-child decomposition

> **Recommended correction to the 6-name memory:** the contract's 6 children (c1–c6) are correct, BUT they share an
> integration-scaffold dependency the contract glosses (the §2 four-touch-point wiring + the content-hashed
> evidence-artifact schema named in contract:86 as "the shared-contract leaf to land FIRST"). I add **c0
> `fsm_evidence_schema_and_phase_scaffold`** as the mandatory first leaf. So: **7 leaves (c0 scaffold + c1–c6)**, not 6.

### c0 — `fsm_evidence_schema_and_phase_scaffold` (SHARED CONTRACT — land FIRST, serial)
- **Net-new vs extends:** net-new glue (no new behavior; the integration spine).
- **Target module/symbol:** new `ngv2/env_readiness.py` (the content-hashed per-state evidence-artifact dataclass +
  `phase_artifact_hash()`), plus the ordered `ENV_PHASE_ORDER` constant the six states slot into; a single test fixture
  pair (safe/vuln target dir) under `ngv2/tests/fixtures/`.
- **Fail-closed property:** the schema's `advance_gate(prev_artifact)` helper returns `advance:False` for an
  absent/None/unhashable prior artifact (the "absent evidence ≠ pass" §3 invariant), so every downstream state inherits
  fail-closed-by-construction.
- **RED oracle:** *positive* — `phase_artifact_hash(sample)` is deterministic + content-addressed (same input → same
  hash; differs on any field change). *negative* — `advance_gate(None)` and `advance_gate({})` → `advance:False`.
  Import generated code via importlib; no clock/uuid/random.
- **Xn:** foundational for X1/X2/X4 (not itself an X).
- **meta_task_type:** `validation` (pure decision/schema fn; ngv2-routed → smoke_gated, no stateful_fuzz). **NOT
  `state_machine`** — see §3 note on stateful_fuzz.
- **Wire-up / LIVE_ROOT:** reachable from `run_hunt`→`build_default_seams` (assert a non-test importer once a state
  consumes it).
- **Deps/order:** depends on P1.1 typed-terminal enum (extends it). Blocks c1–c6. Parallel with nothing.

### c1 — `fsm_detect`
- **Net-new vs extends:** EXTENDS (`web_framework_detect`, `entrypoint_scan`, `language_patterns`, `contracts.Target`)
  + net-new glue (interpreter/ABI resolver + eligibility-at-entry as an FSM state).
- **Target module/symbol:** new `ngv2/fsm_detect.py::detect(repo_root, pinned_commit) -> DetectArtifact`; calls
  `web_framework_detect.detect_frameworks` (web_framework_detect.py) + resolves `python_bin`/`node_bin` from
  `.python-version`/`pyproject.toml`.
- **Fail-closed property:** language ∉ {py,js} OR no build file OR interpreter unresolved OR SHA ≠ pin → DENY with a
  typed terminal (`no_build_system` / `no_eligible_language` / `interpreter_unresolved` / `sha_mismatch`). Must never
  pass an env on to PROVISION without a resolved ABI interpreter.
- **RED oracle:** *positive* — a py fixture with `pyproject.toml` + `.python-version` → `language=='py'`,
  `python_bin` resolved, `build_file_present`, advance. *negative (load-bearing)* — a fixture with NO build file →
  `advance:False`, `terminal=='no_build_system'`; a fixture whose `.python-version` names an absent interpreter →
  `interpreter_unresolved`. Data-driven (fixture dirs), determinism-clean.
- **Xn:** X1 (positive path), X2 (safe/ineligible fixture refused with typed terminal).
- **meta_task_type:** `validation` (pure classifier over filesystem; ngv2-routed → smoke_gated). Avoid `state_machine`.
- **Wire-up / LIVE_ROOT:** first state of the env-FSM; reachable from `run_hunt` via the c0 scaffold; assert
  `fsm_detect.detect` has a non-test importer (the conductor seam).
- **Deps/order:** after c0. Then PARALLEL with c2/c3 (disjoint files).

### c2 — `fsm_provision` **[NET-NEW — long pole #2]**
- **Net-new vs extends:** NET-NEW (the *inverse* of the host-side network installer at poc_runner_live.py:331-352;437).
- **Target module/symbol:** new `ngv2/fsm_provision.py::provision(detect_artifact) -> ProvisionArtifact`; reuses the
  JM-side jailed-install PATTERN from `harness/target_bootstrap._ensure_venv` (landed `2049f78`) — venv in an
  outside-repo scratch, `--unshare-net`, lockfile-only (`-r <lock>`), ABI interpreter from c1, fail-closed if bwrap
  absent. Also REPLACES `poc_runner_live._default_pip_installer`'s reactive stderr loop (a sibling task / P0.2 NGv2
  counterpart, contract:204).
- **Fail-closed property (TWO):** (a) NEVER install an attacker-named (stderr-derived) package — lockfile-only
  (closes G8/X10); (b) gate on a REAL import/smoke probe, NOT build success — a "builds but won't import" target →
  typed `provision_unrunnable` (the EnvBench BUILT≠runnable lesson; contract:330).
- **RED oracle:** *positive* — a fixture with a valid lockfile → venv built with the c1 ABI interpreter, a smoke
  `import <pkg>` succeeds, advance. *negative (load-bearing, TWO)* — (1) a fixture whose dep-resolution stderr names
  `evil-pkg` → `evil-pkg` is NOT installed (assert absent from venv) [X10]; (2) a fixture that pip-builds but whose
  package fails to import → `advance:False`, `terminal=='provision_unrunnable'`. Install argv contains `--unshare-net`
  (assert).
- **Xn:** X1, X2, **X10** (jailed/no-net/lockfile-only install).
- **meta_task_type:** `io_adapter` or `validation`. The decision/gate fn (smoke-probe → advance) is pure and
  smoke-gated. The impure jailed-install helper is the **owner-hand-authored / irreducible** seam (see §5 Q2) — likely
  authored as a separate quarantined helper the pure gate INJECTS, mirroring `poc_runner_live`'s quarantine model.
- **Wire-up / LIVE_ROOT:** second env-FSM state; the produced venv path feeds JAIL-BUILD/HEALTH-PROBE/DETONATE
  `target_spec` (the P2.2 hand-off). Assert non-test importer.
- **Deps/order:** after c0+c1; **after P0.2** (shares the jailed-install helper, contract:329/risk-register:529).
  Same-file-collision risk with the P0.2-NGv2-counterpart on `poc_runner_live.py` → split by symbol/region.

### c3 — `fsm_jail_build` **[CLEAN REUSE]**
- **Net-new vs extends:** EXTENDS — thin wrapper over the existing, robust `build_detonation_jail_argv`.
- **Target module/symbol:** new `ngv2/fsm_jail_build.py::jail_build(provision_artifact) -> JailArtifact`; calls
  `poc_runner_live.bwrap_available` (poc_runner_live.py:65) as a LOUD preflight and validates
  `build_detonation_jail_argv` (poc_runner_live.py:69) is constructible (target ro-bind, tmpfs scratch, net/ipc/pid
  unshared).
- **Fail-closed property:** `bwrap` absent / jail un-constructible → typed `jail_unavailable` HERE (preflight), not a
  silent detonate-time crash. Never emit a JailArtifact that implies a working jail when bwrap is missing.
- **RED oracle:** *positive* — bwrap present → `jail_constructible==True`, argv contains `--unshare-net --unshare-ipc
  --unshare-pid`, advance. *negative (load-bearing)* — bwrap absent (inject a `which`-returns-None seam, NOT real PATH
  mutation, for determinism) → `advance:False`, `terminal=='jail_unavailable'`.
- **Xn:** X1, X2; lays X9 jail-recipe groundwork.
- **meta_task_type:** `validation` (pure gate; the impure argv-build already lives in the quarantined
  `poc_runner_live`). ngv2-routed → smoke_gated. The spec mentions loopback/jail → also smoke-gated via the
  plan_normalizer:696 hint list.
- **Wire-up / LIVE_ROOT:** third env-FSM state; the JailArtifact (recipe) is consumed by HEALTH-PROBE + DETONATE.
- **Deps/order:** after c0. PARALLEL with c1/c2 (disjoint files — wraps an existing symbol, doesn't edit
  poc_runner_live). Lowest-risk child; good first real state to prove the c0 scaffold.

### c4 — `fsm_health_probe` **[NET-NEW — LONG POLE #1]**
- **Net-new vs extends:** NET-NEW — **no service-startup code exists anywhere in `ngv2/`** (grep-confirmed; only
  `LoopbackListener` binds, and that is OUR listener, not the target's service).
- **Target module/symbol:** new `ngv2/fsm_health_probe.py::health_probe(jail_artifact, provision_artifact) ->
  HealthArtifact`. Two sub-capabilities: (a) clean `import <target_pkg>` INSIDE the jail; (b) for a service target,
  start it (`python -m <app>` / the detected entrypoint) and confirm it binds `127.0.0.1:<port>` within a timeout, then
  hit a health route/banner.
- **Fail-closed property:** import fails OR service never binds within timeout → typed `service_no_bind` (and an
  escalation hook for outbound-net startup → P4.3 VM tier). NEVER auto-advance an unhealthy env.
- **RED oracle:** *positive* — an importable fixture → `import_ok`; a flask/fastapi service fixture that binds
  loopback → `service_bound==True`, `health_route_ok`, advance. *negative (load-bearing)* — a fixture that raises on
  import → `import_ok==False`, `advance:False`; a service fixture that never binds within timeout → `service_no_bind`.
  ⚠️ The bind/timeout makes a NAIVE oracle non-deterministic — see §5 Q3 (the pure GATE fn over a HealthArtifact is the
  fuzzable seam; the actual start-and-bind is a quarantined impure helper the gate injects).
- **Xn:** X1, X2.
- **meta_task_type:** `io_adapter` for the impure start/bind helper (quarantined, like poc_runner_live; spec mentions
  bind/listener → smoke_gated automatically via plan_normalizer:696); `validation` for the pure HealthArtifact gate.
  **Avoid `state_machine`** (stateful_fuzz on a service-start helper would be both meaningless and flaky).
- **Wire-up / LIVE_ROOT:** fourth env-FSM state; the bound port + start command feed DETONATE's `target_spec`.
- **Deps/order:** after c0+c2+c3 (needs the provisioned venv + jail recipe). This is THE long pole — budget
  ~1.5–2× attempts (risk-register:528/531) and likely multiple block→re-plan cycles. Scope a minimal loopback-bind
  probe FIRST; defer outbound-net startup to P4.3.

### c5 — `fsm_reachability_probe` **[PARTLY NET-NEW]**
- **Net-new vs extends:** PARTLY NET-NEW — reuses `sink_presence_gate.verify_sink_present`,
  `sink_reachability_gate.assess_sink_reachability` (already wired in `_TRANSITION_GATES` for detonate→novelty,
  gate_executor.py:39), `entrypoint_scan.scan_entrypoints`, and the DEAD `sink_instrument.trace_sink_firing`
  (sink_instrument.py:7 — must be WIRED, 0 prod importers today). The benign-sentinel driver that runs the REAL
  entrypoint into the sink region is net-new.
- **Target module/symbol:** new `ngv2/fsm_reachability_probe.py::reachability_probe(detect_artifact, finding,
  health_artifact) -> ReachabilityArtifact`; wires `sink_instrument.trace_sink_firing` as the benign-ping verifier.
- **Fail-closed property:** sink absent/commented/patched (presence gate False) OR sink only ever constant-arg'd
  (reachability gate `constant_only`) OR benign sentinel never reaches the sink line → typed `sink_not_reachable`.
  Proves the sink is LIVE attacker-reachable code BEFORE any detonation.
- **RED oracle:** *positive* — a fixture whose sink is live + takes an external arg + a benign ping drives the real
  entry into the sink line → `sink_presence ∧ sink_reachability ∧ benign_ping_reached`, advance. *negative
  (load-bearing)* — a fixture whose sink is commented out → `verify_sink_present`→patched →`sink_not_reachable`; a
  fixture whose sink is only called with a hardcoded literal → `assess_sink_reachability`→`constant_only`
  →`advance:False`. The benign-ping uses `trace_sink_firing` (settrace) — determinism caveat §5 Q3.
- **Xn:** X1, X2 (and substantively closes G2/G3 — "is the sink real and reachable").
- **meta_task_type:** `validation` (the presence/reachability gates are already pure differential-fuzzable fns); the
  settrace benign-ping helper is the impure injected seam (`io_adapter`, smoke_gated). **Avoid `state_machine`.**
- **Wire-up / LIVE_ROOT:** fifth env-FSM state; reachability verdict feeds BASELINE/DETONATE; **wire the dead
  `sink_instrument` to a live importer** (its own acceptance-gate requirement — orphan_unwired).
- **Deps/order:** after c0+c4 (needs a healthy importable env to run the benign ping). Some overlap with P1.3/P3.1
  substance — coordinate (do not double-wire sink channels).

### c6 — `fsm_baseline_capture`
- **Net-new vs extends:** EXTENDS — reuses `poc_runner_live.snapshot_tree`/`diff_snapshots` (poc_runner_live.py:141/173);
  the benign-control negative-control capture as an FSM gate is net-new.
- **Target module/symbol:** new `ngv2/fsm_baseline_capture.py::baseline_capture(jail_artifact, reachability_artifact)
  -> BaselineArtifact`; runs a BENIGN control input through the jail, snapshots FS, captures stdout.
- **Fail-closed property:** the success marker OR the expected_fs_signature is PRESENT in the benign control →
  the oracle would be vacuous (control already "confirms") → typed `baseline_vacuous` / REFUSE. This is the
  negative-control that makes DETONATE's differential meaningful (closes the G2 vacuous-confirm class on the env path,
  complements the P1.2 empty-sig reject at detonation.py:21).
- **RED oracle:** *positive* — a benign control input → marker ABSENT in control stdout ∧ fs_signature ABSENT in
  control fs-diff → `control_clean==True`, advance. *negative (load-bearing)* — a fixture where the benign control
  ITSELF emits the marker / writes the signature → `advance:False`, `terminal=='baseline_vacuous'`.
- **Xn:** X1, X2; foundational for X5 (differential reproducibility — the baseline IS the differential's negative arm).
- **meta_task_type:** `validation` (pure gate over a captured BaselineArtifact); the impure benign-run reuses the
  quarantined poc_runner_live jail-runner. Avoid `state_machine`.
- **Wire-up / LIVE_ROOT:** sixth/last env-FSM state; the baseline snapshot is consumed by DETONATE/DIFFERENTIAL-CONFIRM
  (the `∉ baseline` arm of every per-CWE channel).
- **Deps/order:** after c0+c3 (jail recipe) +c5 (a confirmed-reachable sink to baseline against).

### Note on `meta_task_type: state_machine` and stateful_fuzz (CRITICAL)
The contract labels the EPIC `state_machine`, but **individual impl leaves should NOT use `state_machine`.** Verified
in `harness/planner/taxonomies.py:1`: `state_machine` sets `{'bypass_fuzzer': False, 'stateful_fuzz': True}`. For an
NGv2 impl, `harness/planner/plan_normalizer.py:570 _force_smoke_gated_leaf_impl` ALREADY sets `smoke_gated=True` for any
impl that (a) touches an `ngv2/` file (plan_normalizer.py:679), (b) has an `ngv2.` mutation_target (:684), or (c) whose
spec mentions socket/listener/bind/loopback (:696). So every P2.1 child auto-routes to the smoke→embedded→narrow bypass
regardless. Using `state_machine` would needlessly invite `stateful_fuzz` (which on a stateful service/jail helper risks
divergence and flakiness) — prefer the NATURAL type: **`validation`** for the pure decision/gate fns (c0,c1,c3,c5,c6
gates), **`io_adapter`** for the impure provision/start/probe helpers (c2,c4 helpers). The EPIC-PLANNING brief itself can
carry `state_machine`/`epic_planning`; the LEAVES carry the natural type.

---

## 4. Recommended BUILD ORDER (dependency-topological) + parallelism

```
SERIAL FLOOR (must precede the fan-out):
  P0.1 (landed) → P0.2 (JM landed; NGv2 counterpart ☐) → P1.1 X1-wiring (in flight) → P1.2 → P1.3
                                                                                          │
  c0  fsm_evidence_schema_and_phase_scaffold  ◄── land FIRST (shared contract + 4-touch-point scaffold)
       │
  ─────┼──────────────── FAN-OUT WAVE A (parallel, disjoint files) ────────────────
       ├── c1 fsm_detect           (validation)   ─┐
       ├── c3 fsm_jail_build       (validation)    ├─ all 3 disjoint → arm 3-wide
       └── c2 fsm_provision        (io_adapter)*   ─┘  (*c2 soft-after P0.2; same-file risk on poc_runner_live → split by region)
       │
  ─────┼──────────────── FAN-OUT WAVE B (parallel after A) ──────────────────────────
       ├── c5 fsm_reachability_probe (validation)  ── after c4? no: c5 needs healthy env → after c4
       └── c4 fsm_health_probe     (io_adapter)    ── LONG POLE; needs c2(venv)+c3(jail)
       │
  ────────────────────── WAVE C (after B) ──────────────────────────────────────────
       └── c6 fsm_baseline_capture (validation)    ── needs c3(jail)+c5(reachable sink)
       │
  ────────────────────── INTEGRATION / hand-off ────────────────────────────────────
       └── P2.2 detonation_seam_full_target_spec  ── consumes the env-FSM target_spec (the X1 vuln-fixture e2e)
```

**Topological order:** `c0` → {`c1` ∥ `c3` ∥ `c2`} → {`c4` then `c5`} → `c6` → P2.2.

**Can be armed in PARALLEL (disjoint `files_touched`):**
- Wave A: **c1 ∥ c3 ∥ c2** — three separate new `ngv2/fsm_*.py` modules. c2 has a same-file collision with the
  P0.2-NGv2-counterpart on `poc_runner_live.py` → split by symbol/region patch (contract:314 §1A).
- Keep ≥1 CROSS-REPO item queued (a JM-side P-WIREUP Tier-0 leaf, or P3.2-c1 JS-validity) so a stalled NGv2 dep never
  idles all 4 slots (gap analysis §7.0:323, contract §1A:81).

**Stays SERIAL (the floor):**
- c0 before everything (shared contract; contract:86).
- c4 needs c2+c3; c5 needs c4; c6 needs c3+c5 (data dependency on the prior state's artifact).
- The dependency spine P1.1→P1.2→P1.3→P2.1→P2.2 (contract:91) — P2.1 should not START its detonation-touching wiring
  until P1.2/P1.3 land (else c5/c6 collide with P1.3's per-CWE channels on `detonation.py`).
- One `git_commit.lock` → only the final ff-merge serializes.

**Right-size the wave width to 4 (the program default `parallel_cap:4`, contract §1A:61):** c0 (1 slot, serial) →
Wave A fills 3 NGv2 slots + 1 cross-repo → Wave B fills 2 + 2 cross-repo. Author the brief frontier ahead of the build
frontier (planner plans ≤1 unplanned brief/iter, contract §1A:73).

---

## 5. Open design questions / risks needing an owner/orchestrator decision BEFORE authoring

**Q1 — Does PROVISION (c2) need to stand up a REAL target env, or is a fixture-only oracle sufficient for the build?**
The contract says "build `.venv` from the target's own lockfile" but the trust mandate (X1) needs a vuln FIXTURE to
go end-to-end. Decision needed: do we (a) ship c2 with a tiny built-in safe/vuln FIXTURE PAIR (recommended — hermetic,
deterministic, matches the JanusMask oracle discipline) and defer real-corpus-target provisioning to the capstone, or
(b) require c2's oracle to provision an actual corpus clone (non-hermetic, slow, flaky)? **Recommend (a).** This gates
how the fixtures in c0 are shaped.

**Q2 — How much of c2/c4 is irreducible-tier hand-authored vs pipeline-built?** The PRE-EXISTING
`poc_runner_live.py` is, as a FACTUAL matter of its current state, owner-hand-authored / NOT fuzz-verifiable
(poc_runner_live.py:1-38 docstring) — it does real fork/execve in a jail. c2's jailed-install helper and c4's
service-start helper are the SAME class of impure, side-effecting, network/subprocess code, and the differential
fuzzer cannot validate non-deterministic side-effecting execution. The technical analysis stands: these cP producers
are impure and not fuzz-coverable in the usual way. **But the prior conclusion — "strongly recommend the quarantine
split (pure gate pipeline-built + impure helper hand-authored-with-owner-signoff)" — is SUPERSEDED by the owner
directive below.** The impure helper's buildability is NOT pre-decided as a hand-edit; it is attempted through the
pipeline first, and a hand-edit becomes an option ONLY if that documented pipeline attempt fails.

> **★ POLICY — PIPELINE-FIRST IS MANDATORY (owner directive 2026-06-24).** No cP producer / impure helper (jailed venv-build, target service-start+bind, settrace benign-ping, jailed benign-run, or any `poc_runner_live`-class side-effecting code introduced for P2.1) may be declared "requires owner hand-edit" or "irreducible / not-pipeline-built" until it has been ATTEMPTED through the planner→stage→worker pipeline at least once and that attempt has FAILED with a documented, specific reason. First resort: build it through the pipeline, augmenting the agents/planner THROUGH the pipeline as needed (per the spec-only directive). Hand-editing is the LAST resort, escalated to an owner decision ONLY after a real pipeline attempt is recorded as failed. "Owner-gated" never means "leave it built-but-not-working"; the bar remains demonstrated-live (BUILT≠WORKS).

**Decision (revised): attempt each cP impure producer through the pipeline first** (the PURE gate fn is pipeline-built
regardless — that part of the prior recommendation is unchanged and correct). If a specific producer's pipeline build
records a concrete failure (e.g. the fuzzer rejects non-deterministic side effects with a documented `fuzz_error`),
THAT failure — not an a-priori assumption — escalates to an owner hand-edit decision for that one producer. The
note that the gap analysis budgets these as a BUILD (not merely a wiring) job is retained, but a BUILD job is a
pipeline job by default, not a hand-edit job.

**Q3 — Determinism of c4/c5 oracles (settrace + service-bind + timeout).** The RED oracles for HEALTH-PROBE (bind +
wall-clock timeout) and REACHABILITY (`sink_instrument.trace_sink_firing` uses `sys.settrace` + runs `func`) are
inherently impure/timing-sensitive, which collides with the "determinism-clean, no clock, importlib-import" oracle
rule. **Decision: the oracle must test the PURE GATE fn over a pre-captured Health/Reachability ARTIFACT (deterministic
fixture JSON), and the impure start/probe helper is tested only by a smoke gate, not a differential-fuzz oracle.** Need
confirmation this satisfies the §5 self-exam invariant (negative control required) without a non-hermetic test. This
shapes whether c4/c5 split into TWO leaves each (pure gate leaf + impure helper leaf). NOTE: the pure-gate-oracle
decision here is correct and unchanged. The impure start/probe helper's own BUILDABILITY is NOT decided here — it
follows the Q2 PIPELINE-FIRST policy (attempt through the pipeline first; smoke-gate it; a hand-edit is the last
resort only after a documented pipeline-build failure). A smoke gate being the test surface does NOT imply the helper
is hand-authored.

**Q4 (lower) — PHASE_ORDER duplication across two files.** `PHASE_ORDER` is a duplicated literal in
`transition_planner.py:9` AND `gate_executor.py:97`. Inserting 6 new phases means editing the SAME ordered tuple in two
files that MUST stay byte-identical (the `run_gates` consecutive-index check, gate_executor.py:58, desyncs otherwise).
**Decision: should c0 first REFACTOR `PHASE_ORDER` into a single shared constant (e.g. in the new `env_readiness.py` or
a `phases.py`) imported by both, to remove the duplication footgun before the six children each edit it?** Recommend
yes — it's a small same-file-collision-avoidance win and prevents a desync class of bug. (This touches the live
`transition_planner.py`/`gate_executor.py` — coordinate with P1.1/P3.3 which also edit them.)

**Q5 — Where does the env-FSM ATTACH to `run_hunt`?** Today `_INITIAL_PHASE='hunt'` (run_hunt.py:61) and `_ensure_seeded`
seeds `phase='hunt'`. Inserting DETECT…BASELINE before hunt means changing `_INITIAL_PHASE` to `'detect'` and extending
the seed — but the OLD `source` phase (PHASE_ORDER[0]) is currently inert. **Decision: do the 6 env states slot
BEFORE `hunt` (so `detect→provision→jail_build→health_probe→reachability_probe→baseline_capture→hunt→…`), and does
`source` get folded into DETECT or removed (P3.3's "seed source or remove it")?** This is the wire-up point the
EPIC-level "reachable from run_hunt" condition (contract:350) hinges on, and it determines the exact `worker_phases`
insertion. Note: env states run ONCE per session up-front, not per-finding — confirm they sit before the per-finding
hunt loop, not inside it.

**Q6 (coordination) — c5/c6 vs P1.3/P3.1 on `detonation.py` + sink channels.** c5 wires `sink_instrument`; P3.1 wires
`auth_bootstrap`; P1.3 wires `LoopbackListener` + per-CWE channels — all touch the detonation/evidence substance.
**Decision: confirm P1.2+P1.3 land before P2.1 c5/c6 start** (the spine order, contract:91) so the per-CWE channels and
the baseline differential don't collide on `detonation.py`/`conductor_seams.build_evidence`.

---

## Appendix B — prior JM staging survey (Explore agent, 2026-06-24)

**No env-readiness FSM is staged anywhere in JanusMaskJR** — `_autowork_scratch/p21_env_fsm/` was empty before this
file; no `brief_hooks_*{fsm,env,detect,provision,health,reach,baseline}*` exists. Staging-conflict risk: LOW.
Relevant ADJACENT assets the build can lean on (do not re-derive):
- `_autowork_scratch/ngv2_fsm/` — landed conductor infra (conductor_seams, gate_executor, stage_command_map, _runner)
  matching NGv2 master; these are the §2 touch-points the children edit.
- `_phase_prep/phase2/` — `pathtrav_detect.py`/`ssrf_detect.py` reference detectors + wired oracles (c1/c5 inputs).
- `_phase_prep/phase3/` — reachability cascade references (`entrypoint_scan`, `reachability_triage`,
  `source_sink_prefilter`, `codeql_*`) + `test_reachability_triage_wired.py` (c5 inputs; CodeQL provision design in
  `_phase_prep/phase3/BUILD_PLAN.md` overlaps the DETECT/PROVISION discussion — review before authoring c1/c2).
- `_c3_pending/` — `test_detonation_requires_semantic_oracle_wired.py` (DRAFT C3 detonation-gate oracle) + a validated
  `poc_writer` (detonation-side, downstream of P2.1).

## Appendix A — corrected child count
The 6-name memory (DETECT/PROVISION/JAIL-BUILD/HEALTH-PROBE/REACHABILITY/BASELINE) is CORRECT per the contract.
This decomposition adds **c0 (shared scaffold/evidence-schema leaf)** as a mandatory predecessor — making **7 leaves**
— because the four-touch-point cross-process wiring (the exact class that has X1/P1.1 stuck) and the content-hashed
evidence-artifact schema (contract:86 "land FIRST") are not optional and are shared by all six states. Several children
(c2,c4,c5) likely SPLIT into a pure-gate leaf + an impure-helper leaf pending the §5 Q2/Q3 quarantine decisions, which
would raise the leaf count further (estimate 7–11 leaves total).
