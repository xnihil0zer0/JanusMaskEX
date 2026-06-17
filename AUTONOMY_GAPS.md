# Autonomy Gaps — Hands-Off Lifecycle Audit (2026-06-16)

Adversarial trace of the JanusMask factory's hands-off lifecycle. Each entry is a
point where the pipeline **requires a human operator** or can **silently
wedge/stall/mislead** without surfacing a clear signal. Every such point is a
GAP = a BUG. Ordered by severity. Each gap is scoped to become a bug brief
(meta_task_type noted where it would be `harness_self_fix`).

Lifecycle stages walked: brief intake/validation → promotion/allowlist gating →
planning (synthesis + plan validation + deterministic park) → dispatch → worker
→ submission/AST-merge → verification_command → auto_commit/rollback → post-run
(archive, blocked-retry, inactivity watchdog, self-heal) → process/operational
(supervisor, code-cache, pause, disk, locks, quarantine).

---

## GAP 1 — Malformed brief is mislabeled as a "planner hallucination" and silently parked forever
- **Stage:** Brief intake / planning
- **Severity:** CRITICAL (operator's own input is silently swallowed; no actionable signal)
- **Evidence:**
  - `harness/planner/brief_loader.py:187-188` — `load_brief` raises `BriefValidationError('Validation failed', missing=…, empty=…)` when a REQUIRED_SECTION (`REQUIRED_SECTIONS` = `{title, scope, non_goals, inputs, deliverables}`, line 55) is missing/empty.
  - `harness/planner/cli.py:303-306` — the planner subprocess catches that, prints `Brief load failed: {e}` to stderr and `sys.exit(3)`. The error text therefore contains the literal `Validation failed`.
  - `harness/autowork_daemon.py:1605-1614` — daemon reads the (absent) output plan → empty dict → `_check_hallucination(...)` returns `(True, 'empty_plan')` (`harness/autowork_daemon.py:1336-1338`).
  - `harness/autowork_daemon.py:1636-1638` — because `stderr_tail` contains `'validation failed'`, the park marker is written with `deterministic: true`.
  - `harness/autowork_daemon.py:1645` — emits the GENERIC `planner_hallucination_discarded` event. There is **no** distinct malformed-brief signal.
  - `harness/autowork_daemon.py:1274-1276` — once `deterministic and attempts >= 1`, `_recently_failed_to_plan` parks the slug for **86400s (24h)**; `harness/autowork_daemon.py:1567-1568` skips it on every iteration. (Only a brief-file mtime bump re-arms it: `harness/autowork_daemon.py:1260-1267`.)
- **Failure scenario:** Operator authors `brief_hooks_foo.md` but forgets a `## Non-Goals` heading. The daemon runs the planner once, the brief fails the load schema, and the daemon records it as a *planner hallucination* with a *deterministic 24h park*. The operator sees a generic "hallucination discarded" row indistinguishable from a real Gemini-only/empty-plan hallucination, gets **zero** indication that THEIR brief is malformed or WHICH section is missing, and the brief never plans again for 24h. The malformed brief is indistinguishable from pipeline noise.
- **Fix (harness_self_fix):** In `_run_planner_subprocess` / the park path, detect the brief-load-failure case distinctly. Cheapest: before invoking the planner, the daemon should call `harness.planner.brief_loader.load_brief` on the candidate brief (or have the CLI exit with a dedicated rc, e.g. `4`, for `BriefValidationError` vs `3` for other load errors, carrying the `missing`/`empty` lists on stderr as JSON). On that signal:
  1. Write `state/control/autowork/malformed_briefs/<slug>.json` with the exact validation error (`{missing:[…], empty:[…], brief_path, ts}`).
  2. Emit a distinct telemetry event `brief_malformed` (NOT `planner_hallucination_discarded`).
  3. Do **not** write a `deterministic:true` 24h park (a malformed brief is an operator-fixable input error, not a planner defect). The existing mtime-bump re-arm (line 1260) already clears it once the operator edits the file.
  4. Surface the malformed-brief set in the WebUI/idle telemetry so it is loud.

---

## GAP 2 — Blocked-retry time-bomb: a withdrawn brief's tasks re-run from `state/tasks/blocked/` regardless of allowlist / brief presence
- **Stage:** Post-run (blocked-task handling + retry)
- **Severity:** CRITICAL (autonomy-violating: a deliberately withdrawn task resurrects itself; operator must hand-write a marker to stop it)
- **Evidence:**
  - `harness/autowork_daemon.py:883-971` (`_retry_blocked_tasks`) — globs `state/tasks/blocked/*.json` (line 899) and re-stages each (`p.rename(dest)`, line 964) under a budget of `max_attempts=3` (line 883) with escalating backoff (lines 952-957). The **only** gates are: `.exhausted` marker (line 911), `.retry.json` sidecar (line 904), per-task budget (line 928), backoff window (line 958), and `dest.exists()` (line 961).
  - There is **no** consultation of `_auto_promote_allowlist` (`harness/autowork_daemon.py:2568`) and **no** check that the source brief still exists. `_auto_promote_brief_eligible` (`harness/autowork_daemon.py:2621`) gates *promotion/planning* but is **never** consulted in the blocked-retry path.
  - The only way to stop it is the manual `<tid>.exhausted` marker the code itself respects (`harness/autowork_daemon.py:911`, `929-932`) — i.e. the documented operator workaround.
- **Failure scenario:** Operator removes a brief from `auto_promote.allowlist` and moves the brief file aside to abandon a line of work. Any of that brief's tasks already in `blocked/` will be re-dispatched up to 3 more times (with up to 24h backoff between attempts), spawning workers and consuming the parallel cap against a brief the operator deliberately withdrew. The withdrawal does not take effect; the operator must manually write `<tid>.exhausted` for every stranded task.
- **Fix (harness_self_fix):** Add an automatic blocked-task hygiene stage to `_retry_blocked_tasks` (or a sibling helper called from `_iteration`): before re-staging a blocked `<tid>.json`, resolve its source brief slug (the task JSON already carries provenance / the plan path) and verify (a) the slug is still allowlisted via `_auto_promote_allowlist`, and (b) the brief file still exists on disk. If either fails, **quarantine** the blocked task to `state/tasks/blocked/withdrawn/` (or write `<tid>.exhausted` automatically) and emit a `blocked_task_withdrawn` telemetry row instead of re-staging. This makes brief withdrawal self-handling — no hand-written marker.

---

## GAP 3 — Daemon caches harness code at startup; a landed harness fix is not live until a manual supervisor restart, and nothing restarts it
- **Stage:** Process / operational
- **Severity:** HIGH (every harness_self_fix that lands is inert until an operator restarts; the daemon keeps running the OLD buggy logic, masking the fix)
- **Evidence:**
  - `harness/autowork_daemon.py:2298-2415` (`run_daemon`) is a single long-lived `while not _shutdown_requested:` loop. Python imports `harness.*` at process start; the loop never reloads any module and never re-execs.
  - `scripts/run-autowork.sh:108-152` — the supervisor only re-launches the daemon **when the child dies** (`wait "${DAEMON_PID}"` then respawn). A committed harness change does not kill the daemon, so it is never picked up. No HEAD/sha watch exists anywhere in the supervisor or the daemon (grep for `rev-parse`/`harness_sha`/`reload`/`restart` in `harness/autowork_daemon.py` finds only the push-pin check at 2210 and orphan-resume at 2327 — none restart on code change).
  - The worker subprocesses (`orchestrator_worker`) are spawned fresh per task and DO see new code; only the **daemon's own** dispatch/promote/retry/watchdog logic is stale. So a fix to (e.g.) `_retry_blocked_tasks` or `_check_hallucination` lands green but the live daemon keeps running the pre-fix version indefinitely.
- **Failure scenario:** A harness_self_fix corrects a daemon-side bug (e.g. GAP 1 or GAP 2). The fix commits, oracles go green, the brief archives — but the live daemon process imported the old `autowork_daemon.py` at startup days ago. The bug keeps biting; the operator believes it is fixed. This silently defeats the entire self-healing premise for any daemon-resident defect.
- **Fix:** Add auto-restart-on-harness-change. Two complementary pieces:
  1. **Daemon self-exit on harness drift:** at the top of each `run_daemon` loop iteration, compare the git HEAD sha (or an mtime hash of `harness/**` + `config/**`) against the sha/hash captured at `_daemon_start_time`. On drift, drain (`_drain_running`) and `sys.exit(0)` cleanly with a `harness_changed_restart` telemetry row. The supervisor's existing `wait`→respawn loop (`scripts/run-autowork.sh:108`) then relaunches with fresh code. Gate behind a config flag (default on) so tests can pin it.
  2. **Supervisor sha-stamp (belt-and-suspenders):** have `run-autowork.sh` record the launched HEAD and, after each `wait`, refuse to treat a same-second exit as a crash-loop when HEAD has advanced.

---

## GAP 4 — Trust-core harness files can NEVER be auto-approved → harness_self_fix to them fails closed forever until the operator drops a decision file
- **Stage:** Auto-commit / submission validation
- **Severity:** HIGH (the most critical self-healing target — the daemon/orchestrator/jail themselves — is the one class that cannot self-heal)
- **Evidence:**
  - `harness/orchestrator.py:2282` — `_NEVER_AUTO_APPROVE` = `('harness/agent_jail.py', 'harness/dbus_proxy.py', 'harness/paths.py', 'harness/git_integration.py', 'harness/orchestrator.py', 'harness/interceptors.py', 'harness/selfheal.py', 'harness/autowork_daemon.py', 'services/**')`.
  - `harness/orchestrator.py:2246-2247` — `_auto_approve_sensitive_eligible` returns `False` for any path matching `_NEVER_AUTO_APPROVE`, even with `auto_approve_sensitive_harness` on.
  - `harness/orchestrator.py:2778, 2284-2301` — the only remaining approval path is `_apply_approval_granted`, which reads `state/control/decisions/<task_id>.json` and returns True only on an explicit operator `approve`/`approved`. Absent → False → the commit fails closed → `auto_commit_failed` retries to exhaustion (then GAP 7).
- **Failure scenario:** A bug in `autowork_daemon.py` or `orchestrator.py` (i.e. exactly GAPs 1–3) is fixed via a `harness_self_fix` brief. The submission is correct and tests pass, but the apply targets a `_NEVER_AUTO_APPROVE` path, so it can never auto-commit. It silently dead-ends at `auto_commit_failed` until an operator manually writes a decision file. The pipeline cannot self-heal its own core, which is precisely where these autonomy bugs live.
- **Fix:** This is a deliberate safety boundary, so the fix is to make the *blocked-on-operator* state **loud and self-surfacing**, not to remove the gate. When a submission for a `_NEVER_AUTO_APPROVE` path is accepted but cannot auto-approve, write `state/control/decisions_pending/<task_id>.json` with the diff summary + target path + reason, emit a distinct `trustcore_decision_required` telemetry row, and surface it in idle telemetry / WebUI as a standing operator action item (instead of silently looping `auto_commit_failed`). Optionally: a per-task `await_decision` with `emit_pending` so the pending decision is visible the moment the task is accepted.

---

## GAP 5 — Inactivity watchdog escalates exactly ONCE, then never re-fires; and the self-heal it spawns can deadlock ALL dispatch
- **Stage:** Post-run (inactivity watchdog + self-heal)
- **Severity:** HIGH (the last-line "we're stuck" safety net mutes itself, and can actively cause the inactivity it is meant to cure)
- **Evidence:**
  - `harness/autowork_daemon.py:2933-2942` — once `is_stuck`, it writes `state/control/autowork/inactivity_escalated.json` and escalates. On every subsequent iteration `if not marker_path.exists()` (line 2936) is False, so it **never escalates again** while the marker is present. The marker is only cleared when the daemon later observes `not is_stuck` (line 2947-2949) or at startup (line 2331-2333). If the system stays stuck, the watchdog stays silent after one shot.
  - `harness/autowork_daemon.py:2298-2333` — at startup the marker is unconditionally deleted, so the *only* automatic reset requires a daemon restart (which GAP 3 says does not happen on harness change).
  - **Known deadlock (MEMORY `selfheal-deadlock-blocks-all-dispatch.md`):** the spawned inactivity self-heal worker has empty `files_touched`, so the conservative `can_run_parallel` treats it as conflicting with EVERY real task → it blocks ALL dispatch → which *causes* further inactivity. The current live mitigation is a hand-placed `inactivity_escalated.json` suppression marker — an operator workaround, not a fix.
- **Failure scenario:** The pipeline genuinely wedges (e.g. all briefs blocked on GAP 4 decision files). The watchdog fires once, spawns a self-heal worker that itself blocks all dispatch, then goes silent. The operator sees one `inactivity_watchdog_triggered` row and then nothing, while the system is fully stalled and the self-heal worker is making it worse.
- **Fix (harness_self_fix):** (a) Re-arm the watchdog on an interval: re-emit `inactivity_watchdog_triggered` (and re-escalate under a bounded budget) every N minutes while still stuck, rather than one-shot on marker existence. (b) Give the inactivity self-heal worker a non-empty, narrowly-scoped `files_touched` (or exempt empty-`files_touched` self-heal tasks from the conservative `can_run_parallel` conflict set) so it cannot block all dispatch. (c) Escalate to a *loud operator alert* (not just a self-heal spawn) after the second consecutive stuck window.

---

## GAP 6 — Quarantined tasks/briefs have NO automatic recovery; the loop-spin circuit-breaker counter resets on every restart
- **Stage:** Dispatch (circuit breaker / quarantine)
- **Severity:** MEDIUM-HIGH (quarantine is a one-way trip requiring an operator; the breaker itself is restart-amnesiac)
- **Evidence:**
  - `harness/autowork_daemon.py:1984-2003` — the per-task dispatch circuit breaker uses the **module-global in-memory** `_dispatch_timestamps` (`harness/autowork_daemon.py:2692`). On 10 dispatches in 300s it moves the spec to `tasks/quarantine/<tid>.json` (line 1993) and emits `quarantine` (line 2003).
  - `_dispatch_timestamps` is reset to `{}` on every process start (module-level dict, line 2692) — so the loop-spin detector forgets all history across a daemon restart (GAP 3's restart, a crash respawn, or `--once`). A task that spins, gets the daemon restarted, and spins again is never caught.
  - Grep confirms **no** code re-stages or recovers anything from `tasks/quarantine/` or `state/control/autowork/quarantine/` (zombie-brief quarantine at `harness/autowork_daemon.py:1877-1882` is also terminal). Quarantine is purely terminal storage awaiting an operator.
- **Failure scenario:** A task with a subtly bad spec dispatch-spins, gets quarantined, and sits in `tasks/quarantine/` indefinitely with no telemetry follow-up and no auto-replan; its dependents hang the queue. An operator must notice the `quarantine` row, inspect, and decide to re-stage or abandon. Meanwhile a crash-respawn loop can let a different spinner evade the breaker because the counter reset.
- **Fix (harness_self_fix):** (a) Persist `_dispatch_timestamps` to `state/control/autowork/dispatch_counts.json` so the loop-spin detector survives restarts. (b) Wire quarantined tasks into the existing self-heal/autobrief escalation path (`_escalate_to_autobrief`) so a quarantined spec automatically produces a corrective brief instead of dead-ending, OR write a `quarantine_pending` operator action item that is surfaced in idle telemetry. Either way, quarantine must not be a silent terminal sink.

---

## GAP 7 — `auto_approve_sensitive_ceiling` (default 3) exhausts → every later sensitive harness fix silently fails closed
- **Stage:** Auto-commit
- **Severity:** MEDIUM (a slow-burn fuse: the Nth+1 harness fix stops auto-committing with no obvious signal)
- **Evidence:**
  - `harness/orchestrator.py:2256-2278` — `_auto_approve_sensitive_eligible` returns False once the persisted count in `state/control/autowork/auto_approve_count.json` reaches the ceiling (default 3, line 2256). The counter is incremented per successful auto-approved commit (`harness/orchestrator.py:2846-2857`) and is **never automatically reset**.
  - After exhaustion, a sensitive (non-trust-core) harness fix falls back to `_apply_approval_granted` (operator decision file) — same fail-closed dead-end as GAP 4, but reached silently after the budget burns down.
- **Failure scenario:** A multi-leaf harness epic lands its first 3 sensitive fixes via auto-approve, then the 4th silently cannot commit and loops `auto_commit_failed` with no distinct "ceiling exhausted" signal to the operator. The operator sees retry churn but not the cause.
- **Fix (harness_self_fix):** When the ceiling blocks an otherwise-eligible auto-approve, emit a distinct `auto_approve_ceiling_exhausted` telemetry row and write a `decisions_pending` action item (as in GAP 4) so the block is visible. Consider a config option to auto-reset the counter on a clean push/integrate (the counter exists to bound a runaway burst, not to permanently cap a healthy session).

---

## GAP 8 — Self-heal runaway ceiling (default 50) is operator-reset-only; on trip, all further escalations are silently dropped
- **Stage:** Post-run (self-heal)
- **Severity:** MEDIUM
- **Evidence:**
  - `harness/autowork_daemon.py:756-770` (and the comment at 748-755) — `runaway_ceiling.json` persists the global self-heal escalation count; the comment states **"RESET POLICY: operator-cleared only — delete runaway_ceiling.json to reset the counter; there is no automatic reset."**
  - On trip, `_escalate_to_autobrief` emits `runaway_ceiling_tripped` and `return`s (drops the escalation). After 50 lifetime escalations, **no** task ever gets a corrective self-heal again until an operator deletes the file.
- **Failure scenario:** Over a long unattended run the cumulative escalation count crosses 50. From then on, every retry-exhausted task is silently denied a corrective self-heal — the self-healing loop is globally off, and the operator only learns this by spotting a `runaway_ceiling_tripped` row buried in telemetry.
- **Fix (harness_self_fix):** Add a bounded automatic reset (e.g. decay the counter on each clean integrate/push, or reset on a rolling time window) so a healthy long run is not permanently capped. When tripped, escalate to a loud operator alert (idle-telemetry action item) rather than a silent drop.

---

## GAP 9 — Retry-exhaustion produces a corrective self-heal brief that requires operator allowlist promotion to ever run
- **Stage:** Post-run (retry-exhausted → self-heal)
- **Severity:** MEDIUM (the corrective output of self-healing is itself gated behind an operator action)
- **Evidence:**
  - `harness/autowork_daemon.py:843` — the self-heal prompt explicitly instructs the agent: *"Do NOT edit the auto-promote allowlist … promotion is an operator decision. The corrected spec re-stages under the ORIGINAL task_id for operator review."* The comment at `harness/autowork_daemon.py:833-838` confirms promotion is an operator decision.
  - So after a task exhausts its budget (`_retry_blocked_tasks` → `_escalate_to_autobrief`, lines 935-937), the self-heal worker writes a corrected brief to its outbox, but that brief will not be promoted/planned unless an operator allowlists its slug (`_auto_promote_brief_eligible`, `harness/autowork_daemon.py:2621`).
- **Failure scenario:** The pipeline correctly diagnoses a failure and writes a fixed brief, then waits indefinitely for an operator to allowlist it. Unattended, the corrective loop never closes. The "self-heal" is really "self-diagnose-then-await-operator".
- **Fix:** This is partly an intentional safety posture (see MEMORY `selfheal-loop-closure-landed.md`, flag `selfheal_auto_promote` default false). The autonomy fix is to surface the awaiting-promotion corrective briefs as a loud, single operator action item (a `selfheal_promotion_pending` digest in idle telemetry / WebUI), AND to honor the existing `selfheal_auto_promote` flag end-to-end so an operator who opts into full autonomy gets a closed loop. Today the awaiting-promotion state is effectively invisible.

---

## GAP 10 — No disk-space preflight anywhere; ENOSPC degrades into a fleet of swallowed OSErrors and a silent stall
- **Stage:** Process / operational
- **Severity:** MEDIUM
- **Evidence:**
  - Grep for `statvfs` / `disk` / `ENOSPC` / `free_space` across `harness/autowork_daemon.py` returns nothing — there is no disk preflight.
  - The codebase swallows `OSError` pervasively in the hot paths: e.g. park-marker writes (`harness/autowork_daemon.py:1599-1601`, `1638-1640`), telemetry emits, sidecar writes (`harness/autowork_daemon.py:931-934`), stage writes (`harness/autowork_daemon.py:1529-1534`). Under ENOSPC these all silently no-op.
- **Failure scenario:** The drive fills (huntr corpus, drive-backup, large worktrees — see MEMORY `backup-detach-fixes-systemic-autocommit.md`). Commits fail, markers don't persist (so retry budgets never advance → re-spin), telemetry stops being written — the daemon "runs" but accomplishes nothing, and the swallowed OSErrors hide the cause. The operator sees an idle-looking daemon with no error.
- **Fix (harness_self_fix):** Add a disk-space preflight at the top of `run_daemon`'s loop (`shutil.disk_usage(state_dir)`): when free space drops below a configurable threshold, emit a loud `low_disk` telemetry row, write a `state/control/autowork/low_disk.json` action item, and pause dispatch (decline to launch new workers) until space recovers — converting a silent stall into a visible, self-throttling state.

---

## GAP 11 — HITL `await_decision` returns `'timeout'` after 30 min; the timeout branch's behavior is a silent operator dependency
- **Stage:** Auto-commit (HITL gate)
- **Severity:** LOW-MEDIUM (only active when `control.require_approval` is configured, but then it is a hard operator dependency)
- **Evidence:**
  - `harness/control_gate.py:85-117` — `await_decision` blocks the worker up to `approval_timeout_sec` (default `DEFAULT_APPROVAL_TIMEOUT = 1800.0`, line 25) polling for `state/control/decisions/<task_id>.json`, then returns `'timeout'`.
  - `harness/orchestrator.py:3488, 3523, 3570` — three accept-round call sites consume this; a `'timeout'`/non-approve decision routes the round to rejected (`harness/orchestrator.py:3494, 3529, 3576`). The worker is **blocked for the full 30 min** per round waiting on a human.
- **Failure scenario:** If an operator enables `require_approval` for the `accepted` phase, every task stalls a worker for up to 30 minutes waiting for a decision file that never comes in an unattended run, then is rejected — wasting a worker slot and the run. The dependency on a human is total and the 30-min block is silent (only `approval_timeout` lifecycle rows surface, `harness/orchestrator.py:72-74`).
- **Fix:** Default-off is the current safety (`await_decision` short-circuits to `'auto'` when the phase is not in `require_approval`, `harness/control_gate.py:94-95`), so this only bites a misconfiguration. The autonomy fix: when `require_approval` is on AND the daemon is running unattended (no operator-presence heartbeat), emit a loud `approval_required_unattended` warning at daemon start, and make the timeout decision configurable (auto-reject vs auto-approve vs hold) rather than implicitly rejecting after a 30-min block.

---

## GAP 12 — Rollback failures leave the worktree "for operator review" with only a log line
- **Stage:** Auto-commit / rollback
- **Severity:** LOW-MEDIUM (rare, but when it fires the recovery is entirely manual and only logged, not surfaced as telemetry)
- **Evidence:**
  - `harness/orchestrator.py:2124` — on a rejected-commit rollback where a peer commit landed on top, the revert fails and the rejected commit is *"LEFT for operator review to avoid clobbering the peer commit"* — only a `logger.error`, no telemetry row, no action-item file.
  - `harness/orchestrator.py:2111, 2114, 2117, 2130, 2135, 2139` — multiple rollback failure branches log *"worktree may be in inconsistent state"* with no operator-visible signal beyond the log.
  - `harness/git_integration.py:1817` — stash-pop conflict recovery can `raise RuntimeError` routing to blocked/, leaving a HEAD reset that needs human verification.
- **Failure scenario:** A concurrency edge (peer commit between commit and rejection-rollback) leaves a rejected commit on the branch. Unattended, this commit silently ships in the next push (an unverified/rejected change in `origin/main`), and the only record is a buried `logger.error`. The operator never sees it unless they read logs.
- **Fix (harness_self_fix):** Every rollback-failure / inconsistent-worktree branch in `_rollback_rejected_commit` and the stash-pop recovery must emit a distinct telemetry row (`rollback_failed_operator_review`) AND write `state/control/autowork/operator_review/<task_id>.json` with the sha + reason, so the standing operator-action surface (shared with GAPs 4/6/7) captures it. Optionally pause auto-push while any `operator_review` item is outstanding so a rejected commit cannot escape to origin.

---

## Cross-cutting theme
Six of these gaps (1, 4, 6, 7, 9, 12) share one root deficiency: **the pipeline has no single, loud, operator-action surface.** Blocked-on-human states are scattered as silent fail-closed loops, buried `logger.error`s, or generic telemetry rows indistinguishable from noise. The highest-leverage structural fix is a single `state/control/autowork/operator_actions/` directory (malformed briefs, trust-core decisions, ceiling exhaustion, quarantine, awaiting-promotion, rollback review) that the daemon surfaces in idle telemetry and the WebUI — turning every silent operator dependency into a visible, enumerable queue. GAPs 2, 3, 5, 6(persist), 8, 10 are then independently self-handling once their hygiene/restart/reset logic is added.
