---
working_dir: "/home/xnihil0zer0/NobleGreedv2"
priority: high
required_task_ids:
  - p21-cp-health-producer-impl
  - p21-cp-health-producer-oracle
interfaces: "P2.1 env-readiness-FSM PRODUCER layer, child cP (`health_producer`) — the PIPELINE-FIRST attempt at the GENUINE IMPURE LONG POLE #1 (service-start + loopback bind + health poll). The seven pure handlers (c0-c6) already landed in NGv2 as pure gates over input-dicts; the first producer (`jail_producer`) landed clean and fuzz-covered, proving the quarantine pattern (inject the impure call behind a seam → the producer body is a pure deterministic transform over injected results → meta_task_type validation + hermetic importlib oracle, real side effect covered by the auto-applied smoke gate). This brief APPLIES THE SAME PROVEN PATTERN to the genuinely-impure service-start case. New standalone flat module `ngv2/health_producer.py` exposes `produce_health_input(jail_artifact, provision_artifact, *, import_fn=..., start_fn=..., probe_fn=...) -> dict`. The THREE impure side effects — (a) `import <target_pkg>` inside the env, (b) start the service subprocess (`python -m <app>`/detected entrypoint), (c) poll `socket.connect_ex(('127.0.0.1', <port>))` + hit a health route — are EACH QUARANTINED behind an injectable seam parameter (`import_fn`, `start_fn`, `probe_fn`) with REAL defaults, so the producer body is a PURE, deterministic transform over `(import_fn() bool, start_fn(...) handle, probe_fn(...) (bound, health_ok) tuple)`. Its output dict carries EXACTLY the keys the LANDED c4 handler `ngv2/fsm_health_probe.py::health_probe` reads — `import_ok`, `is_service`, `service_bound`, `bound_addr`, `health_route_ok`, `start_cmd` — so `health_probe(produce_health_input(...), prev_artifact=jail_artifact)` ADVANCES. Fail-closed: `import_fn` raising/False → `import_ok=False` → c4 refuses with `service_no_bind`; a service target whose `probe_fn` never binds → `service_bound=False` → c4 refuses with `service_no_bind`; an absent/None/tampered `jail_artifact` → the c4 handler's `advance_gate` rejects → no advance. PIPELINE-FIRST: this is the centerpiece test of the owner's directive — attempt the supposed hand-edit (impure service-start) THROUGH the pipeline ONCE before declaring it impossible; if a specific impurity CANNOT be expressed behind a seam and the build records a `fuzz_error`, that documented failure is the escalation trigger (do NOT pre-assume hand-edit). PARALLEL-SAFE: edits ONLY its two NEW files (`ngv2/health_producer.py` + its oracle) — DISJOINT from the c0-c6 handlers and from the landed `jail_producer`; the LIVE wiring into run_hunt is the SEPARATE c7 integration leaf (deferred). WIRE-UP: this producer reaches the `python -m ngv2.run_hunt` LIVE_ROOT by feeding the on-chain c4 handler `fsm_health_probe.health_probe` (which consumes `ngv2.fsm_evidence`, imported by `transition_planner`/`gate_executor` on the conductor's live chain); the full live call-in is DEFERRED to c7."
---

# Title
P2.1-cP — env-FSM health_probe PRODUCER: a pure, side-effect-quarantined `produce_health_input()` that constructs the `health_input` dict the LANDED c4 `fsm_health_probe` handler consumes and advances (PIPELINE-FIRST attempt at the genuine impure long pole: service-start + loopback bind + health poll)

# Scope
Land the cP health_probe PRODUCER of the P2.1 env-readiness FSM at `/home/xnihil0zer0/NobleGreedv2`
(READ each named file first). ONE new flat module, ONE behavior, NO live-FSM mutation, NO new subpackage.
This is the PIPELINE-FIRST attempt at the GENUINE IMPURE LONG POLE: the first producer whose construction involves
a real subprocess service-start, a loopback bind, and a health poll — each QUARANTINED behind an injectable seam so
the producer body is a pure transform the factory can build and hermetically oracle, exactly as the landed
`jail_producer` proved for the bwrap-PATH side effect.

1. NEW flat module `ngv2/health_producer.py` (stdlib only at module top; NO new subpackage, NO module-level side
   effects). It defines:
   - `produce_health_input(jail_artifact, provision_artifact, *, import_fn=<real default>, start_fn=<real default>, probe_fn=<real default>) -> dict`
     — the health_probe PRODUCER. It CONSTRUCTS the `health_input` dict that the LANDED c4 handler
     `ngv2.fsm_health_probe.health_probe` consumes. The THREE side effects are EACH QUARANTINED behind an injectable
     seam with a REAL default; the body is a PURE, deterministic transform over their returns. Behavior:
       * `import_ok`: call `import_fn()` (real default does the in-env target import); on True → `import_ok=True`;
         if `import_fn()` returns False OR RAISES → fail closed: `import_ok=False` (caught), and return immediately
         with `is_service` set (no service work attempted) so the c4 handler refuses with `service_no_bind`.
       * `is_service`: derive whether the target is a runnable service vs a library. For a library (non-service)
         target, `is_service=False` and NO bind is required — `import_ok=True` is sufficient for c4 to advance.
       * For a SERVICE target (`is_service=True`): call `start_fn(...)` (real default starts the service subprocess
         `python -m <app>`/detected entrypoint and returns a handle) then `probe_fn(...)` (real default polls
         `socket.connect_ex(('127.0.0.1', <port>))` for the bind and hits the health route) returning a
         `(service_bound: bool, health_route_ok: bool)` tuple. Set `service_bound`/`health_route_ok` from that tuple;
         set `bound_addr` (e.g. `'127.0.0.1:<port>'`) and `start_cmd` (the launch argv list) from the start handle.
         If `start_fn`/`probe_fn` raise → fail closed: `service_bound=False`, `health_route_ok=False`.
       * Return EXACTLY the dict the c4 handler reads (omit service-only keys for the library path):
         service path → `{'import_ok': <bool>, 'is_service': True, 'service_bound': <bool>, 'health_route_ok': <bool>, 'bound_addr': <str>, 'start_cmd': <list>}`;
         library path → `{'import_ok': <bool>, 'is_service': False}`. These keys are the EXACT keys
         `ngv2.fsm_health_probe.health_probe` reads (`health_input['import_ok']`, `health_input['is_service']`, and —
         when `is_service` — `health_input['service_bound']`, `health_input['health_route_ok']`; its success artifact
         `details` additionally collects `bound_addr` and `start_cmd` when present) — CONFIRMED by reading the landed
         handler (lines 26-46): the gate-deciding keys are `import_ok`, `is_service`, `service_bound`,
         `health_route_ok`; the `details`-collected keys are the six `('import_ok','is_service','service_bound','bound_addr','health_route_ok','start_cmd')`.
     PURE + TOTAL over the injected seams: with fixed `import_fn`/`start_fn`/`probe_fn` returns, identical args yield
     identical output. The producer does NOT itself adjudicate the prior `jail_artifact` — it is PASSED THROUGH to the
     c4 handler as `prev_artifact`, which delegates the fail-closed prior-evidence check to
     `ngv2.fsm_evidence.advance_gate`. (`provision_artifact` is an additional optional prior the c4 handler may also
     gate; the producer carries it through but does not read it as a field.)

# Inputs
- `ngv2/fsm_health_probe.py` (READ-ONLY, LANDED c4) — `health_probe(jail_artifact: dict, provision_artifact: dict|None=None, health_input: dict|None=None) -> {'advance','terminal','artifact'}`.
  It calls `advance_gate(jail_artifact)` FIRST (and `advance_gate(provision_artifact)` if given). It reads
  `health_input['import_ok']` (must be a `bool` and truthy), `health_input['is_service']` (must be a `bool`); when
  `is_service` is True it ALSO requires `health_input['service_bound']` and `health_input['health_route_ok']` (both
  `bool` and truthy). Its success artifact `details` collects from
  `('import_ok','is_service','service_bound','bound_addr','health_route_ok','start_cmd')`. Typed terminal on ANY
  refusal of the health_input itself (missing/non-bool/false key, non-dict, import not ok, service not bound) =
  `'service_no_bind'`; on a bad prior it returns the `advance_gate` terminal (`'missing_evidence'`/`'hash_mismatch'`).
  The producer's output dict MUST be exactly this `health_input` shape.
- `ngv2/fsm_evidence.py` (READ-ONLY, LANDED c0) — `phase_artifact_hash(d)`, `advance_gate(prev) -> {'advance','terminal'}`
  (the prior-evidence validator the c4 handler delegates to); `ENV_PHASE_ORDER` includes
  `('detect','provision','jail_build','health_probe',...)`. The oracle builds a VALID round-tripping `jail_artifact`
  (phase `'jail_build'` shape with `content_hash`) via `phase_artifact_hash` to drive the positive case.
- `ngv2/jail_producer.py` + `tests/ngv2/test_jail_producer.py` (READ-ONLY, JUST-LANDED PROVEN PATTERN) — MIRROR this
  seam-injection + hermetic-importlib-oracle structure exactly (whole-file manifest impl; `importlib.import_module`
  in the oracle; `tmp_path` fixtures; round-tripping prior via `phase_artifact_hash`; load-bearing negatives).
- `ngv2/loopback_listener.py`, `ngv2/poc_runner_live.py` (READ-ONLY) — the real bind/subprocess idioms the REAL
  DEFAULT seams should use: `socket.connect_ex(('127.0.0.1', port))` for the bind probe, a daemon-thread/subprocess
  launch for the service start. The oracle injects FAKES and NEVER touches a real subprocess/socket/clock.
- `ngv2/run_hunt.py` (READ-ONLY) — the `python -m ngv2.run_hunt` LIVE_ROOT; the wire-up chain target (reached via
  the on-chain c4 handler; full live call-in deferred to c7).

# Non-Goals
Integration is out of scope for the implementation task (the literal word `integration` MUST appear here AND in the
implementation task's `non_goals` to excuse the integration-test requirement). The LIVE wiring of
`produce_health_input` into `run_hunt`/the conductor is the SEPARATE c7 integration leaf — DEFERRED. The OUTBOUND-NET
service startup (a real `python -m <app>` that needs egress) is OUT OF SCOPE — that is the P4.3 VM tier (deferred);
this producer's loopback-bind default works in the existing bwrap `--unshare-net` jail (loopback is up). This
producer's REAL `import`/`start`/`probe` seams are exercised ONCE by the `smoke_gated` bypass (the spec mentions
NGv2 + bind/socket, so an `ngv2/`-touching impl auto-routes to `smoke_gated`), NOT by the differential oracle — the
oracle injects all three seams and never touches a real subprocess/clock/socket; the real seams are smoke-gate-covered,
NOT differential-fuzzed. Do NOT edit `ngv2/fsm_health_probe.py`, `ngv2/fsm_evidence.py`, `ngv2/jail_producer.py`,
`ngv2/loopback_listener.py`, `ngv2/poc_runner_live.py`, `ngv2/transition_planner.py`, `ngv2/gate_executor.py`, or
`ngv2/conductor_seams.py`. Do NOT insert the producer into the live `ENV_PHASE_ORDER`, `transition_planner`,
`gate_executor`, `stage_command_map`, or `conductor_seams` — that live-FSM wiring is c7 (so cP stays file-disjoint and
parallel-safe; the module-level `orphan_unwired` gate no-ops on this external `ngv2/**` build and is expected to
pass/no-op). Do NOT create a new subpackage (one FLAT file). `harness_self_fix` is NOT applicable (these are `ngv2/**`
files in the EXTERNAL repo, not `harness/**`). Do NOT add a `TypedTerminal` enum member (the c4 handler already owns
the `service_no_bind` terminal as a plain string on its own artifact).

# Deliverables
- `ngv2/health_producer.py`: `produce_health_input(jail_artifact, provision_artifact, *, import_fn=<real default>, start_fn=<real default>, probe_fn=<real default>)`
  — pure over the THREE injected seams; quarantines the import/service-start/bind-probe side effects; constructs the
  `health_input` dict the LANDED c4 `fsm_health_probe.health_probe` consumes; fail-closed
  (`import_fn` False/raises → `import_ok=False` → c4 refuses `service_no_bind`; service never binds → `service_bound=False`
  → c4 refuses `service_no_bind`).
- A NEW pipeline-authored RED oracle `tests/ngv2/test_health_producer.py` (the `test_authoring` task) — RED now
  (module absent), GREEN after.

# Required plan shape
- EXACTLY ONE implementation task + ONE `test_authoring` oracle task (a RED-PAIR). These EXACT task_ids
  (pinned via `required_task_ids`):
  - `p21-cp-health-producer-impl` — meta_task_type: `validation` (a pure transform over three injected seams; an
    `ngv2/`-touching impl that mentions bind/socket auto-routes to the `smoke_gated` bypass which covers the real
    import/start/probe once — do NOT use `state_machine`/stateful_fuzz). OMIT `mutation_target`. files_touched:
    EXACTLY `ngv2/health_producer.py` (ONE new flat file). `dependencies: ['p21-cp-health-producer-oracle']`.
    `non_goals` MUST contain the literal word `integration`. `verification_command` MUST substring-name the
    oracle's authored test file `tests/ngv2/test_health_producer.py`.
    SUBMISSION SHAPE: a SINGLE brand-new file -> a whole-file `__JANUSMASK_MANIFEST__` with the ONE key
    `ngv2/health_producer.py` mapping to the complete module source (do NOT mix a manifest with a
    `__JANUSMASK_PATCHES__` block — rejected `manifest_incomplete`). No `# JANUSMASK_DELETE` directive needed.
  - `p21-cp-health-producer-oracle` — meta_task_type: `test_authoring`; files_touched: EXACTLY
    `tests/ngv2/test_health_producer.py`; mutation_target: `ngv2.health_producer`; `dependencies: []`
    (authored RED first).
- RED-PAIR ordering (correct direction): the oracle task has `dependencies: []`; the impl `depends on` the oracle
  (`dependencies: ['p21-cp-health-producer-oracle']`); the oracle imports the not-yet-existing `ngv2.health_producer`
  so it is a genuine red-pair (else the planner could drop the standalone oracle).
- verification_command (BARE, selects >=1 real test, never pytest exit 5; NO `cd`):
  `python -m pytest tests/ngv2/test_health_producer.py -q`
- Wire-up / LIVE_ROOT: `ngv2.health_producer` produces the `health_input` the on-chain c4 handler
  `ngv2.fsm_health_probe.health_probe` consumes; that handler imports `ngv2.fsm_evidence`, imported by
  `ngv2.transition_planner` + `ngv2.gate_executor`, reached by `ngv2.run_hunt.run_hunt` — so the producer participates
  in the live `python -m ngv2.run_hunt` chain by feeding the on-chain handler. The INBOUND live caller threading
  `produce_health_input` into the running conductor is added by the DEFERRED c7 integration leaf (the `orphan_unwired`
  gate is default-OFF / no-ops externally, so this does not block the parallel build; the oracle asserts the
  producer->handler->gate contract below).

## The pre-committed oracle (the `test_authoring` task) MUST assert (RED-now -> GREEN-after, non-vacuous, ungameable):
Import the generated `ngv2.health_producer` via `importlib` (`importlib.import_module` — `exec`/`eval`/`__import__`
are AST-banned). NO real subprocess/clock/socket — the import/service-start/bind-probe are ALL INJECTED via
`import_fn`/`start_fn`/`probe_fn`. Build fixtures in-test. Build a VALID round-tripping `jail_artifact` via
`ngv2.fsm_evidence.phase_artifact_hash` (phase `'jail_build'`, status `'success'`, with `content_hash`).
1. CONTRACT / reachability (non-vacuous): with `import_fn=lambda: True`, `start_fn=<fake handle returning bound_addr/start_cmd>`,
   `probe_fn=lambda *a, **k: (True, True)`, and a valid `jail_artifact`, `produce_health_input(...)` for a SERVICE target
   returns a dict that carries `import_ok is True`, `is_service is True`, `service_bound is True`, `health_route_ok is True`,
   and non-empty `bound_addr` / `start_cmd`. RED today: module absent.
2. POSITIVE / producer->handler->gate, SERVICE target (X1): feed the produced dict to the LANDED handler —
   `fsm_health_probe.health_probe(<valid jail_artifact>, health_input=produce_health_input(jail_artifact=<valid>, provision_artifact=None, import_fn=lambda: True, start_fn=<fake handle>, probe_fn=lambda *a, **k: (True, True)))`
   — and assert `result['advance'] is True`, `result['terminal'] == ''`, `result['artifact'] is not None`, and the
   artifact `details` carries `service_bound True` / `health_route_ok True` (the full producer->handler->gate
   contract advances). NOTE: the handler's signature is `health_probe(jail_artifact, provision_artifact=None, health_input=None)`
   — pass the produced dict as the `health_input` kwarg and the valid `jail_artifact` as the first positional
   prev-evidence arg (CONFIRM the exact call shape from the landed handler source).
3. POSITIVE / LIBRARY (non-service) target: `import_fn=lambda: True` with the target classified non-service →
   `produce_health_input(...)` returns `import_ok is True`, `is_service is False`, and feeding it to the handler
   ADVANCES (`result['advance'] is True`) WITHOUT requiring any bind — proving the non-service path needs only
   `import_ok`.
4. FAIL-CLOSED NEGATIVES (load-bearing, MANDATORY): (a) SERVICE NEVER BINDS: `import_fn=lambda: True`, a SERVICE
   target, `probe_fn=lambda *a, **k: (False, False)` -> `produce_health_input` returns `service_bound is False`;
   feeding THAT to the handler yields `advance is False` and `terminal == 'service_no_bind'` with `artifact is None`.
   (b) IMPORT FAILS: `import_fn=lambda: (_ for _ in ()).throw(ImportError())` (or `lambda: False`) ->
   `produce_health_input` returns `import_ok is False`; feeding that to the handler yields `advance is False` and
   `terminal == 'service_no_bind'`. (c) ABSENT/FORGED PRIOR: with all seams positive (service binds) but the
   prev-evidence `jail_artifact=None` -> the handler refuses (`advance is False`); a `{}` prior -> refuses; a TAMPERED
   prior (a valid `jail_artifact` whose `content_hash` is then mutated) -> refuses (`terminal in ('missing_evidence','hash_mismatch')`).
   The POSITIVE control (step 2, same produced dict WITH a valid prior) advances — so the negative is non-vacuous
   (it is the absent/forged prior, not the produced dict, that blocks).
5. DETERMINISM / purity (seams fully quarantined): with FIXED `import_fn`/`start_fn`/`probe_fn`, two calls to
   `produce_health_input` with identical args yield byte-identical `json.dumps(result, sort_keys=True, default=str)`,
   AND a call with all three seams injected touches NO real socket/process/clock — proving the side effects are fully
   quarantined behind the seams and the body is a pure transform.
- regression_tests >= 2 (the service-never-binds `service_no_bind` negative and the absent/forged-prior refusal are
  distinct, non-vacuous tests).
