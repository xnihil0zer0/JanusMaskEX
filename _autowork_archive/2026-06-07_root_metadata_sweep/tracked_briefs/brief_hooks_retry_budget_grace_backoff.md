---
interfaces: "modifies the tiered-threshold logic inside `harness/autowork_daemon._recently_failed_to_plan` (module-level function); no signature change, no new symbols, no other functions touched"
---

# Title

Give the planner-kickoff backoff a grace retry budget of 2 before escalation begins

# Scope

`harness/autowork_daemon._recently_failed_to_plan` currently escalates the
plan-attempt cooldown from the FIRST failure: `attempts <= 1 -> 300s`,
`attempts == 2 -> 3600s`, `attempts >= 3 -> 86400s` (harness/autowork_daemon.py
around lines 1213-1219). Planner kickoffs fail *stochastically* (dual-agent
reconciliation flakes), so penalising the first two failures with a cooldown
sends unlucky-but-recoverable briefs into the 1-day tier and stalls the run.

Change ONLY the threshold-selection block so there is a GRACE RETRY BUDGET OF 2
before any backoff, then the same escalation shifted up by two attempts:

- `attempts <= 2` -> `threshold = 0.0`   (within the grace budget: retry now)
- `attempts == 3` -> `threshold = 300.0`
- `attempts == 4` -> `threshold = 3600.0`
- `attempts >= 5` (else) -> `threshold = 86400.0`

The final `return time.time() - last_ts < threshold` is UNCHANGED (with
`threshold == 0.0` the expression is always False, i.e. always retriable).
Every other line of the function — the marker read, JSON parse, the
`last_ts`/`attempts` type guards that `return False` on malformed input — MUST
remain byte-identical. No new module-level symbol; no signature change.

# Required plan shape

EXACTLY ONE task. `meta_task_type: harness_self_fix` (the target file
`harness/autowork_daemon.py` is on the irreducible `_NEVER_AUTO_APPROVE`
deny-list, so this is the sanctioned self-fix landing path + an operator
decision file). `mutation_target: harness/autowork_daemon.py`. A single-symbol
partial edit of the existing function `_recently_failed_to_plan` only (the
function is small — replace its body's threshold block; do NOT whole-file edit
the module). `verification_command:
python -m pytest tests/adversarial/test_escalating_backoff_recently_failed_to_plan.py -q`.
No second task; no test-authoring task (the oracle is already committed).

# Non-Goals

Do NOT change the function signature or the marker file format
(`{"attempts": int, "last_ts": float}`, `.json` suffix). Do NOT alter the
malformed-input guards (missing `last_ts`, bool/non-numeric `last_ts`,
bool/non-int `attempts` all still `return False`). Do NOT touch
`_plan_attempt_marker_path`, `_auto_promote`, or any other symbol. Do NOT add a
config flag. Do NOT whole-file edit `harness/autowork_daemon.py` (it is large;
edit only the one function). Do NOT modify the task build-retry budget (a
separate mechanism) — this brief is only the plan-kickoff cooldown.

# Inputs

`harness/autowork_daemon.py` `_recently_failed_to_plan` (the threshold tiers at
~lines 1213-1219 and the trailing `return time.time() - last_ts < threshold`).
The committed RED oracle
`tests/adversarial/test_escalating_backoff_recently_failed_to_plan.py` pins the
exact new tiers (grace budget of 2; 3 ->300s; 4 ->3600s; 5+ ->86400s) and is
the authoritative contract.

# Deliverables

The single-symbol edit to `_recently_failed_to_plan` implementing the
grace-budget tiers above, landing green against the committed oracle.
IMPLEMENTATION CONSTRAINTS to emit as implementation_notes: deny-listed target
=> meta_task_type harness_self_fix + operator writes
`state/control/decisions/<tid>.json` approve; oracle-first (already committed);
single-symbol partial edit only, never whole-file; verification_command is the
committed oracle file only (no network, no pip, no glob of tests/planner/).
