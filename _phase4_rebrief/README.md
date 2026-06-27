Phase-4 rework holding (2026-06-13). Briefs moved here build modules ALREADY
committed in NobleGreedv2 (would only churn the planner -> empty plan via the
live committed-module dedup guard). They are NOT deleted: Phase 4 of
HANDOFF_factory_clobber_fix_and_ngv2_worker_rework.md re-briefs these workers
ADDITIVELY (real behavioral oracle + __main__/argparse entrypoint, NO clobber of
the committed module). triage-worker moved because its plan_hooks file was
removed during clobber-cleanup, causing the daemon to re-plan it every cycle.
