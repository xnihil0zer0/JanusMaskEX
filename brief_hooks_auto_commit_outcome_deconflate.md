---
working_dir: "/home/xnihil0zer0/JanusMaskJR"
priority: P1
meta_task_type: harness_self_fix
operator_decision_required: true
auto_approve_requested: true
required_task_ids:
  - auto-commit-deconflate-oracle
  - auto-commit-deconflate-impl
interfaces: >
  EDIT EXACTLY ONE existing file: harness/orchestrator_worker.py. Add TWO new top-level
  worker-local helpers and EDIT the four existing auto-commit-failure terminal call sites to
  record a SPECIFIC failure sub-reason. Goal: de-conflate the umbrella `auto_commit_failed`
  outcome (which today collapses three distinct failure modes — patch-apply failure,
  verification_failed, and a staging-worktree lifecycle failure) so an operator can read the
  SPECIFIC mode straight off the blocked sidecar `state/tasks/blocked/<id>.retry.json` and a
  dedicated ledger row, with NO grep of `state/impl_progress.jsonl`. The de-conflation is
  PURELY ADDITIVE — it records a new `blocked_reason` alongside the existing budget-affecting
  `last_outcome` (which is left byte-identical) so the daemon retry budget is unchanged. The new
  helpers are `_classify_auto_commit_failure(state_dir, task_id) -> str` and
  `_record_auto_commit_blocked_reason(state_dir, task_id, outcome, reason) -> None`.
---

# Title
De-conflate the umbrella `auto_commit_failed` outcome: record the SPECIFIC auto-commit failure mode on the blocked sidecar + ledger without changing the retry budget

# Scope
EDIT the EXISTING file `harness/orchestrator_worker.py` (READ it first). SINGLE FILE. This is a
sensitive-path edit (`harness/**`) but `harness/orchestrator_worker.py` is NOT in the irreducible
`_NEVER_AUTO_APPROVE` set (`harness/orchestrator.py:2358` — that tuple is
`harness/agent_jail.py, harness/dbus_proxy.py, harness/paths.py, harness/git_integration.py,
harness/orchestrator.py, harness/interceptors.py, harness/selfheal.py, harness/autowork_daemon.py,
services/**`), so no operator decision FILE is required, but the implementation task MUST be
`harness_self_fix`. Do NOT edit `harness/orchestrator.py`, `harness/git_integration.py`, or
`harness/autowork_daemon.py` — they are all `_NEVER_AUTO_APPROVE` and the entire fix fits in the
worker.

Three changes to that one file, emitted as `__JANUSMASK_PATCHES__` (symbol patches; NOT a manifest):

1. ADD a new top-level helper
   `_classify_auto_commit_failure(state_dir, task_id) -> str` that, fail-safe end to end, reads the
   canonical ledger `state_dir/'impl_progress.jsonl'` and returns ONE of the precise sub-reason
   strings below by finding the MOST-RECENT ledger row whose `task_id` matches `task_id` and whose
   `event` is one of the per-mode markers the lower layers ALREADY emit:
     * `auto_commit_patch_failed` — the patch-apply mode (git_integration.py:1331 already writes a
       row `{event:'auto_commit_patch_failed', file, reason}` on the `except (KeyError, ValueError)`
       at git_integration.py:1319-1334). Return `'auto_commit_patch_failed'`.
     * `verification_failed` — the RED-oracle mode (orchestrator.py:3067 already writes a row
       `{event:'verification_failed', exit, stdout_tail, stderr_tail, ...}` at
       orchestrator.py:3061-3070). Return `'verification_failed'`.
     * `verification_missing` — the no-vcmd sibling of the verification mode (orchestrator.py:2949
       writes `{event:'verification_missing', ...}` at orchestrator.py:2944-2952). Return
       `'verification_missing'`.
   If NONE of those rows exists for this `task_id` (the staging-worktree lifecycle mode writes NO
   ledger row — `create_staging_worktree` re-raises `CalledProcessError` at git_integration.py:1459-
   1461, caught by `except Exception` at orchestrator.py:2845-2848 which only `logger.error`s), return
   the fallback `'staging_worktree_failed'`. The helper must NEVER raise: a missing ledger file, an
   unreadable line, or a malformed JSON row is swallowed and the function returns
   `'staging_worktree_failed'` (the conservative default that names the otherwise-unlabelled mode).
   Read the ledger by iterating its lines and `json.loads`-ing each inside a per-line try/except
   (mirror the inline ledger-read idiom already used elsewhere in the worker); scan in reverse so the
   newest matching row wins. Do NOT import any new third-party module.

2. ADD a second new top-level helper
   `_record_auto_commit_blocked_reason(state_dir, task_id, outcome, reason) -> None` that, fail-safe:
   - Appends ONE dedicated telemetry row to `state_dir/'impl_progress.jsonl'` via the
     ALREADY-IMPORTED `from harness._journal import write_jsonl_row` (the worker imports it at
     orchestrator_worker.py:39 and orchestrator_worker.py:821 — import it lazily in-body the same
     way), with fields at minimum
     `{'ts': <iso or epoch>, 'phase': 'autowork', 'task_id': task_id, 'event': 'auto_commit_blocked_reason', 'outcome': outcome, 'reason': reason}`.
   - READ-MODIFY-WRITES the blocked retry sidecar `state_dir/'tasks'/'blocked'/f'{task_id}.retry.json'`
     to ADD a single new key `blocked_reason = reason` WITHOUT touching `last_outcome`, `attempts`,
     or `ts`. CRITICAL: load the existing sidecar JSON (it was written by
     `orchestrator._mark_blocked` -> `_write_retry_sidecar` immediately before this helper runs),
     set ONLY `obj['blocked_reason'] = reason`, and write it back; if the sidecar is missing or
     unreadable, best-effort write a minimal `{'blocked_reason': reason}` object so the precise mode
     is still observable. Preserve the existing `sort_keys=True` write style so the sidecar stays
     stable/diff-friendly.
   - The WHOLE body is wrapped in try/except so it can NEVER raise back into the worker terminal
     path; on any error it silently returns (the existing `_mark_blocked` terminal already ran, so
     the umbrella `last_outcome` is intact regardless).

3. EDIT the FOUR existing auto-commit-failure terminal call sites so that, IMMEDIATELY AFTER the
   existing `orch._mark_blocked(state_dir, task_id, <outcome>)` call (the `<outcome>` argument stays
   BYTE-IDENTICAL), they call
   `_record_auto_commit_blocked_reason(state_dir, task_id, <outcome>, _classify_auto_commit_failure(state_dir, task_id))`.
   The four sites (VERIFY exact lines by reading the file — they may drift):
     * orchestrator_worker.py:618  stateful_fuzz path     — outcome `'auto_commit_failed'`
     * orchestrator_worker.py:695  bypass_fuzzer path      — outcome `'auto_commit_failed'`
     * orchestrator_worker.py:733  round1 path             — outcome `'auto_commit_failed_r1'`
     * orchestrator_worker.py:792  cross-exam round-N path — outcome `f'auto_commit_failed_r{r + 1}'`
   Do NOT add the call to any OTHER `_mark_blocked` site (e.g. `synthesis_or_ast_failed`,
   `smoke_failed`, `embedded_tests_failed`, `narrow_fuzz_failed`, `stateful_fuzz_divergence`,
   `fuzz_error_r{n}`, `worker_crash_orphan`) — only the four auto-commit terminals.

# Inputs
READ `harness/orchestrator_worker.py`. VERIFIED current facts (source of truth — do NOT change
beyond the three edits above):
- The four umbrella call sites are `orch._mark_blocked(state_dir, task_id, 'auto_commit_failed[...]')`
  guarded by `auto_commit_ok or no_diff` (the else branch) at orchestrator_worker.py:618 / :695 /
  :733 / :792. Each is reached when `orch._auto_commit_accepted(...)` returned `False` AND there is
  no `no_diff` marker.
- `orchestrator._mark_blocked(state_dir, task_id, outcome='rejected')` (orchestrator.py:1911) MOVES
  the task to `blocked/`, then calls `_write_retry_sidecar(blocked_dir, task_id, outcome)`
  (orchestrator.py:1888) which writes `{'attempts', 'last_outcome', 'ts'}` (sort_keys=True) to
  `blocked/<id>.retry.json`, and emits a `task_blocked` ledger row carrying `outcome=<outcome>`. Do
  NOT edit either — they are in `harness/orchestrator.py` (`_NEVER_AUTO_APPROVE`). The new
  `blocked_reason` key is ADDED by the worker helper AFTER `_mark_blocked` returns.
- The three distinct underlying modes (do NOT modify these source files; only READ to confirm the
  ledger events): patch-apply -> `event='auto_commit_patch_failed'` (git_integration.py:1319-1334);
  verification_failed -> `event='verification_failed'` (orchestrator.py:3061-3070) and its sibling
  `event='verification_missing'` (orchestrator.py:2944-2952); staging-worktree lifecycle ->
  re-raised `CalledProcessError` from `create_staging_worktree` (git_integration.py:1459-1461),
  caught at orchestrator.py:2845-2848, emitting NO ledger row (hence the `'staging_worktree_failed'`
  fallback).
- Retry-budget semantics (README.md:370-374 and autowork_daemon.py:954-955): the daemon's
  `_retry_blocked_tasks` computes
  `_DETERMINISTIC_OUTCOMES = ('synthesis_or_ast_failed','embedded_tests_failed','narrow_fuzz_failed')`
  and `effective_max = 1 if last_outcome in _DETERMINISTIC_OUTCOMES else max_attempts` (==3). Because
  this fix leaves `last_outcome` EXACTLY `'auto_commit_failed[_r{n}]'` (NOT a member of that tuple),
  the budget bucket is byte-identical (3). The new `blocked_reason` key is NEVER read by the budget
  logic — it is observability only.
- The canonical ledger is `state_dir/'impl_progress.jsonl'`; rows are one JSON object per line with
  at least `ts`, `task_id`, `event`. `harness/_journal.write_jsonl_row(path, row)` is the only
  journal helper (no reader helper exists), so the classifier reads the file directly line-by-line.
- The RED oracle (pre-committed sibling) is the source of truth for required behavior.

# Non-Goals
Integration test coverage is out of scope for the implementation task (the impl extends an
already-live worker terminal path rather than creating a new module — the literal word `integration`
appears here to excuse the integration-test requirement). Do NOT edit any `_NEVER_AUTO_APPROVE` file
(notably `harness/orchestrator.py`, `harness/git_integration.py`, `harness/autowork_daemon.py`,
`harness/agent_jail.py`). Do NOT change `last_outcome`, `attempts`, or `ts` on the retry sidecar, and
do NOT change the `outcome` argument passed to `orch._mark_blocked` at ANY site — the retry budget
MUST stay byte-identical. Do NOT add the de-conflation call to any non-auto-commit `_mark_blocked`
site. Do NOT add a new member to `_DETERMINISTIC_OUTCOMES` (it lives in the daemon and is off-limits).
Do NOT introduce a new top-level module-level import; the two `harness._journal` and `json` reads
must be lazy/in-body where they are not already imported at module top. Do NOT author tests beyond
the one oracle. Do NOT restart or reconfigure the daemon, and do NOT touch the allowlist, decision
files, `state/`, or `config/`.

# Deliverables
`harness/orchestrator_worker.py` with:
- a new fail-safe top-level `_classify_auto_commit_failure(state_dir, task_id) -> str` returning one of
  `auto_commit_patch_failed` | `verification_failed` | `verification_missing` | `staging_worktree_failed`
  by scanning the ledger newest-first, defaulting to `staging_worktree_failed`;
- a new fail-safe top-level `_record_auto_commit_blocked_reason(state_dir, task_id, outcome, reason)`
  that appends an `auto_commit_blocked_reason` ledger row AND adds a `blocked_reason` key to
  `blocked/<id>.retry.json` without disturbing `last_outcome`/`attempts`/`ts`;
- the four auto-commit terminal sites each invoking the recorder with the classified reason
  immediately after the unchanged `orch._mark_blocked(..., <outcome>)`;
GREEN under the scoped verification_command, with the retry-budget bucket for
`auto_commit_failed[_r{n}]` provably unchanged (still 3) and no regression to the other terminals.

# Required plan shape
Emit EXACTLY TWO tasks, a RED-pair.

Task 1 — the oracle (authored RED first):
- task_id MUST be exactly `auto-commit-deconflate-oracle`.
- meta_task_type: test_authoring
- mutation_target: harness.orchestrator_worker   (dotted MODULE only)
- files_touched: ["tests/harness/test_auto_commit_outcome_deconflate.py"]
- Submit the test file source directly (ordinary Python; emit NEITHER patch nor manifest marker).
- verification_command: `python -m pytest tests/harness/test_auto_commit_outcome_deconflate.py -q`
- The oracle MUST, using a tmp-dir fixture `state_dir` (NO reliance on the live repo; construct the
  `state_dir/impl_progress.jsonl`, `state_dir/tasks/blocked/<id>.retry.json` tree synthetically),
  assert AT MINIMUM these readily-testable modes via runtime checks on module behavior + on-disk
  artifacts (NEVER a scan of the test file's own source text):
  (a) PATCH-APPLY MODE: write a ledger with a row
      `{"task_id": "t_patch", "event": "auto_commit_patch_failed", "file": "harness/x.py", "reason": "..."}`;
      assert `worker._classify_auto_commit_failure(state_dir, "t_patch") == "auto_commit_patch_failed"`.
  (b) VERIFICATION MODE: write a ledger with a row
      `{"task_id": "t_verify", "event": "verification_failed", "exit": 1}`;
      assert `worker._classify_auto_commit_failure(state_dir, "t_verify") == "verification_failed"`.
  (c) STAGING-WORKTREE FALLBACK: for a task `t_stage` that has NO per-mode row in the ledger (the
      staging-worktree mode writes none), assert
      `worker._classify_auto_commit_failure(state_dir, "t_stage") == "staging_worktree_failed"`.
  (d) RECORDER ADDS blocked_reason WITHOUT touching last_outcome (BUDGET PRESERVED): pre-seed
      `state_dir/tasks/blocked/t1.retry.json` with `{"attempts": 1, "last_outcome": "auto_commit_failed", "ts": 123}`
      (mirroring what `_write_retry_sidecar` writes); call
      `worker._record_auto_commit_blocked_reason(state_dir, "t1", "auto_commit_failed", "verification_failed")`;
      then re-read the sidecar and assert `blocked_reason == "verification_failed"` AND
      `last_outcome == "auto_commit_failed"` AND `attempts == 1` AND `ts == 123` are ALL unchanged
      (proving the budget-affecting field is byte-stable), AND assert a row with
      `event == "auto_commit_blocked_reason"` and `reason == "verification_failed"` is present in the
      ledger.
  (e) FAIL-SAFE: `worker._classify_auto_commit_failure(state_dir, "absent")` on a `state_dir` with no
      ledger file returns `"staging_worktree_failed"` without raising; and
      `worker._record_auto_commit_blocked_reason(state_dir, "no_sidecar", "auto_commit_failed", "verification_failed")`
      with no pre-existing `.retry.json` does NOT raise (best-effort writes a minimal
      `{"blocked_reason": ...}` sidecar).
  Import the module under test as `from harness import orchestrator_worker as worker` (mutation_target
  is the dotted module). Keep every assertion on observable module return values / files.

Task 2 — the implementation:
- task_id MUST be exactly `auto-commit-deconflate-impl`.
- meta_task_type: harness_self_fix
- files_touched: ["harness/orchestrator_worker.py"]
- depends on `auto-commit-deconflate-oracle`.
- Emit a `__JANUSMASK_PATCHES__` (do NOT emit a manifest block).
- OMIT mutation_target. spec_author: null (the oracle is the pre-committed RED sibling).
- verification_command: `python -m pytest tests/harness/test_auto_commit_outcome_deconflate.py -q`
- non_goals MUST contain the literal word `integration`. regression_tests >= 2 (propose
  `tests/harness/test_auto_commit_outcome_deconflate.py` plus an existing worker regression such as
  `tests/adversarial/test_orchestrator_worker_terminal.py` or the worker's own existing suite under
  `tests/harness/`/`tests/adversarial/` — the impl author selects a real, scoped, non-flaky test that
  exercises the changed worker terminal symbols; NEVER the full adversarial suite).

# Required plan shape — wiring (acceptance)
At acceptance the new behavior MUST be WIRED into the live worker path, not an orphan.
`harness/orchestrator_worker.py` is the daemon's per-task worker entrypoint (already live-reachable —
the autowork daemon spawns it per task), and the edit threads the two new helpers DIRECTLY INTO the
four already-live auto-commit terminal call sites in `main()`. The oracle's behavioral assertions
(a)-(e) prove the helpers' contract; the four call-site edits are the live wiring (each fires on the
real `auto_commit_ok == False` terminal). No `_NEVER_AUTO_APPROVE` file is edited.

# Implementation notes / hazards
- R-ANCHOR additive: BOTH `_classify_auto_commit_failure` and `_record_auto_commit_blocked_reason` are
  brand-new top-level symbols. A standalone `kind:symbol` patch for a not-yet-existing name fails
  patch-apply (KeyError, surfacing only as an opaque `auto_commit_failed`). Add them via the R-ANCHOR
  additive pattern — emit ONE `symbol` patch whose `name` is an EXISTING 1-part top-level worker
  anchor (e.g. `_emit_gate_failure` at orchestrator_worker.py:216, or `_purge_stale_sidecars_safe`,
  or `_reap_spent_briefs_safe`) and whose `code` reproduces that anchor VERBATIM PLUS the new
  function(s) appended. Per README §"R-ANCHOR additive constraints": extras are allowed ONLY for a
  1-part top-level anchor, the `code` must contain exactly one node named the anchor, every EXTRA
  node must be in the `allowed_extra` whitelist (an additional `def` qualifies), and the new names
  must NOT collide with existing ones. You MAY put both new helpers in a single R-anchored patch
  entry (two extra `def`s), or split them across two anchors — either is valid.
- The FOUR call-site edits, by contrast, modify EXISTING code inside `main()`. Since `main()` is one
  large top-level function, emit a `symbol` patch with `name: main` whose `code` reproduces `main`
  with the four `_record_auto_commit_blocked_reason(...)` lines inserted after the matching
  `orch._mark_blocked(...)` calls. (Reproducing a ~640-line function verbatim is acceptable per prior
  precedent: opus does not truncate large functions. If the synthesizer balks at the size, the
  classifier/recorder helpers still de-conflate via the ledger event the lower layers already wrote
  — but the SIDECAR `blocked_reason` requires the call-site edit, so the `main` edit is REQUIRED for
  full credit and the oracle's (d) effect.) Keep the four inserted lines byte-minimal and IDENTICAL
  in shape so the diff is reviewable.
- BUDGET INVARIANCE IS THE LOAD-BEARING CONSTRAINT: never change the `outcome` argument to
  `orch._mark_blocked`, never add a member to the daemon's `_DETERMINISTIC_OUTCOMES`, and never
  rename `last_outcome`. The de-conflation is a SEPARATE additive `blocked_reason` field + a separate
  ledger event. Oracle assertion (d) locks this.
- FAIL-SAFE EVERYWHERE: both helpers must be wrapped so they can NEVER raise back into the worker
  terminal — a malformed ledger line, a missing ledger file, an unreadable/locked sidecar, or a
  non-dict sidecar must each degrade gracefully (classifier -> `staging_worktree_failed`; recorder ->
  best-effort minimal write or silent return). The umbrella `_mark_blocked` terminal has ALREADY run
  before these helpers fire, so any helper failure leaves the existing (correct) blocked routing and
  budget intact.
- NESTED-QUOTE HAZARD: if any docstring is emitted in the patch, emit `"""` (triple double-quote),
  never `'''`, and never backslash-escape quotes inside the patch payload.
- LAZY IMPORTS: reuse the worker's existing idiom — `from harness._journal import write_jsonl_row`
  in-body (already used at orchestrator_worker.py:39 and :821) and the module-level `json` import
  (already at the top of the file). Do NOT add a new module-level import.

# Sequencing note (do NOT act on this)
This brief is an observability fix on the worker terminal path; it does not collide with daemon
dispatch. Leave this file at the repo root alongside the other `brief_hooks_*.md` files. Do NOT add
this brief's slug to `state/control/autowork/auto_promote.allowlist` — promotion is the operator's
decision.
