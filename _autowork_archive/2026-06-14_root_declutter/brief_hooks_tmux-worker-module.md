---
dependencies:
  - "tmux-claude-wire"
interfaces: "exposes `spawn_claude_tmux(agent, resolved_prompt, env, config, *, dbus_sock=None) -> _ExitedProc` where `_ExitedProc` has `poll() -> 0`, `returncode=0`, `wait(timeout=None) -> 0`, `kill()` no-op, and assignable `_work_dir`"
---

# Title

Implement tmux worker backend and execution wrapper

# Scope

CLASSIFICATION (MANDATORY): this leaf creates `harness/tmux_worker.py`, a SENSITIVE path under `_SENSITIVE_APPLY_GLOBS = harness/**`. The implementation task's `meta_task_type` MUST be `harness_self_fix` — any other classification is rejected at planning time with `sensitive_files_touched`. Emit the plan task with `"meta_task_type": "harness_self_fix"`.

Create new module `harness/tmux_worker.py` containing `TmuxWorkerResult`, `_ExitedProc`, `seed_from_prompt_file`, `run_tmux_worker`, and `spawn_claude_tmux` functions. Implement environment preparation, config seeding, command jailing, prompt writing, and tmux execution orchestration. Create test suite `tests/harness/test_tmux_worker.py` verifying all execution pathways, faked tmux interactions, error scenarios, and process shims without spawning real processes.

# Non-Goals

INTEGRATION-TEST EXCUSE (REQUIRED verbatim in every generated task's `spec.non_goals`): live end-to-end integration of this backend (spawning a real interactive claude in tmux for a real worker task) is an OPERATOR-VALIDATED step performed AFTER merge by flipping the flag; it is deliberately OUT OF SCOPE for automated leaf tests, which exercise pure seams over injected fakes only (no real tmux/claude spawn in any test). This excuses the `missing_integration_test` plan gate.
Do NOT change the headless path, the agy STDIN path, the synthesis `active_agents`, or any `agents.*` entry.
Do NOT remove or rewrite any existing `spawn_agent` branch; the new branch is purely additive and flag-gated.
Do NOT flip the default to `tmux` here (operator does it after live validation).
Do NOT touch NGv2 (the agy-default hunt is the separate epic `ngv2_agy_default_hunt`).
Do NOT scrape the TUI for the deliverable; the deliverable is the outbox files claude writes.

# Inputs

Helper modules: `overseer/tmux_session.py`, `overseer/tmux_seams.py`, `harness/agent_jail.py`. Consumes task and environment parameters (`JANUSMASK_TASK_ID`, `JANUSMASK_WORK_DIR`, `JANUSMASK_STATE_DIR`).

# Deliverables

New module `harness/tmux_worker.py`. New test suite `tests/harness/test_tmux_worker.py`. Produces the interface: exposes `spawn_claude_tmux(agent, resolved_prompt, env, config, *, dbus_sock=None) -> _ExitedProc` where `_ExitedProc` has `poll() -> 0`, `returncode=0`, `wait(timeout=None) -> 0`, `kill()` no-op, and assignable `_work_dir`
