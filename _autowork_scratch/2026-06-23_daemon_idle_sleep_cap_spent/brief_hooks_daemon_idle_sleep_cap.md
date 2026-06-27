---
working_dir: "/home/xnihil0zer0/JanusMaskJR"
priority: high
operator_decision_required: true
auto_approve_requested: true
required_task_ids:
  - daemon-idle-sleep-cap-oracle
  - daemon-idle-sleep-cap-impl
interfaces: >
  ADDITIVE latency fix in harness/autowork_daemon.py. Today the idle heartbeat
  sleep (DEFAULT_HEARTBEAT_SEC=1800) is LONGER than the shortest blocked-task
  retry backoff (tier-1 = 300s). A task routed to tasks/blocked/ right before an
  idle cycle waits up to ~1800s for its next retry-scan instead of its own ~300s
  backoff. This is a LATENCY gap (the task DOES retry on the next iteration), not
  a correctness bug.

  FIX (pure, additive): cap the idle sleep by the soonest pending blocked-retry
  deadline. Add one pure helper `_soonest_blocked_retry_deadline(state_dir)` that
  REUSES the exact blocked-task enumeration `_retry_blocked_tasks` already
  performs (`tasks/blocked/*.json`, skip `*.retry.json`, skip `.exhausted`, read
  the `{attempts,last_outcome,ts}` sidecar, derive `effective_max` and the same
  300/3600/86400 backoff tiers) and returns the MIN over retry-ELIGIBLE blocked
  tasks of `last_ts + threshold(attempts)` (a wall-clock deadline), or None when
  no eligible task exists. Then at the idle-sleep site in `run_daemon`
  (`sleep_target = heartbeat if is_idle else poll`), when `is_idle`, cap:
  `sleep_target = min(heartbeat, max(grace, deadline - now))` with a small grace
  floor (e.g. 5.0s) so the loop never busy-spins, and ONLY when a deadline exists
  and is sooner than the heartbeat. The non-idle `poll` branch is UNCHANGED.

  SELF-RELOAD: this is a LOGIC change (not a startup-only config knob).
  `harness.autowork_daemon` is in the daemon self-reload watch set
  (autowork_daemon.py:2879), so an idle daemon notices its own source change,
  exits 0, and the run-autowork.sh supervisor respawns with the new code -- the
  cap takes effect on the next idle cycle with no manual intervention.

  TRUST-CORE: `harness/autowork_daemon.py` IS in `_NEVER_AUTO_APPROVE`
  (orchestrator.py:2577), so the IMPL task REQUIRES an operator decision file
  `state/control/decisions/daemon-idle-sleep-cap-impl.json` even under
  auto-approve; `operator_decision_required: true` and `auto_approve_requested:
  true` are set in this frontmatter. The ORACLE task edits only `tests/**` and
  needs no decision file.
---

# Title

`harness/autowork_daemon.py`: cap the idle heartbeat sleep by the soonest pending blocked-retry deadline so a freshly-blocked retry-eligible task auto-retries on its OWN backoff (~300s) instead of waiting up to the full heartbeat (~1800s) for the next idle scan. ADDITIVE; non-idle `poll` path and the retry/exhaust semantics are unchanged.

# Scope

EDIT the SINGLE EXISTING production file `harness/autowork_daemon.py` (READ it
first) via a `__JANUSMASK_PATCHES__` payload with TWO `kind:'symbol'` patches
(both target symbols are TOP-LEVEL -> direct symbol patches, NOT nested, no
R-anchor needed):

1. ADD a new top-level helper `_soonest_blocked_retry_deadline(state_dir)`
   (anchor it on the existing top-level `_retry_blocked_tasks` so the new symbol
   has an existing-symbol anchor).
2. PATCH the existing top-level `run_daemon` to cap the idle `sleep_target` by
   that deadline.

Touch NO other production file and NO other symbol. Do NOT add or change any
config knob (no new `config/config.yaml` entry; `DEFAULT_HEARTBEAT_SEC` and
`_heartbeat_interval` stay as-is). `harness/autowork_daemon.py` is in
`_NEVER_AUTO_APPROVE` (orchestrator.py:2577) so the IMPL task is
`harness_self_fix` and REQUIRES an operator decision file.

# Inputs

READ `harness/autowork_daemon.py`. VERIFIED current behavior:

- `_retry_blocked_tasks(state_dir, summary, max_attempts=3)` (`:911-999`)
  enumerates `tasks/blocked/*.json` (sorted), skips names ending `.retry.json`,
  skips any `tid` with a `blocked/<tid>.exhausted` marker, reads the
  `blocked/<tid>.retry.json` sidecar for `{attempts:int, ts:float,
  last_outcome:str}`, computes `effective_max = 1 if last_outcome in
  _DETERMINISTIC_OUTCOMES else max_attempts` (where
  `_DETERMINISTIC_OUTCOMES = ('synthesis_or_ast_failed', 'embedded_tests_failed',
  'narrow_fuzz_failed')`, `:954`), parks (writes `.exhausted` + escalates) when
  `attempts >= effective_max`, else applies the backoff: `threshold = 300.0` for
  `attempts <= 1`, `3600.0` for `attempts == 2`, else `86400.0` (`:980-985`), and
  re-stages only when `time.time() - last_ts >= threshold` (`:986`).
- `run_daemon` (`:2791`) idle-sleep site: `is_idle` is computed (`:2920-2922`);
  then `sleep_target = heartbeat if is_idle else poll` (`:2932`); the sleep is a
  `while slept < sleep_target` loop in 0.5s steps that also breaks early on an
  allowlist/brief mtime change when idle (`:2936-2941`). `state_dir` and
  `heartbeat` are in scope at `:2932`.
- `harness.autowork_daemon` is in the self-reload watch set (`:2879`), so this
  logic change is picked up on the next idle cycle via clean-exit + supervisor
  respawn (no startup-only config knob).
- `harness/autowork_daemon.py` IS in `_NEVER_AUTO_APPROVE`
  (orchestrator.py:2577).

The new helper MUST REUSE this exact enumeration + backoff so it can never drift
from the real retry decision. It returns the soonest wall-clock retry deadline
`last_ts + threshold(attempts)` over the retry-ELIGIBLE blocked tasks (NOT
exhausted, `attempts < effective_max`), or None when there is none. It MUST be
pure (no re-staging, no marker writes, no telemetry, no mutation of state) and
fail-soft: a missing `blocked/` dir, an OSError on glob, or a malformed sidecar
yields None / is skipped, never raises.

VERIFIED the validator gates the synthesized plan must satisfy
(`harness/planner/plan_validator.py`): `missing_integration_test` (`:250-256`)
excuses an empty `integration_tests` list ONLY when some `spec.non_goals` entry
lowercased contains the substring `integration`; `missing_edge_case_tests`
(`:257-263`, `needed = min(2, len(edge_cases))`) fires only on NON-`test_authoring`
tasks and requires `len(property_tests) + len(regression_tests) >= needed`.

VERIFIED the hermetic test idiom to REUSE: `tests/harness/test_retry_smoke_failed_budget.py`
builds a synthetic `state_dir` with `tasks/blocked/` and writes a blocked task
`<tid>.json` + a `<tid>.retry.json` sidecar carrying `{attempts, ts,
last_outcome}` at controlled timestamps. The oracle reuses this pattern to drive
the REAL helper.

# Non-Goals

Integration testing is out of scope for BOTH tasks in this plan. This is a
unit-level daemon timing fix: the oracle drives the REAL
`_soonest_blocked_retry_deadline` over a hermetic synthetic state dir with fake
blocked sidecars at controlled timestamps (it never spawns the daemon loop, an
agent, or a real worker), and the impl is a single in-place harness symbol patch
with NO new runtime/integration surface -- so an integration test is not
meaningful and the integration-test requirement is EXCUSED. For BOTH tasks in
this plan, the synthesized `spec.non_goals` array MUST contain at least one
verbatim entry that includes the literal word `integration` (e.g. "No integration
test: unit-level daemon idle-sleep-cap helper / harness symbol patch, never
drives the daemon loop -- no new integration surface"); this is the exact token
the `missing_integration_test` validator gate scans for to excuse the empty
`integration_tests` list. Do NOT add real `integration_tests`.

HARD NEGATIVES (the change is ADDITIVE and surgical): do NOT change the
`_retry_blocked_tasks` re-stage / exhaust / backoff semantics, the
`.exhausted`-marker logic, the autobrief escalation, the `_DETERMINISTIC_OUTCOMES`
set, or the non-idle `poll` sleep branch. Do NOT add a config knob or change
`DEFAULT_HEARTBEAT_SEC` / `_heartbeat_interval`. Do NOT let the helper mutate
state (no re-staging, no marker / telemetry writes). The cap MUST apply ONLY when
`is_idle` and ONLY when a deadline exists and is strictly sooner than the
heartbeat; otherwise `sleep_target` stays the full heartbeat. The grace floor
keeps the capped sleep `> 0` so the idle loop never busy-spins. The helper need
NOT model the `dest.exists()` re-stage skip (`_retry_blocked_tasks:989-990`); any
resulting early-wake on a lingering-but-undispatchable blocked task is bounded by
the `grace` floor to the poll cadence -- acceptable, no busy-spin. Do NOT use
`exec`/`eval`/`compile`/`__import__` anywhere (AST-banned,
`harness/ast_enforcer.py`). Do NOT edit any other file, create a new module, or
author tests beyond the one paired oracle. Do NOT use the broad adversarial suite
as the verification command.

# Deliverables

`harness/autowork_daemon.py` such that:

- A NEW pure top-level helper `_soonest_blocked_retry_deadline(state_dir) ->
  float | None` REUSES the `_retry_blocked_tasks` enumeration (same
  `tasks/blocked/*.json` glob, same `.retry.json` / `.exhausted` skips, same
  sidecar parse, the SAME deterministic-outcome rule (`_DETERMINISTIC_OUTCOMES`
  is a LOCAL defined INSIDE `_retry_blocked_tasks` at `:954`, NOT a module-level
  symbol -- the new helper MUST INLINE the tuple literal
  `('synthesis_or_ast_failed', 'embedded_tests_failed', 'narrow_fuzz_failed')`
  and MUST NOT reference the bare name from module scope, or it will raise
  `NameError`) -> `effective_max`, same
  300/3600/86400 backoff tiers) and returns `min(last_ts + threshold(attempts))`
  over retry-ELIGIBLE blocked tasks (NOT exhausted; `attempts < effective_max`),
  or `None` when there is no eligible blocked task. It is read-only and fail-soft
  (no `blocked/` dir, glob OSError, or bad sidecar -> None / skip; never raises).
- `run_daemon`, at the idle-sleep site, caps `sleep_target` when `is_idle`:
  compute `dl = _soonest_blocked_retry_deadline(state_dir)`; if `dl is not None`,
  set `sleep_target = min(sleep_target, max(grace, dl - time.time()))` with a
  small `grace` floor (e.g. `5.0`) so a freshly-blocked, retry-eligible task is
  re-scanned on ITS backoff. The non-idle `poll` branch and the early-wake
  mtime-watch loop are UNCHANGED.

Illustrative sketch (adapt to the real surrounding code; do NOT paste full
bodies):

    def _soonest_blocked_retry_deadline(state_dir):
        blocked = pathlib.Path(state_dir) / 'tasks' / 'blocked'
        if not blocked.is_dir():
            return None
        try:
            entries = sorted(blocked.glob('*.json'))
        except OSError:
            return None
        soonest = None
        for p in entries:
            if p.name.endswith('.retry.json'):
                continue
            tid = p.name[:-len('.json')]
            if (blocked / f'{tid}.exhausted').exists():
                continue
            attempts, last_ts, last_outcome = 0, 0.0, ''
            sc = blocked / f'{tid}.retry.json'
            if sc.exists():
                try:
                    d = json.loads(sc.read_text(encoding='utf-8'))
                    # parse attempts/ts/last_outcome defensively (mirror _retry_blocked_tasks)
                    ...
                except (OSError, ValueError):
                    attempts, last_ts, last_outcome = 0, 0.0, ''
            effective_max = 1 if last_outcome in ('synthesis_or_ast_failed', 'embedded_tests_failed', 'narrow_fuzz_failed') else 3  # INLINE literal -- _DETERMINISTIC_OUTCOMES is LOCAL to _retry_blocked_tasks, not a module symbol
            if attempts >= effective_max:
                continue
            threshold = 300.0 if attempts <= 1 else (3600.0 if attempts == 2 else 86400.0)
            dl = last_ts + threshold
            soonest = dl if soonest is None else min(soonest, dl)
        return soonest

    # in run_daemon, after `sleep_target = heartbeat if is_idle else poll`:
    if is_idle:
        _dl = _soonest_blocked_retry_deadline(state_dir)
        if _dl is not None:
            sleep_target = min(sleep_target, max(5.0, _dl - time.time()))

# Required plan shape

A clean 2-task RED-PAIR (the proven shape). Slug: `daemon_idle_sleep_cap`.
EXACTLY ONE implementation task (the `harness_self_fix` impl).

★CRITICAL (this broke prior briefs): the plan validator checks EACH TASK's
`spec.non_goals` for the literal word `integration`, NOT the brief section.
Therefore BOTH tasks' synthesized `spec.non_goals` arrays MUST EACH include at
least one entry containing the literal word `integration` (see # Non-Goals).
Omitting it on EITHER task trips `missing_integration_test` and FAILS validation.
Do NOT add real `integration_tests`.

## TASK 1 -- ORACLE (test_authoring), id: daemon-idle-sleep-cap-oracle

- meta_task_type: test_authoring
- mutation_target: harness.autowork_daemon  (bare dotted MODULE only)
- files_touched: [tests/harness/test_daemon_idle_sleep_cap.py]
- dependencies: []
- priority: high
- verification_command: python -m pytest tests/harness/test_daemon_idle_sleep_cap.py -q
- spec.non_goals MUST include a verbatim entry containing the literal word
  `integration` (see ★CRITICAL above).

Author `tests/harness/test_daemon_idle_sleep_cap.py` (new file, beside
`tests/harness/test_retry_smoke_failed_budget.py`). Import the REAL helper
`from harness.autowork_daemon import _soonest_blocked_retry_deadline` (normal
import / importlib `spec.loader.exec_module` from a tmp path -- NEVER
`exec`/`eval`/`compile`/`__import__`, AST-banned). REUSE the hermetic idiom from
`test_retry_smoke_failed_budget.py`: a `tempfile.TemporaryDirectory()` state dir
with `tasks/blocked/` created, and a `_write_blocked(tid, attempts, last_outcome,
ts)` helper that writes `<tid>.json` + the `<tid>.retry.json` sidecar
`{attempts, ts, last_outcome}`. Drive the REAL helper directly and assert on the
returned deadline. The cap formula the helper feeds is
`min(heartbeat, max(grace, deadline - now))`; the helper itself returns the
DEADLINE (wall-clock `last_ts + threshold`), so the oracle asserts on that and
recomputes the cap in-test to prove teeth. RED on HEAD (the helper does not exist
yet). The assertions (all hermetic, offline):

1. SOONER-THAN-HEARTBEAT: one blocked task, `attempts=1`, `last_outcome='timeout'`
   (non-deterministic), `ts = now - 100` -> the helper returns a deadline equal
   to `ts + 300.0`; and the derived cap `min(1800.0, max(5.0, deadline - now))`
   is STRICTLY LESS THAN 1800.0 (i.e. ~200s, not the full heartbeat). This is the
   core teeth assertion (the freshly-blocked task is re-scanned on its 300s
   backoff, not the 1800s heartbeat).
2. NEAREST WINS: two blocked tasks -- one with `ts + 300.0` far in the future and
   one nearer -> the helper returns the SOONER of the two deadlines (the `min`).
3. NONE-WHEN-EMPTY: empty `tasks/blocked/` (or missing dir) -> the helper returns
   None (so the cap is a no-op and `sleep_target` stays the full heartbeat).
4. EXHAUSTED-EXCLUDED: a blocked task whose `attempts >= effective_max` (or which
   carries a `<tid>.exhausted` marker) is NOT counted -- if it is the only blocked
   task, the helper returns None. Cover BOTH the `.exhausted`-marker case AND the
   `attempts >= effective_max` case (e.g. `attempts=3` with a generic outcome,
   and `attempts=1` with a deterministic outcome like `synthesis_or_ast_failed`
   where `effective_max == 1`).
5. PROPERTY / FAIL-SOFT: the helper is READ-ONLY and never raises -- a malformed
   `<tid>.retry.json` (non-JSON bytes) is skipped (treated as defaults, never an
   exception), and after any call the blocked task `.json` files are STILL in
   `tasks/blocked/` (the helper re-stages nothing and writes no `.exhausted` /
   marker / telemetry).
6. TIER BOUNDARY: a task with `attempts=2`, `last_outcome=''` (generic) ->
   deadline equals `ts + 3600.0` (proves the 3600s tier-2 backoff is used, not
   300s), confirming the helper reuses the SAME tier schedule as
   `_retry_blocked_tasks`.

Keep the oracle hermetic and offline. Do NOT import or run the broad adversarial
suite. Do NOT spawn the daemon loop or any subprocess.

## TASK 2 -- IMPL (harness_self_fix), id: daemon-idle-sleep-cap-impl

- meta_task_type: harness_self_fix
- mutation_target: harness.autowork_daemon  (bare dotted MODULE only)
- files_touched: [harness/autowork_daemon.py]
- dependencies: [daemon-idle-sleep-cap-oracle]
- priority: high
- verification_command: python -m pytest tests/harness/test_daemon_idle_sleep_cap.py -q
- REQUIRES an operator decision file
  `state/control/decisions/daemon-idle-sleep-cap-impl.json` even under
  auto-approve, because `harness/autowork_daemon.py` is in `_NEVER_AUTO_APPROVE`
  (orchestrator.py:2577); `operator_decision_required: true` and
  `auto_approve_requested: true` are set in this brief's frontmatter.
- spec.non_goals MUST include a verbatim entry containing the literal word
  `integration` (see ★CRITICAL above). This is REQUIRED: `integration_tests` is
  empty for this in-place harness edit, and `missing_integration_test`
  (plan_validator.py:250-256) only excuses the empty list when some
  `spec.non_goals` entry lowercased contains the substring `integration`.
- spec.test_spec MUST cover the declared edge cases with concrete regression
  tests. `missing_edge_case_tests` (plan_validator.py:257-263,
  `needed = min(2, len(edge_cases))`) fires on this NON-`test_authoring` task and
  FAILS the plan unless `len(property_tests) + len(regression_tests) >= needed`.
  The helper branches on real edge cases -- (a) a retry-eligible blocked task with
  an elapsed-vs-pending backoff window and (b) an exhausted / empty case yielding
  None -- so the synthesized `test_spec.regression_tests` MUST carry at least 2
  concrete regression tests (`>= min(2, len(edge_cases))` across
  `regression_tests` + `property_tests`), e.g.:
  - `test_soonest_deadline_caps_below_heartbeat` -- one retry-eligible blocked
    task (attempts=1, recent ts) yields a deadline whose derived cap is strictly
    less than the 1800s heartbeat.
  - `test_no_eligible_blocked_returns_none` -- empty / all-exhausted blocked dir
    yields None so the cap is a no-op and the full heartbeat is preserved.
  These are genuine coverage of the helper's real branches, NOT a validation
  workaround.

Implement the additive idle-sleep cap exactly as the Deliverables / Inputs
specify, via a single `__JANUSMASK_PATCHES__` payload with TWO `kind:'symbol'`
patches: (1) a NEW top-level helper `_soonest_blocked_retry_deadline`, anchored
on the existing top-level `_retry_blocked_tasks`; (2) the existing top-level
`run_daemon` patched to cap `sleep_target` when `is_idle`. Both are top-level
symbols -> direct symbol patches (no R-anchor / no nesting). The
`_retry_blocked_tasks` re-stage / exhaust / backoff semantics, the non-idle
`poll` branch, and the early-wake mtime-watch loop MUST stay byte-identical in
behavior. The `verification_command` substring-contains the oracle test path, so
this is a fix-forward redpair and the impl is verified by the oracle's OWN
authored file. Do NOT use the broad adversarial suite (it is non-hermetic and
flakes in the staging worktree, which would wrongly block the `harness_self_fix`
jail gate).
