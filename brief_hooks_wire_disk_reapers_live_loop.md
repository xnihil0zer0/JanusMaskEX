---
working_dir: "/home/xnihil0zer0/JanusMaskJR"
priority: P1
meta_task_type: harness_self_fix
operator_decision_required: true
auto_approve_requested: true
required_task_ids:
  - wire-disk-reapers-live-loop-oracle
  - wire-disk-reapers-live-loop-impl
interfaces: >
  EDIT EXACTLY ONE existing file: harness/state_reconciler.py. The stale-STATE-cleanup program built a
  full periodic disk-reaper battery in `reap_stale_disk(root)` — orphaned-workdir rmtree,
  impl_progress.jsonl locked-atomic compaction (`compact_impl_progress_ledger`), log/drain age-out
  (`age_out_logs`), `_autowork_archive` retention prune (`prune_autowork_archive`), and the spent-brief
  reaper (`reap_spent_briefs`) — but `reap_stale_disk` is reachable ONLY from `cleanup_state(mode=apply)`,
  and `cleanup_state` has ZERO callers anywhere in the live harness (verified: every grep hit for
  `reap_stale_disk`/`cleanup_state`/`prepare_workspace` outside `state_reconciler.py` is a test/scratch/
  archive file). The live daemon loop (`autowork_daemon._reclaim_zombie_briefs` ARM-2, the only periodic
  sweep, already throttled behind `sha_staleness_sweep.marker` (300s) + serialized under
  `state_reconcile_lock` + gated by `autowork.state_reconcile=true`) calls ONLY
  `reap_orphaned_workdirs(repo_root, grace=86400.0)` — never the compaction/age-out/archive-prune/
  spent-brief steps. RESULT: those four reapers are DEAD on the live path. Empirical harm (live state
  tree, this repo): impl_progress.jsonl = 108,585 lines never compacted; `state/output/*.py` = 184 files
  accumulating since 2026-06-15; `_autowork_archive` = 71 entries never age-pruned; spent briefs depend
  on a fire-ONCE worker hot-path hook with no periodic catch. FIX (mirrors the EXISTING precedent in this
  same module where `reap_orphaned_workdirs` already tail-calls `detect_and_heal_stalls`): add a NEW
  top-level helper `reap_periodic_disk_battery(root, *, now=None, config=None) -> dict` that runs ONLY the
  four currently-unwired reapers (NOT the workdir rmtree — that already runs), each individually
  contained, and append ONE contained `try/except` tail-call to it inside the EXISTING live-reachable
  `reap_orphaned_workdirs`. This wires the battery into the live loop with ZERO edit to
  `autowork_daemon.py` (which is in `_NEVER_AUTO_APPROVE` and must not change). Default-SAFE: gated OFF
  behind a NEW `autowork.disk_reaper_battery` config flag (default false) so it cannot regress prod until
  proven; when off it is a strict no-op.
---

# Title
state_reconciler: wire the periodic disk-reaper battery (ledger compaction, log age-out, archive prune,
spent-brief reap) into the LIVE daemon loop via reap_orphaned_workdirs — default-OFF, fail-closed, ZERO
autowork_daemon.py edit

# Scope
EDIT the SINGLE EXISTING file `harness/state_reconciler.py` (READ it first — it is the canonical
reconciler module, an auto-approvable `harness/**` path, and is NOT in `_NEVER_AUTO_APPROVE`). SINGLE
FILE. This is a sensitive-path edit, so BOTH the oracle and the impl task are `meta_task_type:
harness_self_fix` and an operator decision is requested (auto-approve is owner-enabled for this program).

Two changes to that one file, emitted as `__JANUSMASK_PATCHES__` SYMBOL patches:

1. ADD a NEW top-level helper `reap_periodic_disk_battery(root, *, now=None, config=None) -> dict`.
2. EDIT the EXISTING top-level `reap_orphaned_workdirs(root, *, now=None, grace=60.0)` to APPEND one
   contained `try/except` tail-call to the new helper — alongside, NOT replacing, the existing
   `detect_and_heal_stalls(root, now=now)` tail-call.

The new behavior must EXTEND the reconciler, never reinvent it. Every reaper it runs ALREADY EXISTS in
this same module as a fully-tested top-level function; this brief only WIRES them onto the live path and
puts them behind a default-OFF flag.

# Background — why the disk reapers are dead on the live path (verified)
The stale-STATE-cleanup program (commits `7d063d2`..`3c05d6d`, 2026-06-18..2026-06-20) built a complete
`reap_stale_disk(root)` battery in `harness/state_reconciler.py`. `reap_stale_disk` (line ~957) runs,
under `state_reconcile_lock` and NEVER under `git_commit.lock`:
  - `reap_orphaned_workdirs` (orphaned `<agent>/<workdir>` rmtree),
  - `compact_impl_progress_ledger` (locked-atomic JSONL compaction; NEVER wipes),
  - `age_out_logs` (state/logs, state/drain, logs older than 14d),
  - `prune_autowork_archive` (`_autowork_archive` entries older than 14d),
  - `reap_spent_briefs` (delegates to `tools.brief_reaper.reap_for_task`; epic/brief-less-safe).

But `reap_stale_disk` is invoked ONLY from `cleanup_state(root, mode='apply')` (line ~419), and
`cleanup_state` has NO live caller. VERIFIED by grep across the whole repo (excluding tests/scratch/
archive/the module itself): the only references to `reap_stale_disk`, `cleanup_state`, and
`prepare_workspace` are inside `state_reconciler.py`'s own bodies/docstrings. The live daemon path is:

  `autowork_daemon._iteration` -> `_reclaim_zombie_briefs(repo_root, state_dir, running)`
    -> ARM-2 (gated by `autowork.state_reconcile=true` (config.yaml:79, currently ON), throttled by
       `sha_staleness_sweep.marker` 300s, serialized under `state_reconcile_lock`)
    -> `reap_orphaned_workdirs(repo_root, grace=86400.0)`  (autowork_daemon.py:2369-2370)

So on the live loop, ONLY the workdir rmtree runs. The other four reapers never fire periodically.
`reap_spent_briefs` does have a SECOND live path — the worker hot-path hook
`orchestrator_worker._reap_spent_briefs_safe` -> `tools.brief_reaper.reap_for_task` — but that fires
EXACTLY ONCE on the last task's accept and swallows all errors with no retry; a missed fire is never
caught. Ledger compaction, log age-out, and archive prune have NO live path at all.

EMPIRICAL HARM (this repo's live state tree, read-only counts taken during investigation):
  - `state/impl_progress.jsonl` = 108,585 lines, never compacted (every replay/scan reads all of it).
  - `state/output/*.py` = 184 emission files accumulating since 2026-06-15 (NOTE: out of battery scope —
    see Non-Goals; the per-task purge primitive owns those).
  - `_autowork_archive` = 71 entries, never age-pruned (retention prune is dead).
  - `state/logs` / `state/drain` / `logs` — never aged out.

WHY NOT just call `reap_stale_disk` from the daemon: that would require editing the daemon's import/call
lines (`autowork_daemon.py:2232,2369`) to swap `reap_orphaned_workdirs` for `reap_stale_disk` — but
`autowork_daemon.py` is in `_NEVER_AUTO_APPROVE` (`harness/orchestrator.py:2424`), so it CANNOT be
auto-approved and must not be hand-edited (owner directive: never hand-edit production outside the
pipeline). The CORRECT, in-pipeline fix keeps all cleanup logic in `state_reconciler.py` and rides the
seam the daemon ALREADY calls: `reap_orphaned_workdirs`. There is a working PRECEDENT for exactly this —
`reap_orphaned_workdirs` already ends with a contained `try: detect_and_heal_stalls(root, now=now)
except Exception: pass` tail-call (the watchdog was wired in the same way, commit `c6224c4`). This brief
adds a sibling contained tail-call to the new battery helper.

WHY default-OFF: the workdir rmtree (already live) is the cheapest reaper. The battery adds a 108k-line
ledger compaction + two age-out scans + a brief reap to EVERY ARM-2 sweep. Even though the whole arm is
throttled 300s and lock-serialized, the program rule is BUILT != WORKS and a new destructive periodic op
must land default-OFF, be proven, then be flipped on by the operator. So the helper is a strict no-op
unless `autowork.disk_reaper_battery` is truthy (env override `JM_DISK_REAPER_BATTERY` accepted too,
mirroring the `JM_WATCHDOG_ENABLED` pattern already in this module).

# Inputs
READ these files FIRST in `/home/xnihil0zer0/JanusMaskJR`:

- `harness/state_reconciler.py` — the SINGLE file both tasks touch. VERIFIED current state:
  - `reap_orphaned_workdirs(root, *, now=None, grace=60.0)` at line ~732. Its body ends (lines ~802-806):
        try:
            detect_and_heal_stalls(root, now=now)
        except Exception:
            pass
        return reaped
    The new tail-call goes immediately BEFORE `return reaped`, alongside the existing
    `detect_and_heal_stalls` block (same contained `try/except Exception: pass` shape).
  - `reap_stale_disk(root, *, now=None)` at line ~957 — the existing battery, which holds
    `state_reconcile_lock` and calls the four reapers. The NEW helper must NOT re-take
    `state_reconcile_lock` (the daemon's ARM-2 already holds it when it calls `reap_orphaned_workdirs`;
    the lock is reentrant per-thread via a thread-local refcount, lines ~611-619 — but the new helper is
    called from INSIDE `reap_orphaned_workdirs`, which `reap_stale_disk` ALSO calls under the lock, so
    re-acquiring would be redundant and the helper must stay lock-free and just run the four reapers).
  - `compact_impl_progress_ledger(root, *, allow=None) -> bool` at line ~808 — locked-atomic, never
    wipes, idempotent. Reuse AS-IS.
  - `age_out_logs(root, *, now=None, max_age_sec=1209600.0) -> list` at line ~891 — reuse AS-IS.
  - `prune_autowork_archive(root, *, now=None, max_age_sec=1209600.0) -> list` at line ~923 — reuse
    AS-IS.
  - `reap_spent_briefs(root, *, stamp=None) -> list` at line ~1451 — delegates to
    `tools.brief_reaper.reap_for_task`, epic/brief-less-safe, idempotent. Reuse AS-IS.
  - `_watchdog_truthy(val) -> bool` at line ~1152 and `_watchdog_enabled(config)` at line ~1186 —
    the EXISTING conservative truthiness + env/config arming pattern. The new flag check MUST reuse
    `_watchdog_truthy` for value coercion (do NOT hand-roll a second truthiness function) and follow the
    same env-OR-config arming shape.
  - `detect_and_heal_stalls(root, *, config=None, now=None) -> dict` at line ~1369 — the PRECEDENT for a
    default-OFF, fail-safe, contained tail-call wired into `reap_orphaned_workdirs`.

- `harness/autowork_daemon.py` — DO NOT EDIT (read lines ~2218-2384 for context only). Confirms ARM-2
  imports + calls `reap_orphaned_workdirs(repo_root, grace=86400.0)` under the throttle + lock + flag,
  and that NO other reaper is invoked on the live loop. This is why riding `reap_orphaned_workdirs` wires
  the battery in with zero daemon edit.

- `harness/config.yaml` — DO NOT EDIT here (read lines ~70-83 for context only): the `autowork:` section
  already holds `state_reconcile: true`. The new `disk_reaper_battery` flag is parsed defensively by the
  helper from the passed `config` dict; the daemon does not yet pass `config` into
  `reap_orphaned_workdirs`, so the helper must ALSO accept the env override and default OFF when neither
  is present (see Deliverables). Adding the literal config key is OUT OF SCOPE for the impl task (it would
  be a second file) — the flag defaults OFF when absent, which is the desired safe default; the operator
  flips it on later, exactly like `state_reconcile`.

# Non-Goals
Integration is out of scope (the literal word `integration` MUST appear in this section and in EACH
task's `non_goals` to excuse the integration-test requirement). Specifically OUT OF SCOPE:
- Editing `harness/autowork_daemon.py` (in `_NEVER_AUTO_APPROVE`), `harness/orchestrator.py`,
  `harness/orchestrator_worker.py`, `harness/config.yaml`, or ANY file other than
  `harness/state_reconciler.py`. The whole point is to wire the battery WITHOUT a daemon edit.
- Re-implementing or modifying `compact_impl_progress_ledger`, `age_out_logs`, `prune_autowork_archive`,
  `reap_spent_briefs`, `reap_stale_disk`, `cleanup_state`, `prepare_workspace`, `state_reconcile_lock`,
  `detect_and_heal_stalls`, or the existing workdir-rmtree body of `reap_orphaned_workdirs`. The four
  reapers are CONSUMED as-is; only a new helper + one tail-call are added.
- Cleaning up `state/output/*.py` emission files, `state/sessions/*` (530 files), `state/tasks/processed`
  (1017 markers), `state/tasks/test_results` (768), `logs/fuzz_results` (76), or stale `selfheal_skip`
  markers (89). Those per-task sidecars are the deliberately-separate concern of the ALREADY-AUTHORED
  `brief_hooks_purge_task_state_primitive.md` (`purge_task_state`) + `brief_hooks_purge_on_reopen_autofire.md`
  (which have NOT landed — no commits, not in code — and remain open). This brief is strictly the
  disk-reaper-BATTERY wiring; do NOT widen it to per-task purge.
- Flipping the new `autowork.disk_reaper_battery` flag ON in committed config, or restarting/
  reconfiguring the daemon. The flag stays default-OFF; the impl is proven, then the operator arms it.
- Adding a held-out spec oracle, a new lock, or any change to the 300s throttle / `state_reconcile` gate.
- Per-task ledger semantics or the `_reconcile_stale_ledger_heads` head-revert pass (separate concern,
  already landed at commit `44efd58`; do not touch it).

# Deliverables

## TASK 1 — wire-disk-reapers-live-loop-oracle (test_authoring; harness/state_reconciler.py)
The test_authoring stage authors a RED behavioral oracle (NO production edit in this task). It MUST be a
hermetic test that builds a fake state tree under a `tmp_path` workspace root and asserts the WIRING +
default-OFF + per-reaper containment + the live/in-flight protection invariant — NOT a frozen-literal
comparison and NOT satisfiable by hardcoding.

ANTI-GAMING ORACLE REQUIREMENTS (the oracle MUST, and MUST NOT leak the answer key):
- DEFAULT-OFF: with NO flag set (no `config`, env unset), call `reap_periodic_disk_battery(root)` and
  assert it is a strict no-op — it returns a summary dict whose reaper results are all empty/false AND it
  does NOT compact a multi-row ledger, does NOT delete an aged log, does NOT prune an aged archive entry,
  and does NOT archive a spent brief. Seed: a `state/impl_progress.jsonl` with a malformed/blank line
  among good rows (so compaction WOULD fire if armed), an aged file under `state/logs`, an aged entry
  under `_autowork_archive`, and a fully-integrated `plan_hooks_<slug>.json` + `brief_hooks_<slug>.md`
  pair (so the spent reaper WOULD fire if armed). Assert all four are UNTOUCHED when off.
- ARMED-VIA-CONFIG: pass `config={'autowork': {'disk_reaper_battery': True}}` (and, in a separate case,
  arm via the env override `JM_DISK_REAPER_BATTERY=1` with `monkeypatch.setenv`) and assert the battery
  RUNS: the ledger is compacted (malformed/blank line dropped, good rows preserved, never wiped to
  empty), the aged log is removed, the aged archive entry is pruned, and the spent brief+plan pair is
  archived under `_autowork_archive/<stamp>/...`. Assert each via the on-disk RESULT, not via mocking the
  reapers.
- WIRED-INTO-LIVE-SEAM: arm the flag, then call the LIVE-reachable `reap_orphaned_workdirs(root,
  config=... )` (the seam the daemon calls) and assert the battery side-effects happened — proving the
  tail-call is present in `reap_orphaned_workdirs`, not only in the standalone helper. (If
  `reap_orphaned_workdirs` does not yet thread `config`, the oracle MUST instead arm via the env override
  so the live seam fires the battery without a signature change — see Deliverables TASK 2 note on
  signature; the oracle author picks whichever arming path the agreed signature supports, and MUST assert
  the battery fired through `reap_orphaned_workdirs`, not only the helper.)
- LIVE / IN-FLIGHT PROTECTION (the load-bearing safety invariant): seed a LIVE in-flight task — a
  `state/control/autowork/running/<tid>.pid` whose pid is THIS process (`os.getpid()`, guaranteed
  signalable) AND a fresh `plan_hooks_<tid-slug>.json` / `brief_hooks_<tid-slug>.md` pair whose tasks are
  NOT all accepted in the ledger. Arm the flag, run the battery (and/or `reap_orphaned_workdirs`), and
  assert the LIVE task's brief+plan pair is NOT archived and the running pidfile is NOT removed — the
  spent-brief reaper only reaps fully-integrated pairs and the workdir reap already protects live
  pidfiles; the battery must never touch live/in-flight work. (This is the PLANNED_STALE / live-brief
  protection invariant the program requires: cleanup reconciles ONLY stale artifacts, never live ones.)
- PER-REAPER CONTAINMENT: seed ONE reaper's input to provoke an error (e.g. make `state/logs` a path that
  raises on iterate, or point the ledger at an unreadable path) and assert the battery STILL runs the
  OTHER reapers and returns a summary (one reaper's failure never aborts the others; no exception
  propagates).
- IDEMPOTENCE: run the armed battery TWICE and assert the second run is a no-op on the already-compacted
  ledger / already-pruned archive / already-reaped brief (no double-archive, no error).
The oracle MUST derive expectations from the on-disk effects, MUST NOT paste the impl source into the
test, and MUST NOT compare against a frozen expected summary literal.

`non_goals` MUST contain the literal word `integration`. `regression_tests >= 2`.

- `task_id: wire-disk-reapers-live-loop-oracle`
- `priority: high`
- `meta_task_type: test_authoring`
- `files_touched: ["tests/harness/test_wire_disk_reapers_live_loop.py"]`  (the RED oracle file; the
  test_authoring stage stages `harness/state_reconciler.py` as the module-under-test)
- `mutation_target: harness/state_reconciler.py`  (MODULE-only dotted path; the test exercises this
  module)
- `dependencies: []`
- `verification_command:` `python -m pytest tests/harness/test_wire_disk_reapers_live_loop.py -q`
  (RED against HEAD — the helper does not yet exist; do NOT use a broad `tests/adversarial/ -q` vcmd).

## TASK 2 — wire-disk-reapers-live-loop-impl (harness/state_reconciler.py)

IMPLEMENTATION NOTES (LOAD-BEARING — GENERAL correct behavior, NOT fixture-matching):

1. PATCH SHAPE: emit a `__JANUSMASK_PATCHES__` SYMBOL patch. TWO symbols change:
   - ADD the NEW top-level helper `reap_periodic_disk_battery` — land it via an R-ANCHORED enclosing
     patch on an existing top-level symbol (anchor on `reap_stale_disk` or `prune_autowork_archive`) so a
     brand-new module-level symbol lands correctly (a standalone new-symbol patch with no anchor fails
     patch-apply with an opaque `auto_commit_failed` — see the program's new-symbol R-anchor rule).
   - EDIT the EXISTING `reap_orphaned_workdirs` to append the contained tail-call.
   Do NOT emit `__JANUSMASK_MANIFEST__` (single existing file, symbol patches — not whole-file).

2. NEW helper `reap_periodic_disk_battery(root, *, now=None, config=None) -> dict`:
   - FAIL-SAFE / DEFAULT-OFF arming, mirroring `detect_and_heal_stalls`/`_watchdog_enabled`: armed iff the
     `JM_DISK_REAPER_BATTERY` env var is truthy (via the EXISTING `_watchdog_truthy`) OR the parsed config
     section `autowork.disk_reaper_battery` (tolerate a bare flag, a `{'disk_reaper_battery': ...}`
     wrapper, or `{'autowork': {'disk_reaper_battery': ...}}`) is truthy. With neither set -> NOT armed.
   - When NOT armed: return immediately a summary dict with `{'enabled': False}` and empty reaper results;
     touch NOTHING.
   - When armed: run, EACH in its OWN contained `try/except Exception` so one failure never aborts the
     others (mirror `reap_stale_disk`'s per-reaper containment): `compact_impl_progress_ledger(root)`,
     `age_out_logs(root, now=now)`, `prune_autowork_archive(root, now=now)`, `reap_spent_briefs(root)`.
     Do NOT run `reap_orphaned_workdirs` here (it already runs on the live path and calling it from here
     would recurse). Return a summary dict, e.g.
     `{'enabled': True, 'ledger_compacted': bool, 'logs': [...], 'archive': [...], 'spent_briefs': [...]}`.
   - Do NOT acquire `state_reconcile_lock` inside this helper (its caller `reap_orphaned_workdirs` is
     itself called by the daemon under the held lock and by `reap_stale_disk` under the held lock;
     re-acquiring is redundant and, while reentrant, is needless — keep the helper lock-free).
   - `now`/`config` default to `None`; `now` resolves to `time.time()` exactly as the sibling reapers do.

3. EDIT `reap_orphaned_workdirs`: SIGNATURE — add a keyword-only `config=None` parameter so the live seam
   can thread the daemon's config later (backward-compatible: existing callers
   `reap_orphaned_workdirs(repo_root, grace=86400.0)` and `reap_orphaned_workdirs(root_path, now=now)`
   keep working). Then, immediately BEFORE `return reaped` and AFTER the existing
   `try: detect_and_heal_stalls(root, now=now) except Exception: pass` block, ADD a SECOND contained
   block:
        try:
            reap_periodic_disk_battery(root, now=now, config=config)
        except Exception:
            pass
   Keep the existing `detect_and_heal_stalls` tail-call and the entire workdir-rmtree body
   byte-identical. The battery is gated OFF inside the helper, so this tail-call is a strict no-op until
   the operator arms the flag — `reap_orphaned_workdirs`'s current behavior is UNCHANGED by default.

4. GENERALITY: the arming check must be the GENERAL truthiness/env/config pattern (reuse `_watchdog_truthy`
   for coercion), NOT a hardcoded environment string match or a special-cased task. The four reaper calls
   pass `root`/`now` through generically; do NOT key any reaper on a fixture path, slug, or task_id.

`non_goals` MUST contain the literal word `integration`. `regression_tests >= 2`.

- `task_id: wire-disk-reapers-live-loop-impl`
- `priority: high`
- `meta_task_type: harness_self_fix`
- `files_touched: ["harness/state_reconciler.py"]`
- OMIT `mutation_target` (this is an impl task editing a `harness/**` path, not a test_authoring task).
- `dependencies: ["wire-disk-reapers-live-loop-oracle"]` (the RED oracle must exist first; the impl turns
  it green).
- Emit a `__JANUSMASK_PATCHES__` SYMBOL patch: the NEW `reap_periodic_disk_battery` (R-anchored on
  `reap_stale_disk` or `prune_autowork_archive`) + the EDIT to `reap_orphaned_workdirs`.
- `verification_command:` a SCOPED, non-vacuous pytest selecting the new oracle AND a slice of the
  existing reconciler suite that must stay green, e.g.
  `python -m pytest tests/harness/test_wire_disk_reapers_live_loop.py tests/harness/test_reap_spent_briefs_parity.py tests/harness/test_reconciler_reaps_spent_briefs.py -q`
  (do NOT use a broad `pytest tests/adversarial/ -q` vcmd — it is non-hermetic and flaky-blocks). Run the
  EXACT vcmd yourself before dispatch and confirm `N passed` with N>=2 and that the existing reconciler
  tests are NOT regressed.

# Required plan shape
Emit EXACTLY TWO tasks (pin via
`required_task_ids: [wire-disk-reapers-live-loop-oracle, wire-disk-reapers-live-loop-impl]`).
PRIORITY MUST be canonical lowercase (`high`), NEVER P0/P1/ints/Capitalized. The oracle task is
`test_authoring` (writes the RED test + carries `mutation_target: harness/state_reconciler.py`, MODULE
dotted path only); the impl task is `harness_self_fix` (writes the single `harness/**` path, OMITS
`mutation_target`). Each emits a `__JANUSMASK_PATCHES__` SYMBOL patch (the oracle writes a NEW test file;
the impl R-anchors the new helper). Each task's `non_goals` MUST contain the literal word `integration`;
each `regression_tests >= 2`. The impl `dependencies` on the oracle so the red pair is preserved (oracle
RED-before, impl GREEN-after). Do NOT add any task touching a file other than the one its `files_touched`
declares; do NOT add a task editing `autowork_daemon.py`, `orchestrator.py`, `orchestrator_worker.py`, or
`config.yaml`.

`harness/state_reconciler.py` is NOT in the irreducible `_NEVER_AUTO_APPROVE` set
(`harness/agent_jail.py`, `harness/dbus_proxy.py`, `harness/paths.py`, `harness/git_integration.py`,
`harness/orchestrator.py`, `harness/interceptors.py`, `harness/selfheal.py`, `harness/autowork_daemon.py`,
`services/**`), so the auto-approve-sensitive-harness path covers both tasks; an operator decision file
is requested via the frontmatter but no `_NEVER_AUTO_APPROVE` block applies.
