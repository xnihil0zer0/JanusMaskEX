---
interfaces: "exposes `spawn_claude_tmux(agent, resolved_prompt, env, config, *, dbus_sock=None) -> _ExitedProc` where `_ExitedProc` has `poll() -> 0`, `returncode=0`, `wait(timeout=None) -> 0`, `kill()` no-op, and assignable `_work_dir`"
---

# Title

Wire configuration and routing logic for tmux worker backend

# Scope

CLASSIFICATION (MANDATORY): this leaf edits the SENSITIVE paths `harness/orchestrator.py` and `harness/config.yaml` (both under `_SENSITIVE_APPLY_GLOBS = harness/**, config/**`). The implementation task's `meta_task_type` MUST be `harness_self_fix` — any other classification is rejected at planning time with `sensitive_files_touched`. Emit the plan task with `"meta_task_type": "harness_self_fix"`.

Add helper functions `_claude_backend(config: dict) -> str` and `_use_tmux_claude(agent: str, config: dict) -> bool` to `harness/orchestrator.py`. Integrate these into `spawn_agent` to conditionally delegate agent execution to `harness.tmux_worker.spawn_claude_tmux` via lazy import. Add `workers.claude_backend: headless` entry to `harness/config.yaml` with a comment containing the literal `tmux_worker`. Add test suite `tests/harness/test_tmux_claude_wire.py` covering all configurations and routing logic.

# Non-Goals

INTEGRATION-TEST EXCUSE (REQUIRED verbatim in every generated task's `spec.non_goals`): live end-to-end integration of this backend (spawning a real interactive claude in tmux for a real worker task) is an OPERATOR-VALIDATED step performed AFTER merge by flipping the flag; it is deliberately OUT OF SCOPE for automated leaf tests, which exercise pure seams over injected fakes only (no real tmux/claude spawn in any test). This excuses the `missing_integration_test` plan gate.
Do NOT change the headless path, the agy STDIN path, the synthesis `active_agents`, or any `agents.*` entry.
Do NOT remove or rewrite any existing `spawn_agent` branch; the new branch is purely additive and flag-gated.
Do NOT flip the default to `tmux` here (operator does it after live validation).
Do NOT touch NGv2 (the agy-default hunt is the separate epic `ngv2_agy_default_hunt`).
Do NOT scrape the TUI for the deliverable; the deliverable is the outbox files claude writes.

# Inputs

Existing files: `harness/orchestrator.py` and `harness/config.yaml`. Consumes the interface: exposes `spawn_claude_tmux(agent, resolved_prompt, env, config, *, dbus_sock=None) -> _ExitedProc` where `_ExitedProc` has `poll() -> 0`, `returncode=0`, `wait(timeout=None) -> 0`, `kill()` no-op, and assignable `_work_dir`

# Deliverables

Modified `harness/orchestrator.py` and `harness/config.yaml` enabling conditional tmux worker routing. New test file `tests/harness/test_tmux_claude_wire.py` asserting orchestrator routing truth table.
