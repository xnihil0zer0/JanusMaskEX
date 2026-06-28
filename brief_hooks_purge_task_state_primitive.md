---
working_dir: "/home/xnihil0zer0/AI-Data/JanusMaskEX"
priority: P1
meta_task_type: harness_self_fix
operator_decision_required: true
auto_approve_requested: true
required_task_ids:
  - purge-task-state-primitive-oracle
  - purge-task-state-primitive-impl
interfaces: >
  EDIT EXACTLY ONE existing file: harness/state_reconciler.py. Add a NEW top-level helper
  `purge_task_state(root, task_id, *, config=None, now=None) -> dict` that ENUMERATES a single
  canonical, source-of-truth list of a task's per-task sidecar paths and removes them idempotently —
  REPLACING today's scattered, hand-cleared, per-re-dispatch cleanup with one manifest-driven primitive.
  It MUST be FAIL-CLOSED on three invariants: (1) REFUSE (no-op + typed reason) when the task's running
  pidfile is live (reuse the EXISTING `task_id_has_live_pidfile`/`_running_dir` liveness probes in this
  module — never hand-roll a new one), so a purge can never race a live worker; (2) NEVER remove or touch
  any `brief_hooks_*.md` or any unclassifiable/non-sidecar path (classify-and-fail-closed — the path must
  match an EXACT, known per-task sidecar template or it is skipped); (3) be a strict no-op gated OFF by
  default behind a NEW `autowork.purge_task_state.enabled` config flag (default false), so it cannot
  regress prod until proven. Today there is NO single per-task purge primitive: the sidecars are written
  by ~8 scattered call sites (state/output/<tid>.{patches,files,fallback.*}.json at orchestrator.py:1774-
  1846/2470-2471, state/sessions/*_<tid>_submission.json at orchestrator.py:1274/1485, state/tasks/
  processed/<tid>.json at orchestrator.py:1249-2092, state/tasks/test_results/<tid>* at
  orchestrator_worker.py:948-953, logs/fuzz_results/<tid>* at autowork_daemon.py:540, running/<tid>.{pid,
  slot} at autowork_daemon.py:1073/1136, blocked/<tid>.{json,retry.json,exhausted} at
  autowork_daemon.py:745 + orchestrator_worker.py:445/525 + orchestrator.py:1952, queued tasks/<tid>.json
  at autowork_daemon.py:1185) and the ONLY existing fragment (selfheal.py:379/407) clears blocked sidecars
  ONLY. Operators clear the full set BY HAND on a re-dispatch (stale-sidecar-precedence). This brief
  centralizes that into one idempotent, liveness-guarded, fail-closed primitive.
---

# Title
state_reconciler: manifest-driven, liveness-guarded `purge_task_state` primitive (default-OFF)

# Scope
EDIT the SINGLE EXISTING file `harness/state_reconciler.py` (READ it first; it is the canonical
reconciler module and is auto-approvable `harness/**` — it is NOT in `_NEVER_AUTO_APPROVE`, so this
`harness_self_fix` is auto-approve-eligible WITH NO decision file, though a decision is requested for the
program). SINGLE FILE. Emit a `__JANUSMASK_PATCHES__` payload (NOT a manifest block).

This brief ADDS ONE new top-level helper and a tiny set of supporting top-level helpers in the SAME
file. It EXTENDS the reconciler's existing per-task primitives (`task_id_has_live_pidfile`, `pid_is_live`,
`_running_dir`, `state_reconcile_lock`, the watchdog truthy/config readers) — it does NOT reinvent any of
them, and it does NOT change any existing function's behavior. With the new flag OFF (the default and the
config's absence), the module's behavior is byte-for-byte preserved.

# Inputs
READ `harness/state_reconciler.py`. VERIFIED current facts (source of truth — do NOT change beyond the
additive helper(s) below):
- Liveness probes ALREADY in this module to REUSE (do NOT duplicate):
  `task_id_has_live_pidfile(running_dir, task_id) -> bool` (~line 92, parses each `*.pid` stem to its
  EXACT encoded task id and checks `os.kill(pid,0)`; substring-proof — `t1` never matches `t12`),
  `pid_is_live(pid) -> bool` (~line 44), `_running_dir(root) -> Path` (~line 1529, returns
  `<root>/state/control/autowork/running`), `_pidfile_task_id(stem)` (~line 65).
- The shared serializing lock: `state_reconcile_lock(state_dir)` (~line 590) — the ONE dedicated reconcile
  lock; it is re-entrant via a thread-local refcount. REUSE it to serialize the purge's unlinks; NEVER
  acquire `git_commit.lock`.
- The default-OFF config-reader PATTERN to mirror: `_watchdog_enabled(config)` (~line 1186) +
  `_watchdog_truthy(val)` (~line 1152) + `_watchdog_cfg_section(config)` (~line 1167). They tolerate a
  `None`/non-dict `config`, accept a bare/`autowork`-nested shape, and default OFF. Build the analogous
  `autowork.purge_task_state` reader the same way (reuse `_watchdog_truthy` for truthiness).
- The CANONICAL per-task sidecar set (VERIFIED writer sites — this IS the manifest the helper enumerates):
  * `state/output/<tid>.patches.json`            (orchestrator.py:2470, 1846)
  * `state/output/<tid>.files.json`              (orchestrator.py:2471, 1834)
  * `state/output/<tid>.fallback.py`             (orchestrator.py:1774)
  * `state/output/<tid>.fallback.patches.json`   (orchestrator.py:1780)
  * `state/output/<tid>.fallback.files.json`     (orchestrator.py:1781)
  * `state/sessions/*_<tid>_submission.json`     (orchestrator.py:1274, glob — written at :1485)
  * `state/tasks/<tid>.json`                     (queued sidecar; autowork_daemon.py:1185)
  * `state/tasks/processed/<tid>.json`           (autowork_daemon.py:2197; orchestrator.py:1861-2092)
  * `state/tasks/test_results/<tid>*`            (orchestrator_worker.py:948-953, glob)
  * `logs/fuzz_results/<tid>*`                   (autowork_daemon.py:540, glob)
  * `state/control/autowork/running/<tid>.pid`   (autowork_daemon.py:1073)
  * `state/control/autowork/running/<tid>.slot`  (autowork_daemon.py:1136)
  * `state/tasks/blocked/<tid>.json`             (autowork_daemon.py:745)
  * `state/tasks/blocked/<tid>.retry.json`       (orchestrator_worker.py:445/525; orchestrator.py:1952)
  * `state/tasks/blocked/<tid>.exhausted`        (orchestrator.py + autowork_daemon.py:2024)
- The existing PARTIAL fragment to SUPERSEDE conceptually (do NOT edit it here): `harness/selfheal.py:379`
  / `:407` clears ONLY `blocked/{tid}.json|.retry.json|.exhausted`. The new primitive covers the FULL set.
- IMPORTANT — the `<tid>.pid` and `<tid>.slot` files under the running dir ARE a sidecar AND the liveness
  signal. The liveness REFUSE check (below) MUST be evaluated BEFORE any unlink and gates the WHOLE purge:
  if a live pidfile exists for the task, the entire purge is refused (the pidfile is NOT removed). The pid/
  slot files are only ever removed on the purge path AFTER the task is confirmed NOT live.

# Non-Goals
This leaf does NOT edit any `_NEVER_AUTO_APPROVE` file (notably `harness/orchestrator.py`,
`harness/orchestrator_worker.py`, `harness/autowork_daemon.py`, `harness/git_integration.py`,
`harness/selfheal.py`, `harness/agent_jail.py`). It does NOT auto-fire on task re-open (that
re-open-path auto-purge is a SEPARATE, owner-gated follow-up — see the companion brief
`brief_hooks_purge_on_reopen_autofire.md`); it adds only the CALLABLE primitive, default-OFF. It does NOT
re-point/reset the `janusmask/work` ref (that touches trust-core `git_integration.py` and needs a staged
operator decision file — see the companion brief). It does NOT remove the existing
`harness/selfheal.py:379/407` blocked-sidecar fragment. It does NOT flip `harness/config.yaml` (the impl
must tolerate the flag's absence with the default-OFF reader; a follow-up config-flip is owner-gated). It
does NOT thread the primitive into any live sweep / dispatch path. It does NOT archive/move/delete any
`brief_hooks_*.md` or any path that is not an EXACT known per-task sidecar (fail-closed). Integration test
coverage is out of scope for the implementation task (the impl extends an already-wired live module —
`harness/state_reconciler.py` is reachable from the live root `autowork_daemon.py` — rather than creating
a new module; the literal word `integration` appears here to excuse the integration-test requirement).

# Deliverables
- A new top-level `purge_task_state(root, task_id, *, config=None, now=None) -> dict` in
  `harness/state_reconciler.py` that:
  (1) ENUMERATES the single canonical sidecar manifest above for `task_id` (a dedicated helper, e.g.
      `_task_sidecar_paths(root, task_id) -> list[Path]`, returns the EXACT path list including resolving
      the two globs `sessions/*_<tid>_submission.json` and `test_results/<tid>*` and `fuzz_results/<tid>*`
      to concrete matches; the manifest is the ONE source of truth);
  (2) is GATED OFF by default — when `autowork.purge_task_state.enabled` is not truthy (incl. `config` is
      `None`/missing), it performs NO unlink and returns a clean refusal summary
      (e.g. `{"enabled": False, "refused": True, "reason": "disabled", "removed": [], "skipped": []}`);
  (3) when enabled, REFUSES the WHOLE purge (no unlink at all) iff the task's running pidfile is LIVE
      (`task_id_has_live_pidfile(_running_dir(root), task_id)` is True), returning a typed reason
      (e.g. `{"enabled": True, "refused": True, "reason": "live_worker", "removed": [], "skipped": []}`);
  (4) when enabled AND not live, removes each enumerated sidecar idempotently (a missing path is a no-op
      success — fail-closed per-path try/except so one bad unlink never aborts the purge), serialized under
      `state_reconcile_lock(<root>/state)`, and returns `{"removed": [...], "skipped": [...]}`;
  (5) NEVER removes or even enumerates a `brief_hooks_*.md` or any path that is not an EXACT known per-task
      sidecar template — anything else is fail-closed-skipped (classify-and-fail-closed).
  The whole function is fail-safe and never raises.
- New supporting top-level helper(s) in the SAME file: the sidecar-manifest enumerator and the
  default-OFF config reader (mirroring the watchdog reader). No change to any existing function.
- New `autowork.purge_task_state.enabled` config key, read DEFENSIVELY with the conservative default
  `false` so the default behavior does NOT regress today's reconciler.
- A pre-committed RED oracle proving: exact-manifest removal, the live-pidfile REFUSE, the
  `brief_hooks_*.md`-never-touched / unclassifiable-path-never-touched invariant, idempotency, and
  default-OFF fail-safety.

# Required plan shape
Emit EXACTLY TWO tasks, a RED-pair.

Task 1 — the oracle (authored RED first):
- task_id MUST be exactly `purge-task-state-primitive-oracle`.
- meta_task_type: test_authoring
- mutation_target: harness.state_reconciler   (dotted MODULE only)
- files_touched: ["tests/harness/test_purge_task_state_primitive.py"]
- Submit the test file source directly (ordinary Python; do NOT emit either patch/manifest marker).
- verification_command: `python -m pytest tests/harness/test_purge_task_state_primitive.py -q`
- The oracle MUST, using a tmp-dir fixture `root` (NO reliance on the live repo; construct the whole
  `root/state/...` tree synthetically) and toggling
  `config={"autowork":{"purge_task_state":{"enabled":True}}}`, assert AT MINIMUM (ALL checks are runtime
  checks on module behavior and on-disk artifacts — return values, files — NEVER a scan of the test
  file's own source text):
  (a) EXACT-MANIFEST REMOVAL: plant the FULL canonical sidecar set for `task_demo` on disk
      (`state/output/task_demo.patches.json`, `.files.json`, `.fallback.py`, `.fallback.patches.json`,
      `.fallback.files.json`; `state/sessions/claude_task_demo_submission.json`;
      `state/tasks/task_demo.json`; `state/tasks/processed/task_demo.json`;
      `state/tasks/test_results/task_demo_baseline.json`; `logs/fuzz_results/task_demo_x.json`;
      `state/control/autowork/running/task_demo.slot`; `state/tasks/blocked/task_demo.json`,
      `task_demo.retry.json`, `task_demo.exhausted`) — and a UNRELATED sibling task's sidecar
      (`state/output/task_demo2.patches.json`) AND a `brief_hooks_purge_demo.md` at `root` AND an
      unrelated stray file `state/output/keepme.txt`. After
      `purge_task_state(root, "task_demo", config=cfg)`, assert: every planted `task_demo` sidecar is GONE;
      the sibling `task_demo2` sidecar STILL EXISTS (substring-proof — `task_demo` must not also reap
      `task_demo2`); the `brief_hooks_purge_demo.md` STILL EXISTS; the stray `keepme.txt` STILL EXISTS;
      and the returned `removed` list contains the planted task_demo sidecar paths (and `skipped`/`removed`
      never contains the brief_hooks file or keepme.txt).
  (b) LIVE-PIDFILE REFUSE: plant a running pidfile for `task_demo` whose pid IS signalable (use the CURRENT
      test process pid, `os.getpid()`, so `os.kill(pid,0)` succeeds — derive the pidfile stem/dir from the
      module's own `_running_dir` + `_pidfile_task_id` parsing so the planted name is exactly what the
      liveness probe matches, NOT a hard-coded format), PLUS the full sidecar set. After
      `purge_task_state(root, "task_demo", config=cfg)`, assert: the return has `refused` True with a
      typed reason indicating a live worker; NO sidecar was removed (every planted file STILL EXISTS,
      including the pidfile); `removed` is empty.
  (c) BRIEF_HOOKS / UNCLASSIFIABLE NEVER TOUCHED: independently of (a), with a `task_id` whose name could
      substring-collide with an unrelated artifact, assert the function never enumerates or removes any
      `brief_hooks_*.md` at `root` and never removes a path that is not an exact per-task sidecar (a stray
      `state/output/<other>.json` or a top-level doc is preserved).
  (d) IDEMPOTENT: a SECOND `purge_task_state(root, "task_demo", config=cfg)` (after (a)) returns cleanly
      with an empty (or already-gone) `removed` set and raises nothing; the workspace is unchanged.
  (e) DEFAULT-OFF FAIL-SAFE: with `config=None` (and separately with
      `{"autowork":{"purge_task_state":{"enabled":False}}}`), `purge_task_state(root, "task_demo")`
      performs NO unlink (every planted sidecar STILL EXISTS), returns a clean disabled/refused summary,
      and raises nothing; and a `root` with no state tree returns cleanly without raising.

Task 2 — the implementation:
- task_id MUST be exactly `purge-task-state-primitive-impl`.
- meta_task_type: harness_self_fix
- files_touched: ["harness/state_reconciler.py"]
- depends on `purge-task-state-primitive-oracle`.
- Emit a `__JANUSMASK_PATCHES__` (do NOT emit a manifest block).
- OMIT mutation_target. spec_author: null (the oracle is the pre-committed RED sibling).
- verification_command:
  `python -m pytest tests/harness/test_purge_task_state_primitive.py tests/harness/test_reconciler_reaps_spent_briefs.py tests/adversarial/test_autowork_reap_zombie.py -q`
  (the new purge tests PLUS existing reconciler/reap regressions exercised by the changed module; scoped to
  the changed surface — NEVER the full adversarial suite, which flakes and wrongly blocks the edit).
- non_goals MUST contain the literal word `integration` (the impl creates no new wired module — it extends
  the already-wired live `harness/state_reconciler.py` — so the integration-test requirement is excused).
- regression_tests >= 2.

# Required plan shape — wiring (acceptance)
At acceptance the new behavior is reachable from the live import graph WITHOUT editing any
`_NEVER_AUTO_APPROVE` file: `harness/state_reconciler.py` is already a live-reachable module
(`harness.wire_up.check_wired(repo_root, 'harness/state_reconciler.py').wired is True`, importer
`autowork_daemon.py`), so adding a top-level helper to it satisfies the wire-up gate (the
`orphan_unwired` gate fires only for NEW modules, not new symbols in an already-wired module). The
primitive is a CALLABLE operator/reopen-path utility; this brief deliberately does NOT thread it into a
live sweep or dispatch path (that would risk perturbing a live run). The oracle proves the contract
end-to-end on a synthetic `root`.

# Implementation notes / hazards
- R-ANCHOR additive: `purge_task_state` and its supporting helper(s) are brand-new top-level symbols. A
  standalone `kind:symbol` patch for a not-yet-existing name fails patch-apply (opaque
  `auto_commit_failed`). Add them via the R-ANCHOR additive pattern — ONE `symbol` patch whose `name` is
  an EXISTING 1-part top-level anchor in this module that you reproduce VERBATIM (e.g. `_running_dir`, the
  small canonical-running-dir helper at the file's tail, OR `reap_orphaned_workdirs`) PLUS the new
  `purge_task_state` + supporting helpers appended as extra top-level `def`s. Extra top-level `def`s are
  in the allowed_extra whitelist, so they land in ONE patch entry; the new names must not collide with an
  existing symbol. Reproduce the chosen anchor function BYTE-FOR-BYTE unchanged.
- REUSE existing primitives: `task_id_has_live_pidfile`, `pid_is_live`, `_running_dir`, `_pidfile_task_id`,
  `state_reconcile_lock`, and `_watchdog_truthy` (for the flag's truthiness). Do NOT duplicate a liveness
  probe, a running-dir resolver, or a lock.
- DEFAULT-OFF FAIL-SAFE: `autowork.purge_task_state.enabled` defaults false; with it false (and with
  `config` None) the function is a strict no-op so the existing reconciler behavior is byte-for-byte
  preserved and the existing reap regressions stay green.
- CLASSIFY-AND-FAIL-CLOSED: the enumerator MUST build paths ONLY from the exact known per-task templates
  (the manifest). It MUST NOT glob broadly (e.g. NOT `state/output/*<tid>*`); the two legitimate globs are
  the EXACT-suffix `sessions/*_<tid>_submission.json`, the EXACT-prefix `test_results/<tid>*` /
  `fuzz_results/<tid>*` — and even there, match on the parsed task id, not a loose substring, so `task_demo`
  never reaps `task_demo2`. Anything not matching an exact template is never enumerated and never removed.
  A `brief_hooks_*.md` at `root` is NEVER in the manifest.
- LIVENESS GATE FIRST: evaluate `task_id_has_live_pidfile(_running_dir(root), task_id)` BEFORE any unlink;
  if live, refuse the WHOLE purge (no unlink, pidfile preserved) with a typed reason.
- LOCK DISCIPLINE: serialize the unlinks under `state_reconcile_lock(<root>/state)`; never acquire
  `git_commit.lock`. The lock is re-entrant, so taking it here is safe.
- NESTED-QUOTE HAZARD: when emitting any `"""` docstring inside the `__JANUSMASK_PATCHES__` code block,
  emit `"""` (triple double-quote) — never `'''` and never backslash-escape quotes inside the payload.
- Keep ALL unlink operations behind per-path try/except so a single missing/locked file never aborts the
  purge or the daemon iteration.

# Sequencing note (do NOT act on this)
Do NOT add this brief's slug to `state/control/autowork/auto_promote.allowlist`. Leave this file at the
repo root alongside the other `brief_hooks_*.md` files; the main loop will queue it after the in-flight
`p11_build_evidence_perphase` work lands. This brief edits ONLY the auto-approvable
`harness/state_reconciler.py`, so NO operator decision file is required to dispatch it (a decision is
requested for the program, not because the path is trust-core).
