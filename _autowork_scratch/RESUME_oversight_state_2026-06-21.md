# Oversight resume state — gracefully shut down 2026-06-21 ~17:18

## Shutdown state (how to resume)
- HALTED via `state/control/autowork/full_stop` + `state/control/autowork/supervisor.stop` (both set 17:18).
- Daemon child (was pid 149125) TERM'd + drained; supervisor (was pid 10476) stopped.
- TO RESUME: `rm -f state/control/autowork/full_stop state/control/autowork/supervisor.stop`
  then `scripts/run-autowork.sh --state-dir state --logs-dir logs --config harness/config.yaml`.
- Protected processes left ALIVE intentionally: agy pid 6200 (interactive), claude pid 7101. Do NOT kill.

## ★ KEY DISCOVERY this session — planner blind-draft constant-outbox defect (the REAL root of recurring deterministic-park)
Proven by live reproduction (agents ae071624 + a3ed4001). The planner spawns blind-draft agents into a
CONSTANT-named outbox dir `<agent>-r1-notask-da39a3ee` (`da39a3ee`=sha1("") because planner has no task_id),
under `agent_workroot()` = `/home/xnihil0zer0/JanusMaskJR_agentwork`. STALE `plan_draft.json` accumulate there;
`orchestrator._poll_mode_artifact` (no mtime guard) returns the stale file as "artifact received" (MASKS the
no-write), while `blind_draft._resolve_outbox_artifact` applies a `spawn_start_epoch` mtime filter that REJECTS
it → both agents "crashed" → "Both agents failed to produce a valid draft" rc=2 → deterministic 24h park.
PRE-EXISTING latent infra bug (d1fcce0 2026-05-25 + 652fb3a 2026-06-05), NOT the redpair smoke-gate collapse
(that guard works fine). This is the true cause of the intermittent rc=2/rc=1 planner flakes I'd been hand-clearing.
NOTE: there was NO stale pinned claude session (claude --continue is not implicated) — masking surface was
purely the 2 stale outbox plan_draft.json files (since removed by hygiene).

## PERMANENT FIX — authored + ready, NOT yet dispatched
- Brief: `brief_hooks_planner_blind_draft_outbox_per_spawn.md` (slug `planner_blind_draft_outbox_per_spawn`).
- Fix (3 symbol patches in harness/orchestrator.py): (1) `_build_agent_env` append uuid4().hex[:8] nonce ONLY
  when task_id empty (planner case) — scoped to avoid breaking `_pinned_session_slug` idempotence /
  resume_pinned_session (6 tests in test_int3_p2_cwd_pinning.py); (2) `_poll_mode_artifact` add
  `spawn_start_epoch` param + reject st_mtime<spawn_start_epoch; (3) `poll_for_submission` thread
  spawn_start_epoch=poll_start_wall into both call sites (:994,:1032).
- Tasks: impl `planner-blind-draft-outbox-per-spawn-impl` (orchestrator.py, _NEVER_AUTO_APPROVE) +
  oracle `planner-blind-draft-outbox-per-spawn-oracle` (tests/harness/...).
- DECISION FILE ALREADY STAGED: `state/control/decisions/planner-blind-draft-outbox-per-spawn-impl.json` {"approve"}.
- load_brief validated. Dispatch as a BARRIER (verifier-path edit): quiesce, land, restart daemon.

## P1.1 build_evidence (the live task) — state at shutdown
- UN-PARKED (deterministic park marker removed by hygiene). Was mid-plan (dual-agent, drafting on the correct
  brief `brief_hooks_p11_build_evidence_perphase.md`) when shut down — plan NOT yet written; in-flight planner killed by drain.
- Committed oracle `tests/ngv2/test_p11_build_evidence_perphase.py` (fa6a069, artifacts-shape) is correct + MUST NOT change.
- Brief is internally consistent (contradiction reconciled earlier). The ONLY thing that blocked it was the planner-outbox defect above.
- ON RESTART build_evidence may RE-PARK via the same defect until the fix lands. Options: (a) land the planner-outbox
  fix FIRST (recommended — makes everything robust), or (b) before restart clear stale outbox:
  `rm -f /home/xnihil0zer0/JanusMaskJR_agentwork/{claude,gemini}/*-r1-notask-da39a3ee/outbox/plan_draft.json`
  then let build_evidence plan, then land the fix as a barrier.

## Recommended resume sequence
1. rm sentinels; clear stale planner outbox (one-liner above); restart supervisor.
2. FIRST allowlist `planner_blind_draft_outbox_per_spawn` (decision staged) → land it as a barrier → restart daemon child.
   (This permanently kills the deterministic-park root cause for ALL briefs incl. build_evidence re-plans.)
3. Then build_evidence (P1.1) plans + builds robustly: oracle+impl red-pair → anti-false-green verify
   (oracle artifacts-shape, impl translates-not-copies, no 16-key leak) → live run_hunt WORKS proof
   (traversal reaching triage/verify/novelty/report on production state['artifacts']) → close P1.1 (append §8
   deviation log at AI-Data/Research-JanusMask/NGv2-closure-deliverables-and-acceptance-contract.md).
4. Also `p11-gate-table-typed-terminals` (other blocked P1.1 task) re-dispatch file-disjoint.
5. Then open the spine: P1.2 detonation_authenticity_provenance → P1.3 wire_loopback_per_cwe_channels → P2.1 env_readiness_fsm (EPIC).

## Other staged work (lower priority, dispatch later)
- 3 cleanup-system briefs at repo root (purge_task_state_primitive → purge_on_reopen_autofire → reset_external_engine);
  plan in `_autowork_scratch/cleanup_brief_family_dispatch_plan.md`. Dispatch AFTER P1.1.
- Latent SLOT-LEAK bug (cosmetic, pre-existing since 7079ba8): ~34 `.slot` files in state/control/autowork/running/
  never cleaned (no teardown site; reaper ignores *.slot). NOT a blocker (slots hold agy-pool index, not pids;
  _reap_running globs *.pid only). Worth a systemic fix: unlink matching .slot wherever .pid is unlinked
  (autowork_daemon.py ~332/348/359/368/376/382) + sweep orphans at startup.
- Other 4 parked briefs (claudecap_parallel_isolation, reap_spent_briefs_integration_parity,
  reconciler_reaps_spent_briefs, whole_file_drift_test_authoring) are deterministic:false (auto-retry) — they
  re-hit the planner-outbox defect until the fix lands; the fix resolves them.
