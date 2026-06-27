---
slug: c7_fsm_live_integration
working_dir: "/home/xnihil0zer0/NobleGreedv2"
complexity_score: high
required_task_ids:
  - c7-phase-order-unify-impl
  - c7-gate-bridge-impl
  - c7-seams-env-dispatch-impl
  - c7-conductor-planner-impl
  - c7-initial-phase-flip-impl
  - c7-fsm-live-integration-oracle
---

# Title

P2.1 c7 — fsm_live_integration: wire the 6 env-readiness FSM phases into the live
`run_hunt` path so the cP producers + fsm_* handlers are CALLED on a real hunt
(not merely import-reachable), proving BUILT -> WORKS.

The env-FSM is BUILT-not-WORKS today: c0 landed the shared evidence schema
(`ngv2/fsm_evidence.py`: `PHASE_ORDER`, `ENV_PHASE_ORDER`, `phase_artifact_hash`,
`advance_gate`), c1-c6 landed the 6 pure handlers (`ngv2/fsm_detect.detect`,
`fsm_provision.provision_gate`, `fsm_jail_build.jail_build_gate`,
`fsm_health_probe.health_probe`, `fsm_reachability_probe.reachability_probe`,
`fsm_baseline_capture.baseline_capture`), and cP landed the 6 impure producers
(`detect_producer.produce_detect_input`, `provision_producer.produce_provision_input`,
`jail_producer.produce_jail_input`, `health_producer.produce_health_input`,
`reachability_producer.produce_reach_input`, `baseline_producer.produce_baseline_input`).
BUT `run_hunt` still starts at phase `hunt` (`run_hunt.py:61 _INITIAL_PHASE='hunt'`),
`conductor_seams.build_default_seams` has NO env-phase seam, the planner/conductor
have no env action branch, and `gate_executor` never consumes a content-hashed env
artifact. So a live `run_hunt` traverses `hunt->triage->...` and NEVER calls a single
env producer or handler. This leaf closes that gap end-to-end.

# Scope

Six tasks in ONE flat, strictly serial plan (NOT an epic). Each impl edits live FSM
files; the final task is the call-path oracle that drives REAL `run_hunt`. Serial dep
chain: 1 -> 2 -> 3 -> 4 -> 5 -> 6.

EXPLICIT DESIGN DECISIONS (stated here, binding on the impl):

- DECISION (i) — SEAM PATH, NOT WORKER SUBPROCESS. The 6 env states are dispatched
  through an in-process producer->handler SEAM inside `conductor_seams`, NOT through
  `python -m ngv2.workers.<phase>` subprocess spawns and NOT through
  `stage_command_map`/`workers/_runner.py`. This DIVERGES from the DECOMP §2 literal
  text ("a new `workers/<phase>.py` per state + stage_command_map.AGENT_PHASES"). Reason:
  the env phases run ONCE up-front per session over the SAME `repo`/`target_path`, are
  pure-decision over producer-built dicts, and must re-validate a content-hash in the
  SAME process — a subprocess round-trip through stage_command_map adds cross-process
  serialization with no benefit and breaks the content-hash chain. `stage_command_map`
  and `workers/**` are left UNTOUCHED for env phases (they stay `hunt..report` only).

- DECISION (ii) — PHASE_ORDER FOLDING. The 6 ENV phases slot AHEAD of `hunt` in the
  single source `fsm_evidence.PHASE_ORDER`. The inert leading `source` phase is FOLDED
  INTO `detect` (i.e. `source` is removed; `detect` becomes index 0). Final
  `PHASE_ORDER` = `('detect','provision','jail_build','health_probe',
  'reachability_probe','baseline_capture','hunt','triage','verify','poc','detonate',
  'novelty','report','awaiting_submission','submitted','done')`. The run_gates
  consecutive-index check (`gate_executor.py:58-62`) keys off `PHASE_ORDER.index`, so it
  stays consistent automatically once the single source is updated and the three live
  duplicate literals DERIVE from it. The `('source','hunt')` entry in
  `_TRANSITION_GATES` is dropped/superseded by the env gates (its `source_ready` check
  is subsumed — detect emits a real DetectArtifact only when the repo is genuinely
  resolved).

The env phases run BEFORE the per-finding hunt loop, once per session.

# Non-Goals

- This brief IS the integration leaf. The word **integration** appears here so the
  planner routes it correctly: out of scope is any integration with EXTERNAL corpus
  targets or real-network provisioning — the oracle uses a hermetic stdlib-only fixture
  repo (no host pip, no real venv build). Do NOT make the oracle clone or provision a
  real corpus target; do NOT require network access.
- No back-half FSM work (detonate/differential-confirm/teardown stay as-is). c7 wires
  ONLY the 6 front-half env states `detect..baseline_capture` ahead of `hunt`.
- Do NOT touch `ngv2/workers/**`, `stage_command_map.py`, or `artifact_harvester.py` for
  env phases (per DECISION (i) — env phases are in-process seam dispatch, not workers).
- Do NOT re-author the c0 schema, the c1-c6 handlers, or the cP producers. They are
  landed and correct; this leaf CALLS them. The only handler-side change permitted is
  adding the 5 missing `TypedTerminal` members in task 2.
- Do NOT inject MOCK producer `*_fn` seams in the seam path. The env seam must call each
  producer with its DEFAULT (REAL) seams over the real fixture repo (real `os.walk`,
  real `shutil.which`, real interpreter resolution) so producer output is real-derived.
- No clock / uuid / random / unseeded nondeterminism in any impl symbol.

# Inputs

LIVE FSM FILES (working_dir = `/home/xnihil0zer0/NobleGreedv2`):

- `ngv2/fsm_evidence.py` — `PHASE_ORDER` (line 4, the SINGLE SOURCE), `ENV_PHASE_ORDER`
  (line 5), `phase_artifact_hash(artifact)` (line 7), `advance_gate(artifact)` (line 12
  — pops `content_hash`, recomputes, returns `{'advance', 'terminal'}`; fail-closed on
  None/non-dict/missing-hash/mismatch).
- `ngv2/transition_planner.py` — imports `PHASE_ORDER` from fsm_evidence (line 60);
  `_next_phase` (line 12); `plan_next_action` (line 20); `worker_phases` list (line 53).
- `ngv2/gate_executor.py` — imports `PHASE_ORDER` from fsm_evidence (line 107);
  `TypedTerminal` class (lines 25-38, MISSING the 5 env terminals); `_TRANSITION_GATES`
  (line 39, the `('source','hunt')` entry to supersede); `run_gates` (line 41,
  consecutive-index check lines 57-62).
- `ngv2/conductor_seams.py` — `_PHASE_COUNT_KEY` (line 20); `build_default_seams` (line
  39) returning the seam dict (line 255: `ctx, load_state, plan, command_for_phase,
  spawn, harvest, persist, build_evidence, run_gates, advance, run_conductor_step`);
  `persist` (line 48); `build_evidence` (line 112). ~440 lines, WHOLE_FILE_DRIFT HOTSPOT.
- `ngv2/hunt_conductor.py` — `run_conductor_step(session_id, seams)` (line 14):
  dispatches `spawn_stage`/`apply_gates`/`park_for_approval`/`advance`/`done`/`blocked`.
  Returns `{'step': ...}`; `'blocked'` is in `conductor_loop.TERMINAL_STEPS`.
- `ngv2/run_hunt.py` — `run_hunt(...)` (line 25, the live entrypoint); `_INITIAL_PHASE`
  (line 61, `'hunt'`); `_ensure_seeded` (line 63, seeds `phase=_INITIAL_PHASE` at line
  81 with `findings/pocs/reports/artifacts`).
- `ngv2/session_api.py` — `PHASE_ORDER` literal (line 675, DUPLICATE — must derive from
  fsm_evidence); `_PHASES` literal (line 716, DUPLICATE used by `create_session` line
  66/70); both feed `_next_phase` (line 404) / `advance` (line 524) / `create_session`.
- `ngv2/state_machine.py` — `LIFECYCLE_PHASES` literal (line 69, DUPLICATE — must derive
  from fsm_evidence); `LIFECYCLE_TRANSITIONS` (line 80, built from LIFECYCLE_PHASES by
  `_ordered_one_step`); the canonical 6-tuple `PHASES`/`ALLOWED_TRANSITIONS` (lines
  23/25) are the legacy hunt model — LEAVE THEM UNCHANGED (backward-compat).
- `ngv2/conductor_loop.py` — `run_until_terminal(session_id, seams, max_steps)`:
  `TERMINAL_STEPS = {'done','parked','blocked'}`; appends each step to `steps`.

HANDLER SIGNATURES (call shapes the seam must honor — return
`{'advance': bool, 'terminal': str, 'artifact': dict|None}`):

- `fsm_detect.detect(detect_input, prev_artifact=None)` — `is_entry=True` skips the
  prev gate; emits `{'phase':'detect','status':'success','details':{...},
  'content_hash':...}`.
- `fsm_provision.provision_gate(provision_input, prev_artifact=None)` — gates prev via
  advance_gate; needs `install_argv` with `--unshare-net` + `smoke_import_ok is True`.
- `fsm_jail_build.jail_build_gate(jail_input, prev_artifact=None)` — needs
  `bwrap_available` + `jail_argv` with the 3 unshare flags.
- `fsm_health_probe.health_probe(jail_artifact, provision_artifact=None, health_input=None)`.
- `fsm_reachability_probe.reachability_probe(detect_artifact, finding, health_artifact=None)`
  — `finding` carries `reach_input={'sink_present':bool,'sink_reachable':str,...}`.
- `fsm_baseline_capture.baseline_capture(jail_artifact, reachability_artifact=None)`
  — reads `jail_artifact['details']['baseline_input']` (or `details`) for
  `success_marker`/`expected_fs_signature`/`stdout`/`fs_diff`.

PRODUCER SIGNATURES (call with DEFAULT real seams):

- `detect_producer.produce_detect_input(repo_root, pinned_commit=None, *, walk_fn=default_walk_fn, head_commit=None, resolved_python_bin=None, resolved_node_bin=None)`.
- `provision_producer.produce_provision_input(resolved_python_bin, lockfile_packages, *, install_fn=None)`.
- `jail_producer.produce_jail_input(provision_artifact, repo_root, work_dir, which_fn=shutil.which, ...)`.
- `health_producer.produce_health_input(entry_point, is_service, jail_artifact=None, provision=None, import_fn=None, start_fn=None, probe_fn=None)`.
- `reachability_producer.produce_reach_input(finding, health_artifact=None, detect_artifact=None, ...)`.
- `baseline_producer.produce_baseline_input(success_marker, expected_fs_signature, *, jail_artifact=None, reachability_artifact=None, ..., repo_dir=None, work_dir=None, control_cmd=None)`.

FIXTURE for the oracle: copy `_e2e_run/target/vuln_service.py` (real CWE-78
`os.system("getent hosts " + hostname)` sink, stdlib `os` only) into a `tmp_path` repo.

DEMO MODEL (drives real `run_hunt`-class path, asserts real-derived values, anti-gaming
nonce): `/home/xnihil0zer0/JanusMaskJR/_autowork_scratch/x1_demo/demo_fsm_traversal.py`.

# Deliverables

Author EXACTLY SIX tasks in ONE plan, serial. Every impl task: `meta_task_type:
validation`, `priority: high`, `partial_edit: true` (multi-symbol edits of existing
files), each with an explicit `__JANUSMASK_PATCHES__` SYMBOL-patch recipe (one entry
per modified top-level symbol; R-anchor any NEW top-level symbol on an existing one in
the same file). `verification_command` is bare (NO `cd` prefix). regression_tests >= 2.
Each task's `# Non-Goals`/non_goals MUST contain `integration` (the planner routing
token; restate "no external-corpus integration").

CRITICAL HANDLER/HASH FACT the oracle relies on: every fsm_* handler computes its
`content_hash` over the artifact dict EXCLUDING `content_hash`, so the emitted artifact
passes `advance_gate` (which pops `content_hash`, recomputes, compares). The seam
persists that artifact verbatim; the gate-bridge re-validates it via `advance_gate`.
Tampering any artifact field WITHOUT recomputing the hash => `advance_gate` ->
`{'advance':False,'terminal':'hash_mismatch'}`.

TASK 1 — `c7-phase-order-unify-impl` (deps: []).
files_touched: `ngv2/fsm_evidence.py`, `ngv2/transition_planner.py`,
`ngv2/gate_executor.py`, `ngv2/session_api.py`, `ngv2/state_machine.py`.
- Slot the 6 ENV phases ahead of `hunt` in `fsm_evidence.PHASE_ORDER` (the single
  source); fold/remove the inert `source` (DECISION (ii)). Keep `ENV_PHASE_ORDER`.
- Route `session_api.PHASE_ORDER` (line 675), `session_api._PHASES` (line 716), and
  `state_machine.LIFECYCLE_PHASES` (line 69) to DERIVE from `fsm_evidence` by import +
  slice (e.g. `_PHASES = PHASE_ORDER` slice excluding env phases / `'source'`; or
  `from ngv2.fsm_evidence import PHASE_ORDER as _CANON`), NOT a re-typed literal. Keep
  each module's existing public shape (`_PHASES` must remain the 6-name agent tuple
  `('hunt','triage','poc','detonate','report','done')` derived as a slice; do not
  silently change `create_session`'s seed semantics).
- Closes A4-G2 (three live literals desync). __JANUSMASK_PATCHES__: one entry per
  modified top-level symbol (the module-level `PHASE_ORDER` assignment in fsm_evidence;
  the `PHASE_ORDER` + `_PHASES` module-level assignments in session_api; the
  `LIFECYCLE_PHASES` assignment in state_machine; any planner/gate constant touched).
- verification_command: `python -m pytest tests/ngv2/test_p21_c0_fsm_scaffold.py
  tests/ngv2/test_c7_fsm_live_integration.py -q`.

TASK 2 — `c7-gate-bridge-impl` (deps: [c7-phase-order-unify-impl]).
files_touched: `ngv2/gate_executor.py`.
- Add the 5 missing `TypedTerminal` members: `NO_BUILD_SYSTEM='no_build_system'`,
  `PROVISION_UNRUNNABLE='provision_unrunnable'`, `JAIL_UNAVAILABLE='jail_unavailable'`,
  `SINK_NOT_REACHABLE='sink_not_reachable'` (and `MALFORMED_INPUT='malformed_input'`),
  `BASELINE_VACUOUS='baseline_vacuous'`.
- Add a transition gate per consecutive ENV step in `_TRANSITION_GATES` (the 5 edges
  `detect->provision`, `provision->jail_build`, `jail_build->health_probe`,
  `health_probe->reachability_probe`, `reachability_probe->baseline_capture`, plus
  `baseline_capture->hunt`) whose gate caller invokes `fsm_evidence.advance_gate` on the
  PRODUCED env artifact (re-validating its `content_hash`), keyed off an evidence key
  the seam supplies (e.g. `ev['env_artifact']`). This is the FIRST LIVE CONSUMER of c0's
  content-hash model. Import `advance_gate` into gate_executor. Fail-closed: a missing
  `env_artifact` key => `<gate>:missing_evidence` (existing run_gates behavior); a
  present-but-tampered artifact => `advance_gate` returns advance False => the gate's
  `may_confirm` is False => `run_gates.advance=False`.
- Closes A4-G3. __JANUSMASK_PATCHES__: entries for `TypedTerminal`, `_TRANSITION_GATES`,
  and the module-level `advance_gate` import anchor (R-anchor the new import on an
  existing top-level symbol if `_parse_patches` requires it).
- verification_command: `python -c "import ngv2.gate_executor"`.

TASK 3 — `c7-seams-env-dispatch-impl` (deps: [c7-gate-bridge-impl]).
files_touched: `ngv2/conductor_seams.py`. WHOLE_FILE_DRIFT HOTSPOT (~440 lines, 4-6
symbols) — MANDATORY explicit per-symbol patch recipe; R-anchor new helpers.
- Add an `env_phase` seam to the dict returned by `build_default_seams` (line 255). The
  seam is a closure `env_phase(state) -> {'advance':bool,'terminal':str,'artifact':dict|None}`
  that, for the current `state['phase']` in ENV_PHASE_ORDER:
  (a) calls the matching cP PRODUCER over `ctx['repo']`/`ctx['target_path']` using
      DEFAULT (real) producer seams (NO mock `*_fn`); e.g. detect ->
      `produce_detect_input(repo, pinned_commit=<real head>, head_commit=<real head>)`;
  (b) calls the matching `fsm_*` handler with the producer dict + the PRIOR phase's
      persisted env artifact (read from `state['env_artifacts'][<prev_phase>]`);
  (c) persists the returned content-hashed `artifact` into
      `state['env_artifacts'][<phase>]` via the db save (thread through `persist`);
  (d) returns the handler's `{'advance','terminal','artifact'}`.
- Thread per-state artifact + evidence: extend `_PHASE_COUNT_KEY`/`persist` so an env
  phase records its artifact, and extend `build_evidence` so that for an env from_phase
  it emits `{'env_artifact': state['env_artifacts'][from_phase]}` (the key task 2's
  gate consumes). The REAL head commit: resolve once (e.g. read `.git/HEAD` ->
  packed/loose ref, or shell out to `git rev-parse HEAD` via a default seam) and use it
  as BOTH pinned_commit and head_commit so detect's `sha_mismatch` guard passes.
- Build helpers are NEW top-level symbols — R-anchor each on an existing top-level
  symbol in conductor_seams (e.g. anchor on `_count_real` or `build_default_seams`).
- __JANUSMASK_PATCHES__: one entry per modified/added top-level symbol
  (`build_default_seams`, the new `env_phase` factory helper(s), `persist` if hoisted,
  the new producer-dispatch + handler-dispatch helpers). Note `persist`/`build_evidence`
  are nested closures inside `build_default_seams` — modify them via the
  `build_default_seams` symbol patch (they are not top-level), and put any genuinely
  new top-level helper as its own R-anchored entry.
- verification_command: `python -c "from ngv2.conductor_seams import build_default_seams; assert callable(build_default_seams)"`.

TASK 4 — `c7-conductor-planner-impl` (deps: [c7-seams-env-dispatch-impl]).
files_touched: `ngv2/hunt_conductor.py`, `ngv2/transition_planner.py`.
- `hunt_conductor.run_conductor_step`: add a `run_env_phase` action branch (mirror
  `spawn_stage`/`apply_gates`). On the planned action `run_env_phase` it calls
  `seams['env_phase'](state)`; on `advance==True` it calls `seams['advance'](session_id)`
  and returns `{'step':'run_env_phase','phase':state['phase'],'to':<next>}`; on
  `advance==False` (terminal) it returns `{'step':'blocked','blocked_by':<terminal>}`
  (fail-closed; `'blocked'` is terminal so the loop halts on a refused safe target).
- `transition_planner.plan_next_action`: add env dispatch — for `phase in
  ENV_PHASE_ORDER` return `{'action':'run_env_phase','target_phase':<next phase in
  PHASE_ORDER>,'reason':...}` (import `ENV_PHASE_ORDER` from `ngv2.fsm_evidence`). This
  must precede the `worker_phases` loop. Keep `plan_next_action` pure/deterministic.
- __JANUSMASK_PATCHES__: `run_conductor_step` (hunt_conductor); `plan_next_action` +
  the `ENV_PHASE_ORDER` import anchor (transition_planner).
- verification_command: `python -c "import ngv2.hunt_conductor, ngv2.transition_planner"`.

TASK 5 — `c7-initial-phase-flip-impl` (deps: [c7-conductor-planner-impl]).
files_touched: `ngv2/run_hunt.py`.
- `_INITIAL_PHASE = 'detect'` (line 61). Update `_ensure_seeded` (line 63) so the seed
  uses `_INITIAL_PHASE` (already does) and seeds an empty `env_artifacts: {}` dict +
  keeps `findings/pocs/reports/artifacts`. Update the docstring (lines 64-72 / 81)
  to say the session starts at `detect`, traverses the env-FSM, then hunts.
- __JANUSMASK_PATCHES__: `_INITIAL_PHASE` (module-level constant — R-anchor on
  `_ensure_seeded` or `main` if a bare reassignment needs an anchor), `_ensure_seeded`.
- verification_command: `python -c "import ngv2.run_hunt"`.

TASK 6 — `c7-fsm-live-integration-oracle` (deps: [c7-initial-phase-flip-impl]).
`meta_task_type: test_authoring`, `mutation_target: ngv2.conductor_seams`,
files_touched: `["tests/ngv2/test_c7_fsm_live_integration.py"]`.
THE CALL-PATH ORACLE. Ordinary Python test source (NOT a manifest). Imports generated
code via `importlib` (`importlib.import_module('ngv2.run_hunt')` etc.; exec/eval/
__import__ are AST-banned). Build a hermetic `tmp_path` repo:
- copy `_e2e_run/target/vuln_service.py` into `tmp_path/repo/` (CWE-78 fixture; stdlib
  `os` only) + a package `__init__.py`;
- a `pyproject.toml` (or `requirements.txt`) so detect finds a build file + resolves a
  python bin, and an EMPTY/stdlib-only lockfile so provision's smoke import + jailed
  install succeed WITHOUT host-network pip (sidesteps P0.2 installer);
- `git init` + one commit so a real `head_commit` exists (pin == head);
- a seeded `prior_findings` finding carrying a `reach_input` whose sink is the real
  CWE-78 sink (`sink_present=True`, `sink_reachable='reachable'`, optional
  `benign_ping_reached=True`) so reachability advances.
Drive REAL `run_hunt(session_id, repo, target_path, db_path, output_dir, max_steps=...)`
over this fixture (its own SessionDB or an injected db). The oracle asserts (the 4
NON-VACUOUS, fail-closed, import-reachability-DISQUALIFIED checks):
1. PER-STATE CONTENT-HASH ARTIFACT PERSISTED: after the run, the session row's
   `env_artifacts` has all 6 env phases; each artifact's `content_hash` RECOMPUTES via
   `fsm_evidence.phase_artifact_hash(artifact_minus_hash)` AND each passes
   `fsm_evidence.advance_gate(artifact)['advance'] is True` (proves the handler RAN and
   the live gate consumed its hash).
2. TAMPER => REFUSAL: take one persisted env artifact, mutate a `details` field WITHOUT
   recomputing the hash, feed it as the prev artifact and assert `advance_gate` =>
   `advance False` / a typed terminal (and that the gate-bridge `run_gates` over a
   tampered `env_artifact` returns `advance=False`). NON-NEGOTIABLE — else A4-G3/X5 is
   vacuous.
3. RUNTIME TRACE ORDER: the `run_hunt` result `steps` (runtime trace, NOT imports)
   contains a `run_env_phase` step for EACH of the 6 env states IN ENV_PHASE_ORDER and
   ALL 6 appear BEFORE the first `hunt`/`spawned`/`apply_gates` step. (Disqualifies any
   "the symbol is importable" check — assert on the actual step sequence.)
4. REAL-DERIVED, NOT LITERALS (anti answer-key-leak): assert the detect artifact's
   `resolved_python_bin` is the REAL resolved interpreter (e.g. matches the fixture's
   pyproject/`.python-version`-derived bin, non-None), `build_files` came from the
   producer's real `os.walk` over the fixture (contains the fixture's actual build
   file relpath), and `head_commit` equals the REAL `git rev-parse HEAD` of the fixture
   repo (NOT a hardcoded literal). Use a NONCE in the fixture (e.g. a uniquely-named
   build file or a sentinel package dir) and assert it appears in the real-derived
   producer output — refute any hardcoded constant.
regression_tests >= 2 (e.g. a SAFE fixture — vuln sink patched / `reach_input.
sink_present=False` — is REFUSED at `reachability_probe` with a typed terminal and the
trace ends in `blocked`, never reaching `hunt`; and a missing-build-file fixture is
refused at `detect` with `no_build_system`).
verification_command (bare, no `cd`):
`python -m pytest tests/ngv2/test_c7_fsm_live_integration.py -q`.

# Interfaces

- New seam key `env_phase(state) -> {'advance':bool,'terminal':str,'artifact':dict|None}`
  in `build_default_seams`'s return dict — the in-process producer->handler dispatcher
  (DECISION (i)). Calls cP producers with DEFAULT real seams, then the matching fsm_*
  handler with `(producer_dict, prev_env_artifact)`, persists the content-hashed
  artifact into `state['env_artifacts'][phase]`.
- New planner action `'run_env_phase'` (target_phase = next PHASE_ORDER phase) returned
  by `plan_next_action` for any `phase in ENV_PHASE_ORDER`.
- New conductor dispatch branch in `run_conductor_step` for `action=='run_env_phase'`:
  advance on success, `{'step':'blocked','blocked_by':<terminal>}` on a typed terminal
  (fail-closed; terminal halts the loop on a refused target).
- New gate-bridge: `_TRANSITION_GATES` entries for the 6 consecutive env edges, each
  calling `fsm_evidence.advance_gate(ev['env_artifact'])` and mapping `advance` ->
  `may_confirm`; 5 new `TypedTerminal` members.
- `fsm_evidence.PHASE_ORDER` is THE single source; `session_api.PHASE_ORDER`,
  `session_api._PHASES`, `state_machine.LIFECYCLE_PHASES` DERIVE from it (no re-literal).
- `run_hunt._INITIAL_PHASE = 'detect'`; the seeded session carries `env_artifacts: {}`.

# Required plan shape

SIX tasks, ONE plan, strictly serial: 1 -> 2 -> 3 -> 4 -> 5 -> 6. NOT an epic. Do not
add or drop a task (`required_task_ids` in frontmatter lists all six). Tasks 1-5:
`meta_task_type: validation`, `priority: high`, `partial_edit: true`, explicit
`__JANUSMASK_PATCHES__` per modified top-level symbol (R-anchor any NEW top-level
symbol). Task 6: `meta_task_type: test_authoring`, `mutation_target:
ngv2.conductor_seams`, ordinary test source via importlib, the 4 call-path assertions +
>= 2 regression tests. Every task's non_goals contains `integration`. All
working_dir = `/home/xnihil0zer0/NobleGreedv2`. `ngv2/**` is external (NOT sensitive →
no decision file; NOT `harness_self_fix`). Dep edges:
`c7-gate-bridge-impl` <- `c7-phase-order-unify-impl`;
`c7-seams-env-dispatch-impl` <- `c7-gate-bridge-impl`;
`c7-conductor-planner-impl` <- `c7-seams-env-dispatch-impl`;
`c7-initial-phase-flip-impl` <- `c7-conductor-planner-impl`;
`c7-fsm-live-integration-oracle` <- `c7-initial-phase-flip-impl`.
