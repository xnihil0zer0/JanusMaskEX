---
interfaces: "harness/orchestrator_worker.py: _reap_spent_briefs_safe(payload) -> None. Complete the archive-on-integrate wiring so the (already-correct v2) reaper also fires for the no_diff DONE class, and add an end-to-end oracle that proves it fires through a REAL worker accept emission (not a hand call). Flag stays default-OFF."
meta_task_type: harness_self_fix
---

# Title

harness/orchestrator_worker.py

# ⛔ GATED HARNESS PATH — OWNER PRECONDITIONS BEFORE DISPATCH

`harness/orchestrator_worker.py` is a `harness/**` path. It is NOT in
`_NEVER_AUTO_APPROVE` (`orchestrator.py:2193`) but it IS deny-list-adjacent:
auto-commit fails closed until an **operator decision file** approves it
(`state/control/decisions/<task_id>.json`, `decision:"approve"`). PER THE
2026-06-08 GOVERNANCE AUDIT, the agent must **NEVER author that decision file
itself** — the owner authors it. So this leaf may be staged and built, but it
will not auto-commit until the OWNER drops the decision file. Do not self-approve.

Also a hard precondition: the RED oracle below is hand-authored by the owner/
operator and committed BEFORE dispatch (impl-only build). Keep
`autowork.archive_spent_briefs` **false** (default-OFF) throughout; this brief
completes correctness, it does NOT arm the feature.

# Why — the feature is partially implemented

The v2 reaper (`tools/brief_reaper.py`, `a5a7905`) is complete and correct:
ground-truth integration evidence, no `shell=True`, no premature archive, safe
moves. But the WIRING that invokes it is incomplete (2026-06-08 adversarial
review, agent 1):

1. **The `no_diff` DONE class is missed.** `_reap_spent_briefs_safe`
   (`orchestrator_worker.py:45`) early-returns unless `payload['outcome'] ==
   'accepted'`. The worker emits `outcome:'no_diff'` at THREE accept sites
   (lines 499 `stateful_fuzz`, 576 `bypass_fuzzer`, 673 `round1/roundN`). A
   `no_diff` outcome means the agents produced no change because the brief was
   ALREADY satisfied — it is genuinely DONE (see the worker's own comment at
   `_consume_no_diff_marker`, line ~84). Those briefs are never reaped, so they
   linger at root as false "pending" paperwork — exactly the staleness the
   feature exists to prevent.

2. **It was never proven end-to-end.** The "proven e2e" claim was a hand call of
   `_reap_spent_briefs_safe({'outcome':'accepted',...})`, not a real dispatch.
   No test exercises the reaper firing through an actual `_print_json_line`
   accept emission with the flag on.

# Scope — complete `_reap_spent_briefs_safe`

Edit ONLY the existing function `_reap_spent_briefs_safe` in
`harness/orchestrator_worker.py` (a single-symbol partial edit). Do NOT change
`_print_json_line`, the reaper module, or any emit site.

- Change the outcome guard so the bridge fires for BOTH `accepted` AND
  `no_diff`:
  replace `if payload.get('outcome') != 'accepted': return`
  with `if payload.get('outcome') not in ('accepted', 'no_diff'): return`.
- Everything else stays: still behind the default-off
  `autowork.archive_spent_briefs` flag; still wrapped so it can never raise back
  into `_print_json_line`; still resolves `task_id`, `repo_root`
  (`pathlib.Path(__file__).resolve().parents[1]`), and today's `stamp`; still
  calls `reap_for_task(repo_root, task_id, stamp=stamp)`.
- The v2 reaper already counts a `no_diff` task as integrated (its
  `_integrated_task_ids` reads `state/impl_progress.jsonl` rows with
  `event == 'no_diff'`, and the reaped `task_id` counts implicitly), so NO
  reaper change is needed — only the bridge guard.

# Required plan shape

Emit EXACTLY ONE task (do NOT decompose):
- meta_task_type: harness_self_fix
- files_touched: ["harness/orchestrator_worker.py"]  (this file ONLY)
- verification_command: "python -m pytest tests/harness/test_worker_reap_wiring.py -q"
- spec_author: null
- IMPL-only: the oracle is a PRE-COMMITTED precondition; author/edit NO test.
- Partial-edit of the EXISTING `_reap_spent_briefs_safe` only (single top-level
  symbol). Do NOT submit a whole-file rewrite.
- The task spec.non_goals MUST contain the literal word "integration".
- test_spec MUST carry >=2 regression_tests reflecting the edge cases below.

# Oracle (hand-author + commit BEFORE dispatch) — tests/harness/test_worker_reap_wiring.py

Extend the existing wiring oracle. Add at least:
1. `test_no_diff_outcome_fires_reaper`: monkeypatch
   `tools.brief_reaper.reap_for_task` (or the imported symbol) to record its
   calls; invoke the bridge with `{'outcome':'no_diff','task_id':'X'}` and the
   flag ON; assert the reaper was called once with `task_id='X'`.
2. `test_accepted_outcome_still_fires_reaper`: same with `outcome:'accepted'`
   (regression — do not break the existing path).
3. `test_non_terminal_outcome_does_not_fire`: `{'outcome':'rejected'}` and
   `{'outcome':'timeout'}` must NOT call the reaper.
4. `test_flag_off_never_fires`: with `archive_spent_briefs` false, neither
   `accepted` nor `no_diff` calls the reaper.
5. END-TO-END (the agent-1 gap): drive a REAL `_print_json_line(
   {'outcome':'no_diff','task_id':...})` (NOT a hand call of the bridge) with
   the flag ON and a seeded tmp repo (a brief+plan pair + a
   `state/impl_progress.jsonl` no_diff row), and assert the brief+plan were
   moved into `_autowork_archive/<stamp>/reconciled/`. This proves the wiring
   end-to-end through the actual emission chokepoint.

# Non-Goals

INTEGRATION is out of scope: do NOT touch `_print_json_line`, the emit sites,
the reaper module, or the config flag default. Do NOT arm the feature (the flag
stays false). Do NOT broaden `repo_root` resolution for external
(`JANUSMASK_WORKING_DIR`) builds in this leaf — v2's unique-brief-paired-plan
ambiguity guard already prevents wrong-brief archival, and external-root
handling is a separate follow-up. Touch no file other than
`harness/orchestrator_worker.py`.

# Edge Cases

- `outcome:'no_diff'` with flag ON -> reaper fires (regression test).
- `outcome:'accepted'` with flag ON -> reaper still fires (regression test).
- `outcome:'rejected'` / `'timeout'` / missing outcome -> reaper never fires.
- Flag OFF -> reaper never fires for any outcome.
- Reaper raising internally must never propagate into `_print_json_line` (the
  bridge stays fully wrapped).
- Missing/empty `task_id` -> no-op.

# Deliverables

`harness/orchestrator_worker.py` with `_reap_spent_briefs_safe` firing on
`accepted` and `no_diff`, GREEN under
`python -m pytest tests/harness/test_worker_reap_wiring.py -q`, the feature
still default-OFF, and an end-to-end test proving the reaper fires through a real
`_print_json_line` emission. Lands only after the OWNER authors the
`state/control/decisions/<task_id>.json` approval.
