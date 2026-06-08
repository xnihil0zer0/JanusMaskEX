---
interfaces: "overseer/driver.py: _build_argv(conversation, rewind_to_index) -> list[str]; run_turn(conversation, user_text, *, runner, env_builder, jail_builder, stream_parser, **kw) -> AssistantTurn. Imports overseer.mode_gate.resolve_tool_allowlist + overseer.mode_prompts.render_mode_context."
meta_task_type: data_model
---

# Title

overseer/driver.py

# Scope

EDIT the EXISTING module overseer/driver.py (single file, IMPL-only) so the
per-turn claude argv it builds is a WORKING HEADLESS invocation. The chat panel
currently returns an EMPTY assistant turn ("(no output)") for every prompt: the
argv omitted `-p` (so the vendored claude emitted only the init event — the
session id was captured — but never processed the stdin prompt) and `--verbose`
(required alongside `--output-format stream-json` in print mode), and it handed
the ABSTRACT mode-capability tokens ('read'/'search'/'write') straight to
`--tools` space-joined, none of which is a real claude tool name.

Fix ONLY `overseer.driver._build_argv` (and any helper you nest INSIDE it — do
NOT add new top-level module symbols). Mirror the harness's canonical claude
spawn (harness/config.yaml agents.claude.args + orchestrator's acceptEdits add).

# Required plan shape

Emit EXACTLY ONE task (do NOT decompose / split into subtasks):
- meta_task_type: data_model
- files_touched: ["overseer/driver.py"]  (this file ONLY)
- verification_command: "python -m pytest tests/overseer/test_driver_headless.py tests/overseer/test_driver.py -q"
- spec_author: null
- IMPL-only: BOTH oracles are pre-committed preconditions — author/edit NO test; touch no other file.

# Inputs

The current `overseer/driver.py` is staged into your inbox/targets — READ it on
your second turn and edit `_build_argv` in place, preserving everything else
(run_turn, AssistantTurn, the stream-folding loop, the agy branch, resume/fork).

The two committed oracles are the contract:
`tests/overseer/test_driver_headless.py` (the NEW fix contract) and
`tests/overseer/test_driver.py` (the existing surface). The required argv shape:

For the CLAUDE backend (conversation['agent_backend'] != 'agy'), the built argv MUST contain:
- `-p`  (print/headless mode — THE load-bearing fix; without it claude never reads stdin).
- `--output-format stream-json`, `--verbose`, `--include-partial-messages`.
- `--model <conversation['model']>` (only when model is not None).
- `--permission-mode acceptEdits`.
- `--append-system-prompt <render_mode_context(current_mode, conversation)>` — call
  `overseer.mode_prompts.render_mode_context(mode, conversation)` (wrap in try/except;
  skip the flag if it returns empty). `mode = conversation.get('current_mode') or 'observe'`.
- `--tools <comma-joined REAL claude tool names>` — map the abstract tokens from
  `overseer.mode_gate.resolve_tool_allowlist(mode)` to real claude tool names with this
  EXACT mapping, order-preserving, de-duplicated, comma-joined (NOT space-joined):
      read -> Read, search -> Grep, list -> Glob, write -> Write, diff -> Read,
      drive-ui -> Read, push -> Write
  (Drop any abstract token with no mapping. observe -> {Read,Grep,Glob}; brief-author ->
  {Read,Grep,Write}.) Omit the `--tools` flag entirely if the mapped list is empty.
- `--resume <claude_session_id>` when a session id exists; append `--fork-session` when
  rewind_to_index is not None.

For the AGY backend (agent_backend == 'agy'): keep the existing minimal shape — `-p`
is allowed, but NO `--model`, NO `--permission-mode`, NO `--append-system-prompt`, NO
`--tools`/mode knobs (agy self-selects). user_text still flows via stdin.

Define the tool-name map and the abstract->real helper as a dict/closure NESTED INSIDE
`_build_argv` (a NEW top-level function or module constant will not auto-commit cleanly).

# Non-Goals

INTEGRATION is out of scope — do not wire, call, or alter turn_runner.py, web_api.py,
service.py, or any seam builder; do not spawn a real agent / subprocess / model API / SSE /
network (the injected runner remains the only process path). Stdlib + sibling overseer
modules only. Edit no test; touch no file other than overseer/driver.py.

# Edge Cases

- model is None (agy, or unset): omit `--model`.
- current_mode missing/None: default to 'observe' before mapping tools and rendering context.
- render_mode_context raising (unknown mode): swallow and skip `--append-system-prompt`.
- a mode whose mapped tool list is empty: omit `--tools` rather than emitting an empty value.

# Deliverables

overseer/driver.py, GREEN under
`python -m pytest tests/overseer/test_driver_headless.py tests/overseer/test_driver.py -q`.
