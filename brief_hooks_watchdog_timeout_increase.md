# Title

UPGRADE: Increase hardcoded sequential worker watchdog timeout in harness/autowork_daemon.py

# Scope

A single-file `harness_self_fix` that updates the hardcoded 900-second (15 minutes) sequential worker watchdog timeout inside `harness/autowork_daemon.py` to dynamically reference the configuration parameter `synthesis.timeout_seconds` (plus a buffer), with a minimum cap of 1800 seconds (30 minutes). This ensures that heavy tasks, such as the full suite acceptance test, are not killed prematurely by the daemon.

# Non-Goals

- Do NOT modify any file other than `harness/autowork_daemon.py`.
- Do not write integration tests for this configuration watchdog increase.

# Inputs

- `harness/autowork_daemon.py` — the autowork daemon supervisor code containing the hardcoded timeout.
- `plan_hooks_watchdog_timeout_increase.json` — the companion plan carrying the `WATCHDOG_TIMEOUT_INCREASE` task.

# Deliverables

- `harness/autowork_daemon.py` dynamically reading the synthesis timeout setting (with a buffer) and enforcing a minimum of 1800s.
- An `auto_commit` ledger row in `state/impl_progress.jsonl` and a new git commit scoped to `harness/autowork_daemon.py`.
