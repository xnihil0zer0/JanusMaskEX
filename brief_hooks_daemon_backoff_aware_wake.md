---
working_dir: /home/xnihil0zer0/JanusMaskJR
interfaces: "harness/autowork_daemon.py — add a pure helper `_next_pending_wake(state_dir, config, now=None) -> float` and wire it into run_daemon's idle-sleep so an idle daemon NEVER sleeps past a blocked task whose retry-backoff window is about to elapse. Two single-file leaves (oracle + impl). harness_self_fix; autowork_daemon.py is _NEVER_AUTO_APPROVE trust-core (operator decision file required)."
---

# Title

Backoff-aware idle wake — the daemon must never sleep through pending timed work.

# Scope

The daemon's idle sleep is a flat `heartbeat` (1800s). It only wakes early on an
allowlist/brief mtime change (`_autowork_watch_mtime`). It is **blind to its own
pending timed work**: a blocked task whose retry-backoff window
(`_retry_blocked_tasks` tiers: attempts ≤1 → 300s, ==2 → 3600s, else → 86400s,
measured from the sidecar `ts`) elapses in 300s is slept past for the full 1800s.
The result is a daemon that "waits around for half an hour doing nothing" while a
ready retry sits eligible — the exact failure observed at
`harness/autowork_daemon.py:2406` (`sleep_target = heartbeat if is_idle else poll`).

Fix it STRUCTURALLY so submitting work is sufficient and the daemon self-paces:
when idle, the sleep is capped at the soonest moment the daemon has timed work to
do, so it wakes exactly when a retry becomes eligible — never sooner (no
hammering), never a heartbeat too late.

Two single-file leaves (each touches exactly ONE file → R-anchor patch /
test-authoring path, NEVER a whole-file rewrite of the 2972-line daemon):

C1 — New PURE helper `_next_pending_wake(state_dir, config, now=None) -> float`
in `harness/autowork_daemon.py`. Returns the number of seconds until the daemon's
soonest pending TIMED event, floored at `1.0` and capped at `heartbeat`. It MUST
mirror `_retry_blocked_tasks` eligibility EXACTLY:
- Scan `state_dir/tasks/blocked/*.json` (skip names ending `.retry.json`).
- For each task id `tid`: skip if `blocked/<tid>.exhausted` exists.
- Read `blocked/<tid>.retry.json` for `{attempts, ts, last_outcome}` (defaults
  `0, 0.0, ''` when absent/corrupt, mirroring lines 914-925).
- `_DETERMINISTIC_OUTCOMES = ('synthesis_or_ast_failed','embedded_tests_failed','narrow_fuzz_failed')`;
  `effective_max = 1 if last_outcome in _DETERMINISTIC_OUTCOMES else max_attempts`
  (default `max_attempts=3`). Skip tasks with `attempts >= effective_max` (already
  exhausted — they will never re-stage).
- Backoff `threshold`: `attempts <= 1 → 300.0`, `attempts == 2 → 3600.0`, else
  `86400.0`. `remaining = threshold - (now - ts)`.
- The helper's result = `min(heartbeat, max(1.0, min(remaining over all
  still-retryable tasks)))`; if there are NO still-retryable blocked tasks, return
  `heartbeat`. `now` defaults to `time.time()` when None; `heartbeat` comes from
  `_heartbeat_interval(config)`. Never returns < 1.0 or > heartbeat.

C2 — Wire it into the idle sleep. In `run_daemon`
(`harness/autowork_daemon.py:2297-2431`) replace the single line at 2406
`sleep_target = heartbeat if is_idle else poll`
with
`sleep_target = _next_pending_wake(state_dir, config) if is_idle else poll`.
NOTHING else in run_daemon changes — the 0.5s-step mtime-watch loop (2408-2415),
drain, and watchdog all stay byte-identical.

# Inputs

Verified anchors on HEAD:
- `harness/autowork_daemon.py:883-971` — `_retry_blocked_tasks`: the eligibility
  logic to mirror (exhausted skip 911-912; sidecar read 913-925; deterministic
  outcomes + `effective_max` 926-927; `attempts >= effective_max` skip 928-951;
  backoff tiers 952-957; `time.time() - last_ts < threshold` 958-959).
- `harness/autowork_daemon.py:2406` — the defect line
  `sleep_target = heartbeat if is_idle else poll`.
- `harness/autowork_daemon.py:2297` — `def run_daemon(...)` (≈135 lines, ends
  before `def main` at 2432). Reproduce it VERBATIM in the C2 symbol patch except
  the single line 2406.
- `harness/autowork_daemon.py:98-101` — `_heartbeat_interval(config)`; `:89-96`
  `_poll_interval(config)`. Use `_heartbeat_interval` inside the new helper.
- `import time`, `import json`, `import pathlib` already at module top.

# Deliverables

1. The C1 helper + C2 one-line wiring, landed via the R-anchor patch path (impl
   leaf is single-file `harness/autowork_daemon.py`; add `_next_pending_wake` as
   the R-anchor extra node before `run_daemon`, and reproduce `run_daemon` as the
   symbol patch carrying ONLY the line-2406 change). Do NOT reproduce the whole
   file; do NOT emit `__JANUSMASK_MANIFEST__`.

2. A pipeline-authored RED oracle `tests/test_daemon_backoff_wake.py`
   (test_authoring; mutation_target `harness.autowork_daemon`) — each test fails
   on HEAD (the helper does not exist) and passes after:
   - empty / absent `blocked/` → returns `heartbeat`.
   - one blocked task `attempts=1, ts=now` → returns `300.0`.
   - one blocked task `attempts=1, ts=now-290` → returns `~10.0` (±1).
   - one blocked task `attempts=1, ts=now-400` (already eligible) → returns `1.0`
     (the floor).
   - one blocked task `attempts=2, ts=now` → returns `3600.0` (capped at
     heartbeat if heartbeat<3600 — use a config with heartbeat≥3600 for this case
     OR assert `min(heartbeat,3600.0)`).
   - a `<tid>.exhausted` marker → that task is ignored (returns `heartbeat` when
     it is the only one).
   - `last_outcome='narrow_fuzz_failed'` at `attempts=1` → `effective_max=1` →
     ignored (returns `heartbeat` when alone).
   - two blocked tasks → returns the SOONER remaining.
   - result is always `1.0 <= r <= heartbeat`.
   - WIRING: `run_daemon`'s source contains `_next_pending_wake(` and no longer
     contains `sleep_target = heartbeat if is_idle else poll` (source-inspection
     assertion, mirroring tests/test_partial_edit_prompt_r_anchor_wired.py).

3. Anti-seesaw — keep these green (the change must not alter retry semantics or
   the idle classification):
   - tests covering `_retry_blocked_tasks` / blocked-retry backoff (run
     `python -m pytest tests/ -k "retry_blocked or blocked_retry or backoff or daemon_idle or autowork_daemon" -q` and keep all currently-green selections green).

# Non-Goals

- This brief covers ONLY blocked-task retry eligibility. Plan-park backoff
  (`_recently_failed_to_plan`) wake-awareness and brief-resubmit state auto-clean
  are explicitly out of scope here — they are separate follow-up briefs. The word
  `integration` appears here to excuse the cross-module integration-test
  requirement; this is a unit-scoped pure-helper change.
- Does NOT change `_retry_blocked_tasks`, the backoff tiers, the heartbeat/poll
  config, or the mtime-watch wake. It only CAPS the idle sleep duration.
- Does NOT touch any file other than `harness/autowork_daemon.py` and the one new
  test file. No manifest, no whole-file daemon rewrite.

# Required plan shape

Emit EXACTLY TWO single-file tasks.

TASK 1 — oracle:
- task_id MUST be exactly `daemon-wake-oracle`.
- meta_task_type: test_authoring
- mutation_target: harness.autowork_daemon   (dotted MODULE only)
- files_touched: ["tests/test_daemon_backoff_wake.py"]
- RED-by-absence on HEAD (`_next_pending_wake` does not exist).
- verification_command: python -m pytest tests/test_daemon_backoff_wake.py -q
- non_goals MUST contain the literal word `integration`.

TASK 2 — impl (depends on TASK 1):
- task_id MUST be exactly `daemon-wake-impl`.
- dependencies: ["daemon-wake-oracle"]
- meta_task_type: harness_self_fix   (writes harness/autowork_daemon.py)
- files_touched: ["harness/autowork_daemon.py"]   (SINGLE FILE → R-anchor patch)
- Emit `__JANUSMASK_PATCHES__`: ONE symbol patch on `run_daemon` (verbatim except
  line 2406) that ALSO carries `_next_pending_wake` as an R-anchor extra node
  inserted before `run_daemon`. Do NOT emit `__JANUSMASK_MANIFEST__`.
- OMIT mutation_target.
- verification_command: python -m pytest tests/test_daemon_backoff_wake.py -q
- non_goals MUST contain the literal word `integration`; regression_tests >= 2.

Both tasks: working_dir /home/xnihil0zer0/JanusMaskJR. NOTE: harness/autowork_daemon.py
is _NEVER_AUTO_APPROVE trust-core → the impl leaf needs an operator decision file
`state/control/decisions/daemon-wake-impl.json`, and the daemon must be restarted
(supervisor-respawn) after landing for the new idle-sleep to go live.
