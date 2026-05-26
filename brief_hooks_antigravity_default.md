# Title

Antigravity Default Configuration & Claude Code Fallback Integration

# Scope

This brief specifies reconfiguring `JanusMaskJR` to default to Antigravity for Gemini models (utilizing Gemini 3.5 Flash) and Claude Code for Claude models (utilizing Opus 4.7), with an automatic fallback to Claude Opus 4.6 running on the Antigravity CLI if Claude Code hits its rate or token limits:

1. **Gemini Agent Rewire**:
   - Reconfigure the `gemini` agent inside [harness/config.yaml](file:///home/xnihil0zer0/JanusMaskJR/harness/config.yaml) to execute `agy` (Antigravity CLI) rather than the standard `gemini` CLI.
   - Set the default arguments for this rewired agent to `["-p", "--sandbox"]`.

2. **Claude Code Default**:
   - Ensure the default `claude` agent executes Claude Code (using the `--model opus` or `--model opus-4.7` parameter) drawing from the user's direct Anthropic subscription limits.

3. **Fallback Agent Definition**:
   - Define a new `claude_fallback` agent in the default configuration structure that executes the Antigravity CLI with Claude Opus 4.6.
   - Configuration arguments for `claude_fallback`: `["-m", "claude-opus-4.6", "-p", "--dangerously-skip-permissions", "--sandbox"]`.

4. **Fallback Orchestration Logic**:
   - Modify the execution routing in [harness/orchestrator.py](file:///home/xnihil0zer0/JanusMaskJR/harness/orchestrator.py) (specifically within `run_both_agents` and `run_agent_phase`):
     - If a call to spawn/poll the `claude` agent fails (returns `None`), the orchestrator must automatically log a warning and fallback to running the `claude_fallback` agent.
     - Ensure this fallback logic operates correctly under both sequential (Antigravity Mode) and parallel thread-pool execution paths.

5. **Fallback Unit Testing**:
   - Add a new unit test suite [test_claude_fallback.py](file:///home/xnihil0zer0/JanusMaskJR/tests/unit/test_claude_fallback.py) to assert that:
     - A failed attempt to spawn/run the `claude` agent successfully triggers a fallback invocation to `claude_fallback`.
     - Standard agent runs do not trigger the fallback when they succeed.

# Non-Goals

- Do not alter standard fuzzing, AST, or bash validator registries.
- Do not affect standard Gemini execution flows if they are configured to bypass Antigravity.

# Deliverables

- Updated agent definitions in [harness/config.yaml](file:///home/xnihil0zer0/JanusMaskJR/harness/config.yaml).
- Fallback logic integrated into `run_both_agents` within [harness/orchestrator.py](file:///home/xnihil0zer0/JanusMaskJR/harness/orchestrator.py).
- New unit tests under [test_claude_fallback.py](file:///home/xnihil0zer0/JanusMaskJR/tests/unit/test_claude_fallback.py) passing successfully.
