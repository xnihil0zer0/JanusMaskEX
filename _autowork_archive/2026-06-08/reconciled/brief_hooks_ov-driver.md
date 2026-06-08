---
interfaces: "overseer/driver.py: run_turn(conversation, user_text, *, runner, env_builder, jail_builder, stream_parser, **kw) -> AssistantTurn; AssistantTurn(session_id, text, tool_uses). Imports overseer.mode_gate (tool allowlist) + overseer.model_select."
meta_task_type: data_model
---

# Title

overseer/driver.py

# Scope

Build the NEW single-file, whole-file, stdlib-only module overseer/driver.py,
IMPL-only against its pre-committed RED oracle tests/overseer/test_driver.py
(AUTHORITATIVE — reproduce the EXACT public surface it imports). The driver is a
DETERMINISTIC shell around INJECTED seams (runner / env_builder / jail_builder /
stream_parser). It NEVER spawns a real process — every process path goes through
the injected `runner`. It builds the claude stream-json argv, wraps it via
`jail_builder`, spawns via `runner`, parses the NDJSON stream lines into an
AssistantTurn, and relays events to the injected `stream_parser`.

# Required plan shape

Emit EXACTLY ONE task (do NOT decompose / split into subtasks):
- meta_task_type: data_model
- files_touched: ["overseer/driver.py"]  (this file ONLY)
- verification_command: "python -m pytest tests/overseer/test_driver.py -q"
- spec_author: null
- IMPL-only: the oracle is a pre-committed precondition — author/edit NO test; touch no other file.

# Inputs

The committed oracle tests/overseer/test_driver.py is the contract. Key structural facts from it:
- `run_turn(conversation, user_text, *, runner, env_builder, jail_builder, stream_parser, **kw) -> AssistantTurn`.
  `conversation` is a dict: {claude_session_id, current_mode, model, agent_backend, transcript}.
- `runner(argv, *, env=None, stdin=None, **kw)` returns a LIST of stream-json NDJSON line strings; call it EXACTLY ONCE.
- AssistantTurn carries: `.session_id` (captured from the init event's session_id),
  `.text` (text_delta deltas accumulated verbatim), `.tool_uses` (list of the tool_use
  content blocks; each has "name").
- argv MUST contain: `--output-format`, `stream-json`, `--include-partial-messages`,
  `--model <conversation['model']>`, and `--tools <space/comma-joined allowlist>` where the
  allowlist comes from `overseer.mode_gate.resolve_tool_allowlist(current_mode)` (the oracle
  checks every allowed tool string appears in the joined argv).
- APPEND uses `--resume <claude_session_id>`; a rewind/branch uses `--fork-session`.
- Wrap the built argv via `jail_builder(cmd, **kw)`; build env via `env_builder(...)`.
  Feed `user_text` via stdin. Parse only through the injected seams — no real subprocess,
  no network, no model call.

# Non-Goals

No real agent spawn / subprocess / model API call / SSE / network — the injected runner is the
ONLY process path. Stdlib only (it MAY import sibling overseer modules by path). No other files.
Does not author its own oracle.

# Deliverables

overseer/driver.py, GREEN under `python -m pytest tests/overseer/test_driver.py -q`.
