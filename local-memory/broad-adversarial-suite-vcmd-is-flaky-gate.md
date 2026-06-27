---
name: broad-adversarial-suite-vcmd-is-flaky-gate
description: "Never use `pytest tests/adversarial/ -q` as a brief verification_command — non-hermetic tests fail non-deterministically in the staging worktree and wrongly block the edit"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: ae16acba-9ad9-45c6-989f-a8c880d79cef
---

A brief's `verification_command` must be a SCOPED, HERMETIC, deterministic gate
over exactly the code paths the edit touches — NEVER the whole `tests/adversarial/`
suite.

**Why:** 2026-06-15 the factory-repair-feedback edit (orchestrator.py:
`_mark_blocked`/`prepare_task_prompt`/`_last_failure_tail`) was rejected
`verification_failed` with the broad vcmd `python -m pytest tests/adversarial/ -q`.
Two runs failed on DISJOINT test sets — staging worktree failed
{test_P1_track_record ×2, test_rebuild_envfaithful, test_rebuild_webui}; clean HEAD
failed {test_replication_clean_room_static ×4 (smoke-artifact-tracked,
harness-home-free)}. Disjoint-across-runs ⇒ the suite is non-hermetic/flaky inside
a git staging worktree (these tests assert git tracking-state / home-free-ness /
rebuild env that differ in a worktree). A differential "new-failures-only" gate
would ALSO misfire because the failing sets are non-deterministic. The edit itself
was innocent.

**How to apply:** scope the vcmd to the deterministic tests that exercise the
changed symbols. For orchestrator `prepare_task_prompt` + blocked-route edits the
hermetic pair is `python -m pytest
tests/adversarial/test_prepare_task_prompt_test_authoring.py
tests/adversarial/test_daemon_hands_off_blocked_route.py -q` (14 passed, 0.31s).
Re-dispatch after fixing the vcmd: evict ALL stale task artifacts for the tid
(state/tasks/<tid>.json, blocked/<tid>.json + .retry.json,
test_results/<tid>_baseline.json, output/<tid>.py, sessions/*<tid>*) but KEEP
state/control/decisions/<tid>.json, then `touch` the brief to fire idle_wake — the
stale staged spec carries the OLD vcmd and the daemon would otherwise re-dispatch
it verbatim. See [[fixes-are-permanent-and-reusable]],
[[spec-only-pipeline-augment-agents]].
