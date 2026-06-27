# auto_commit_failed de-conflation — verified analytic notes (throwaway)

## The umbrella + the 4 worker call sites (VERIFIED)
`harness/orchestrator_worker.py` calls `orch._mark_blocked(state_dir, task_id, 'auto_commit_failed[...]')`
on `auto_commit_ok == False and not no_diff` at:
- :618  stateful_fuzz path        -> 'auto_commit_failed'
- :695  bypass_fuzzer path        -> 'auto_commit_failed'
- :733  round1 path               -> 'auto_commit_failed_r1'
- :792  cross-exam round N path   -> f'auto_commit_failed_r{r+1}'
All four come from a single boolean `auto_commit_ok = orch._auto_commit_accepted(...)` returning False.

## The 3 distinct modes that collapse to auto_commit_ok == False (VERIFIED)
1. patch-apply failure: git_integration.py:1319-1334 `except (KeyError, ValueError)` ->
   result['committed']=False AND emits ledger row event='auto_commit_patch_failed'
   {file, reason} for THIS task_id. `_auto_commit_accepted` then returns False (the
   `if result.get('committed'):` block at orchestrator.py:2942 is skipped).
2. verification_failed: orchestrator.py:3061-3070 -> emits ledger row event='verification_failed'
   {exit, stdout_tail, stderr_tail, ...} then `return False`.
   (Sibling: verification_missing at :2944-2952 emits event='verification_missing' then return False.)
3. staging-worktree lifecycle failure: create_staging_worktree (git_integration.py:1369; the
   `git worktree add` at :1435 with `check=True` re-raises CalledProcessError at :1459-1461).
   Caught at orchestrator.py:2845-2848 `except Exception as e:` -> logger.error (NO ledger row) ->
   `return False`. THIS mode currently leaves NO precise ledger event at all = worst-conflated.

## Budget semantics (VERIFIED — must be preserved)
Daemon `_retry_blocked_tasks` (autowork_daemon.py:911):
  :942  attempts, last_ts, last_outcome read from blocked/<tid>.retry.json
  :954  _DETERMINISTIC_OUTCOMES = ('synthesis_or_ast_failed','embedded_tests_failed','narrow_fuzz_failed')
  :955  effective_max = 1 if last_outcome in _DETERMINISTIC_OUTCOMES else max_attempts (==3)
So budget keys EXACTLY on `last_outcome` membership in that 3-tuple. `auto_commit_failed[_r{n}]` is
NOT a member -> budget 3. README.md:370-374 documents this. last_outcome is also only *formatted*
into the retry_exhausted telemetry (:963) and passed to _escalate_to_autobrief (:965) — neither
branches on its value beyond the membership test.

## Constraint: orchestrator.py is in _NEVER_AUTO_APPROVE (orchestrator.py:2358)
`_mark_blocked` (:1911) and `_write_retry_sidecar` (:1888) live in orchestrator.py, which the brief
forbids editing. So de-conflation must live ENTIRELY in orchestrator_worker.py.

## Chosen design (additive, zero budget change, single-file)
Add a worker-local helper `_classify_auto_commit_failure(state_dir, task_id) -> str` that reads the
TAIL of state/impl_progress.jsonl, finds the most-recent ledger event for THIS task_id among
{'auto_commit_patch_failed','verification_failed','verification_missing'} and returns the matching
specific reason; if none is found (the staging-worktree mode, which writes no row) it returns
'staging_worktree_failed'. Then a second worker-local helper
`_record_auto_commit_blocked_reason(state_dir, task_id, outcome, reason)` (a) appends a dedicated
event='auto_commit_blocked_reason' ledger row {task_id, outcome, reason} and (b) read-modify-writes
blocked/<task_id>.retry.json to ADD a `blocked_reason` key WITHOUT touching `last_outcome`/`attempts`/`ts`.
Both fail-safe (never raise). At each of the 4 call sites, AFTER `orch._mark_blocked(..., outcome)`
(outcome string UNCHANGED), call the recorder with reason=_classify_auto_commit_failure(...).
=> last_outcome stays 'auto_commit_failed[_r{n}]' -> budget bucket byte-identical; the precise mode is
now on both the sidecar (blocked_reason) and a dedicated ledger row, so triage needs no grep.

## R-anchor: both new top-level helpers anchor additively on an EXISTING worker symbol
(e.g. `_emit_gate_failure` at :216) so the not-yet-existing names don't KeyError on patch-apply.
