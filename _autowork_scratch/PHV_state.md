# PHV State Verification (2026-06-13)

1. Worktrees: ONLY main /home/xnihil0zer0/JanusMaskJR dcf697a [master]. No orphan/stale worktrees.
2. Locks: only state/state.lock (0 bytes, Jun 3, NOT a git_commit.lock; this is the persistent state mutex, benign). No git_commit.lock anywhere. No stale .retry locks.
3. Committed contracts: ALL 5 TRACKED & CLEAN (no uncommitted diff):
   harness/webui_config_schema.py, tests/webui/test_config_schema.py,
   harness/model_backends.py, tests/webui/test_model_backends.py, harness/secrets_store.py.
4. config/drive_backup_modules.yaml: UNCOMMITTED (expected/new). 5 explicit .py paths.
   Regex first clause (?<![\w.])<stem>\.py\b — leading '/' is not [\w.], lookbehind passes.
   Empirically tested all 5 stems against the yaml text via the EXACT _grep_config pattern
   (wire_up.py:302): archiver=True ledger=True uploader=True hook_runner=True install_hooks=True.
   VERDICT: YES, all 5 satisfy the regex. Wire-up CONFIG_WIRED claim is valid.
5. Processes: 3 agy procs running:
   - 130392  cwd=JanusMaskJR   (Jun09, 427min) -- long-lived, in main repo
   - 2667946 cwd=NobleGreedv2  (Jun12)
   - 2686453 cwd=JanusMaskJR   (Jun12)
   No orchestrator_worker, no codex. The two JanusMaskJR-cwd agy procs are NOT jailed
   to a worktree (main tree) -> tree-tamper risk per [[agy-autonomous-single-agent-tamper]].
   This is a concern but not a state-corruption per se.
6. config-schema residue: NO .processing, NO .retry.json. Present artifacts are benign:
   session submissions, test_results baselines, plan_attempts/webui-config-schema.json,
   and selfheal_skip/config-schema-oracle (a skip marker, not a stale lock).

VERDICT: state CLEAN on disk artifacts. CAVEAT: 3 live agy procs (2 cwd=main JanusMaskJR
tree, uncontained) -- verify tree integrity before any pipeline dispatch.
