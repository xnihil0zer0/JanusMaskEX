---
working_dir: /home/xnihil0zer0/JanusMaskJR
required_task_ids:
  - daemon-wake-oracle
interfaces: "tests/test_daemon_backoff_wake.py — a standalone RED test_authoring oracle for the (not-yet-existing) pure helper harness.autowork_daemon._next_pending_wake. RED-by-absence on HEAD; the daemon-wake-impl task makes it GREEN later."
---

# Title

RED oracle for the daemon backoff-aware idle-wake helper `_next_pending_wake`.

# Scope

Author ONE new test file `tests/test_daemon_backoff_wake.py` (a `test_authoring`
oracle, mutation_target `harness.autowork_daemon`). It pins the contract of a
pure helper `_next_pending_wake(state_dir, config, now=None) -> float` that does
NOT yet exist on HEAD — so every test is RED-by-absence now and GREEN once the
helper is implemented (separate `daemon_backoff_aware_wake` impl brief).

`_next_pending_wake` returns the seconds until the daemon's soonest pending TIMED
work, mirroring `_retry_blocked_tasks` eligibility EXACTLY, floored at `1.0`,
capped at `heartbeat = _heartbeat_interval(config)`:
- scans `state_dir/tasks/blocked/*.json` (ignoring `*.retry.json`); per task id
  `tid`, reads `blocked/<tid>.retry.json` `{attempts, ts, last_outcome}`;
- skips tasks with a `blocked/<tid>.exhausted` marker, and tasks whose
  `attempts >= effective_max` where `effective_max = 1` if `last_outcome in
  ('synthesis_or_ast_failed','embedded_tests_failed','narrow_fuzz_failed')` else
  `3`;
- backoff `threshold`: `attempts <= 1 -> 300.0`, `== 2 -> 3600.0`, else `86400.0`;
  `remaining = threshold - (now - ts)`;
- result = `min(heartbeat, max(1.0, min(remaining over still-retryable tasks)))`;
  `heartbeat` when no still-retryable blocked task exists.

The oracle MUST construct a temp state dir with `tasks/blocked/` sidecars to drive
each case deterministically (pass an explicit `now` and a `config` dict with a
known `autowork.heartbeat_sec`).

# Inputs

- `harness/autowork_daemon.py:883-971` — `_retry_blocked_tasks`, the eligibility
  logic the helper mirrors (exhausted skip, sidecar read, deterministic outcomes,
  effective_max, backoff tiers).
- `harness/autowork_daemon.py:98-101` — `_heartbeat_interval(config)`.
- The helper is NOT on HEAD: `from harness.autowork_daemon import _next_pending_wake`
  raises ImportError today → that is the intended RED-by-absence state.

# Deliverables

`tests/test_daemon_backoff_wake.py` containing at least these cases (each RED on
HEAD because `_next_pending_wake` is absent, GREEN after the impl lands):
- empty / absent `blocked/` → returns `heartbeat`.
- one blocked task `attempts=1, ts=now` → returns `300.0`.
- one blocked task `attempts=1, ts=now-290` → returns `~10.0` (abs diff < 1.5).
- one blocked task `attempts=1, ts=now-400` (already eligible) → returns `1.0`.
- one blocked task `attempts=2, ts=now` with `heartbeat >= 3600` → returns `3600.0`.
- a `<tid>.exhausted` marker present → that task ignored (returns `heartbeat`
  when it is the only one).
- `last_outcome='narrow_fuzz_failed'`, `attempts=1` → effective_max 1 → ignored.
- two blocked tasks → returns the SOONER remaining.
- result always satisfies `1.0 <= r <= heartbeat`.

# Non-Goals

- Does NOT implement `_next_pending_wake` and does NOT edit
  `harness/autowork_daemon.py` — this brief authors ONLY the test file. The impl
  is the separate `daemon_backoff_aware_wake` brief.
- Does NOT touch any other file. Cross-module `integration` testing is out of
  scope and excused (this is a unit oracle).

# Required plan shape

Emit EXACTLY ONE task.
- task_id MUST be exactly `daemon-wake-oracle`.
- meta_task_type: test_authoring
- mutation_target: harness.autowork_daemon   (dotted MODULE only)
- files_touched: ["tests/test_daemon_backoff_wake.py"]
- It is RED-by-absence on HEAD (`_next_pending_wake` does not exist) — that RED
  is correct and expected for a test_authoring oracle.
- verification_command: python -m pytest tests/test_daemon_backoff_wake.py -q
- non_goals MUST contain the literal word `integration`.
- This is a STANDALONE oracle: there is NO impl task in this plan; do NOT add one.
