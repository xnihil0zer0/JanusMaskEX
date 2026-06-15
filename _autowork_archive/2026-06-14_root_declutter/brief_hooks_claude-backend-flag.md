---
interfaces: "def _claude_backend(config: dict) -> str: ...\ndef _use_tmux_claude(agent: str, config: dict) -> bool: ..."
---

# Title

Add workers.claude_backend config flag and helper selectors

# Scope

Add workers: {claude_backend: headless} (default headless) to harness/config.yaml. Add small additive selector functions in harness/orchestrator.py: _claude_backend(config) -> str (returns the flag, default 'headless') and _use_tmux_claude(agent: str, config: dict) -> bool (True iff _claude_backend(config) == 'tmux' AND os.path.basename(config['agents'][agent]['command']) == 'claude'). These ride as NEW top-level functions (extra nodes), touching nothing existing. Implement test coverage for these selectors, verifying they handle missing workers section, claude_backend set to junk, agy agent under the tmux flag (must be False), and headless flag (must be False).

# Non-Goals

Do not modify how spawn_agent actually spawns the agent yet. Do not flip the default backend to tmux (must default to headless).

# Inputs

harness/config.yaml, harness/orchestrator.py

# Deliverables

Updated harness/config.yaml, selectors in harness/orchestrator.py (exposes `_use_tmux_claude(agent: str, config: dict) -> bool`), and new tests in tests/harness/test_orchestrator.py (or a new test file) verifying selector behavior.
