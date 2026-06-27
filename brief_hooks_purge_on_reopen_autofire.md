---
working_dir: "/home/xnihil0zer0/JanusMaskJR"
priority: P2
meta_task_type: harness_self_fix
operator_decision_required: true
auto_approve_requested: true
required_task_ids:
  - purge-on-reopen-autofire-oracle
  - purge-on-reopen-autofire-impl
interfaces: >
  EDIT EXACTLY ONE existing file: harness/state_reconciler.py. Add a NEW top-level helper
  `purge_reopened_task_state(root, task_id, *, prev_plan_sha=None, plan_sha=None, config=None) -> dict`
  that AUTO-FIRES `purge_task_state` for a re-opened task ONLY when BOTH guards hold: (1) the task is NOT
  live (its running pidfile is dead/absent — reuse `task_id_has_live_pidfile`), AND (2) the brief/plan SHA
  ACTUALLY CHANGED (`prev_plan_sha != plan_sha`, both non-empty) — i.e. a genuine correction + re-plan, NOT
  a legitimate mid-retry of the SAME plan (attempts < budget, blocked but not re-planned). It is gated OFF
  by default behind a NEW `autowork.purge_task_state.autofire_on_reopen` config flag (default false),
  SEPARATE from and ANDed with the base `autowork.purge_task_state.enabled` flag. This is the auto-fire
  layer the operator-only `purge_task_state` primitive deliberately omitted. It DEPENDS on
  `purge_task_state` existing (brief `purge_task_state_primitive`); land that FIRST.
---

# Title
state_reconciler: guarded auto-purge of a re-opened task's stale sidecars (NOT-live AND SHA-changed; default-OFF)

# Scope
EDIT the SINGLE EXISTING file `harness/state_reconciler.py` (READ it first; auto-approvable `harness/**`,
NOT in `_NEVER_AUTO_APPROVE`). SINGLE FILE. Emit a `__JANUSMASK_PATCHES__` payload.

This brief ADDS ONE new top-level guarded wrapper that calls the `purge_task_state` primitive added by the
companion brief `brief_hooks_purge_task_state_primitive.md`. It is the SAFE shape for "auto-purge a task's
stale sidecars when it re-opens": it fires ONLY when the task is provably NOT live AND the plan/brief SHA
actually changed, so it can never race a live worker and never purges a task that is legitimately
mid-retry on the SAME plan.

# Inputs
READ `harness/state_reconciler.py`. VERIFIED facts:
- `purge_task_state(root, task_id, *, config=None, now=None) -> dict` is the primitive added by the
  companion brief; it is itself liveness-guarded, default-OFF, and fail-closed. REUSE it — do NOT
  re-enumerate the sidecar manifest here.
- Liveness probe to REUSE: `task_id_has_live_pidfile(_running_dir(root), task_id)` (~line 92).
- Default-OFF config-reader PATTERN: `_watchdog_enabled` / `_watchdog_truthy` / `_watchdog_cfg_section`
  (~lines 1152-1198). Build the analogous reader for the new `autowork.purge_task_state.autofire_on_reopen`
  flag the same way (reuse `_watchdog_truthy`).
- The RE-OPEN trigger lives in `harness/brief_status.py:97-108`: a plan is re-opened (→ `unplanned`,
  re-queued) when the stamped `source_brief_sha256` != current brief SHA, OR `plan_mtime < brief_mtime`.
  brief_status.py is a PURE read-only module and is NOT edited by this brief; the SHA values are PASSED IN
  to this helper by the caller (the caller supplies `prev_plan_sha` = the plan's stamped
  `source_brief_sha256` and `plan_sha` = the current brief's sha256). This brief does NOT wire the call
  site into brief_status.py or any dispatch path (that wiring is owner-gated; see Non-Goals); it adds only
  the guarded, independently-testable helper.

# Non-Goals
This leaf does NOT edit any `_NEVER_AUTO_APPROVE` file. It does NOT edit `harness/brief_status.py` (pure
read-only; out of scope) and does NOT wire the auto-fire into the live re-open path or any dispatch loop —
that integration is owner-gated and deferred, precisely because firing on the live re-open path could race
a concurrent worker if mis-wired. This brief delivers the GUARDED helper as a callable, default-OFF unit so
the guard logic is proven in isolation before any live wiring. It does NOT re-enumerate the sidecar
manifest (it delegates to `purge_task_state`). It does NOT change any existing function. Integration test
coverage is out of scope for the implementation task (extends an already-wired module, not a new module —
the word `integration` appears here to excuse the integration-test requirement).

# Deliverables
- A new top-level `purge_reopened_task_state(root, task_id, *, prev_plan_sha=None, plan_sha=None,
  config=None) -> dict` in `harness/state_reconciler.py` that:
  (1) is a strict no-op unless BOTH `autowork.purge_task_state.enabled` AND
      `autowork.purge_task_state.autofire_on_reopen` are truthy (default false → no-op);
  (2) REFUSES (no-op + typed reason) when the task is live (`task_id_has_live_pidfile` True) — never races
      a live worker;
  (3) REFUSES (no-op + typed reason `sha_unchanged`) when `prev_plan_sha == plan_sha`, or when either is
      empty/None — so a legitimate mid-retry of the SAME plan (no correction, no re-plan) is NEVER purged;
  (4) only when not-live AND both flags on AND the SHA genuinely changed, delegates to
      `purge_task_state(root, task_id, config=config)` and returns its result (augmented with the reopen
      decision); fail-safe, never raises.
- New `autowork.purge_task_state.autofire_on_reopen` config key, read defensively, default `false`.
- A pre-committed RED oracle proving the two guards (not-live AND sha-changed), the mid-retry-preserved
  case, and default-OFF fail-safety.

# Required plan shape
Emit EXACTLY TWO tasks, a RED-pair.

Task 1 — the oracle (authored RED first):
- task_id MUST be exactly `purge-on-reopen-autofire-oracle`.
- meta_task_type: test_authoring
- mutation_target: harness.state_reconciler   (dotted MODULE only)
- files_touched: ["tests/harness/test_purge_on_reopen_autofire.py"]
- Submit the test file source directly (ordinary Python; no marker).
- verification_command: `python -m pytest tests/harness/test_purge_on_reopen_autofire.py -q`
- The oracle MUST, on a synthetic tmp `root` (no live-repo reliance), with
  `cfg={"autowork":{"purge_task_state":{"enabled":True,"autofire_on_reopen":True}}}`, assert AT MINIMUM
  (all runtime/on-disk checks, never a scan of the test's own source):
  (a) SHA-CHANGED + NOT-LIVE → PURGES: plant the task's sidecar set (a couple of canonical sidecars
      suffice) with NO live pidfile; call with `prev_plan_sha="aaa", plan_sha="bbb"`; assert the sidecars
      are removed and the return indicates a purge fired.
  (b) SHA-UNCHANGED → PRESERVED (mid-retry): same setup but `prev_plan_sha="aaa", plan_sha="aaa"`; assert
      NO sidecar removed, return has a typed `sha_unchanged` refusal.
  (c) LIVE → PRESERVED: SHA changed (`"aaa"`→`"bbb"`) BUT plant a LIVE pidfile (`os.getpid()`); assert NO
      sidecar removed, return has a typed live-worker refusal.
  (d) DEFAULT-OFF: with `config=None` (and separately with `autofire_on_reopen` false but `enabled` true,
      and with `enabled` false), the function is a strict no-op (no removal, clean summary, no raise).
  (e) MISSING SHA: with `prev_plan_sha=None` or `plan_sha=None`/empty, the function refuses (treats unknown
      SHA as "not provably changed" → preserve), removing nothing.

Task 2 — the implementation:
- task_id MUST be exactly `purge-on-reopen-autofire-impl`.
- meta_task_type: harness_self_fix
- files_touched: ["harness/state_reconciler.py"]
- depends on `purge-on-reopen-autofire-oracle`.
- Emit a `__JANUSMASK_PATCHES__` (no manifest block).
- OMIT mutation_target. spec_author: null.
- verification_command:
  `python -m pytest tests/harness/test_purge_on_reopen_autofire.py tests/harness/test_purge_task_state_primitive.py -q`
- non_goals MUST contain the literal word `integration`. regression_tests >= 2.

# Required plan shape — wiring (acceptance)
`harness/state_reconciler.py` is already live-reachable (importer `autowork_daemon.py`); adding a top-level
helper satisfies the wire-up gate (orphan_unwired fires only for new MODULES). The helper is a callable
guarded utility; this brief deliberately does NOT thread it into the live re-open path.

# Implementation notes / hazards
- DEPENDENCY: this brief assumes `purge_task_state` exists in `harness/state_reconciler.py`. Land
  `brief_hooks_purge_task_state_primitive.md` FIRST. If `purge_task_state` is absent at impl time the impl
  will fail; do not dispatch this brief before the primitive lands.
- R-ANCHOR additive for the new top-level symbol(s) (see the companion brief's R-anchor note): reproduce an
  existing 1-part top-level anchor byte-for-byte and append the new `def`(s) as allowed extras.
- REUSE `purge_task_state`, `task_id_has_live_pidfile`, `_running_dir`, `_watchdog_truthy`. Do NOT
  duplicate the manifest, the liveness probe, or a lock.
- DEFAULT-OFF FAIL-SAFE: both flags default false; the function is a strict no-op by default.
- GUARD ORDER: evaluate flags → live check → sha-changed check; any failed guard returns a typed refusal
  and removes nothing.
- NESTED-QUOTE HAZARD: emit `"""` (not `'''`) in any patched docstring; no backslash-escaped quotes.

# Sequencing note (do NOT act on this)
Do NOT add this brief's slug to `state/control/autowork/auto_promote.allowlist`. Dispatch AFTER
`brief_hooks_purge_task_state_primitive.md` lands (hard dependency on the `purge_task_state` symbol) AND
after the in-flight `p11_build_evidence_perphase` work. Edits ONLY auto-approvable
`harness/state_reconciler.py`, so NO operator decision file is required.
