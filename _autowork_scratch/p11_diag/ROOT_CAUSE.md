# P1.1 (p11_gate_every_transition_typed_terminals) planner-failure root cause

Diagnosed 2026-06-19 ~23:25 by oversight agent (direct planner reproduction).

## Verdict
NOT a brief-shape bug, NOT stochastic-merge, NOT fixable by attempt-reset/retry.
ROOT CAUSE = a HARNESS/ENV AUTH failure: the **tmux-backed claude planning worker
hits `API Error: 401 Invalid authentication credentials` / "Please run /login"
INSIDE the bwrap synthesis jail**, so claude's planning half produces an EMPTY draft
every run. The planner then loud-fails (`PLANNER_LOUD_FAIL_EMPTY_DRAFT`, rc=2 at
harness/planner/cli.py:464) because the non-bootstrap path REQUIRES both halves
non-empty. Single-agent promotion (config synthesis.accept_single_agent_leaf_plans /
enable_single_agent_promotion) applies only on the `--bootstrap` path, not the daemon path.

## Evidence chain
1. Direct repro: `python -m harness.planner.cli <brief> --output-plan ...` → RC=2,
   stderr "Both agents failed to produce a valid draft." (cli.py:460-462).
   - claude per-half current_diff: 0 p11 mentions. gemini: 5 (all 4 task_ids present).
2. claude PTY snapshot (state/planning/sessions/claude/sessions/pty_claude_worker.snapshot.txt):
   `●Please run /login · API Error: 401 Invalid authentication credentials` — same 401
   the daemon hit at 22:15 (persistent, not transient).
3. `~/.claude/.credentials.json` is VALID (expiresAt 2026-06-20 01:28, not expired).
4. `claude -p "say OK"` OUTSIDE jail → RC=0 "OK".
5. `claude -p "say JAILOK"` INSIDE the synthesis jail (agent_jail.build_jail_argv,
   bind_credentials=True) → RC=0 "JAILOK". => jail cred binding is FINE for print mode.
6. Interactive claude TUI in a tmux pane OUTSIDE the jail → works ("TUIOK", 34736 tokens).
7. => The 401 is specific to the INTERSECTION: interactive tmux-PTY claude backend
   (workers.claude_backend=tmux) running INSIDE the bwrap jail. Print mode and
   out-of-jail TUI both authenticate; the jailed interactive TUI does not.
   Hypothesis: the long-lived interactive TUI triggers a proactive OAuth token
   REFRESH that fails in-jail (the throwaway `~/.claude.json.jail` rw copy +
   ro/rw cred surface differs from what the refresh path needs), whereas `-p`
   print mode never refreshes.

## Why the earlier daemon failures looked different
- 22:10 reconciliation run: all 4 p11 items were `gemini_only` (claude empty). The
  reconciliation sub-agents (also claude/gemini, same 401 on claude) sometimes
  resolved `silent_concede/claude_silent → auto` (kept) and sometimes
  `both_agents_silent → unresolved` (dropped ALL). That stochastic drop produced
  the `missing_required_task` (rc=1) when only some items survived a partial merge.
  But this is a DOWNSTREAM symptom; the upstream cause is the empty claude half.

## What does NOT fix it
- Brief edits / clearer `# Required plan shape`: irrelevant — claude never runs the brief.
- Attempt-reset + re-touch allowlist: would re-hit the same 401 deterministically.
- Reconciliation merge logic: only matters because claude's half is empty.

## Proposed fix (harness — needs owner/harness brief, NOT brief-editable)
Options for the owner to choose:
(a) Fix the in-jail tmux claude OAuth refresh (so the interactive backend authenticates
    like `claude -p` does in-jail).
(b) Switch `workers.claude_backend` to the print/`-p` backend for the PLANNING phase
    (print mode authenticates in-jail, proven above).
(c) Allow single-agent (gemini-only) promotion on the daemon/planning path, not just
    `--bootstrap` (gemini reliably emits all 4 tasks). Guarded by
    synthesis.single_agent_promotion_ceiling.
