---
interfaces: "overseer/driver.py: run_turn(conversation, user_text, *, runner, env_builder, jail_builder, stream_parser, **kw) -> AssistantTurn. AssistantTurn(session_id, text, tool_uses). The fold loop reads NDJSON stream-json lines and accumulates text/tool_uses. _build_argv is already correct — DO NOT touch it."
meta_task_type: data_model
---

# Title

overseer/driver.py

# Scope

EDIT the EXISTING module `overseer/driver.py` (single file, IMPL-only) so the
`run_turn` stream-fold loop reads the REAL `claude -p --output-format
stream-json --include-partial-messages` event shapes. The chat panel currently
returns an EMPTY assistant turn ("(no output)") for every prompt EVEN THOUGH
claude genuinely answers: the fold loop only matches BARE top-level
`content_block_delta` / `content_block_start` events, which real claude NEVER
emits. In reality the partial-message deltas/blocks are NESTED under a
`stream_event` envelope, the complete message arrives as an `assistant` event,
and a terminal `result` event carries the authoritative answer. So `turn.text`
stays `""` while only the init event's `session_id` is captured.

Fix ONLY the per-event loop inside `overseer.driver.run_turn` (and any helper
you nest INSIDE `run_turn` — do NOT add new top-level module symbols, do NOT
touch `_build_argv`, `_is_init_event`, or `AssistantTurn`).

# Required plan shape

Emit EXACTLY ONE task (do NOT decompose / split into subtasks):
- meta_task_type: data_model
- files_touched: ["overseer/driver.py"]  (this file ONLY)
- verification_command: "python -m pytest tests/overseer/test_driver_stream_shapes.py tests/overseer/test_driver.py -q"
- spec_author: null
- IMPL-only: BOTH oracles are pre-committed preconditions — author/edit NO test; touch no other file.
- test_spec MUST carry ≥2 edge-case regression_tests (e.g. "assistant event alone
  with no deltas yields the text", "result event alone yields the text as a last
  resort") AND the literal word "integration" in the task non_goals.

# Inputs

The current `overseer/driver.py` is staged into your inbox/targets — READ it on
your second turn and edit the body of `run_turn` in place, preserving everything
else (`_build_argv`, the agy branch, `_is_init_event`, the `AssistantTurn`
dataclass, the `stream_parser.handle_event(event)` call on EVERY raw line, the
`sink` relay, the init/session-id capture, and the final `return turn`).

The two committed oracles are the contract:
`tests/overseer/test_driver_stream_shapes.py` (the NEW fix contract) and
`tests/overseer/test_driver.py` (its `CLAUDE_STREAM` fixture is now realistic).

## The three real event shapes (from captured live evidence)

1. **`stream_event` envelope** — the `--include-partial-messages` deltas/blocks
   are wrapped, never top-level. The inner `content_block_delta` /
   `content_block_start` lives under `event`:
   ```json
   {"type":"stream_event","event":{"type":"content_block_delta",
     "delta":{"type":"text_delta","text":"HEL"}}}
   {"type":"stream_event","event":{"type":"content_block_start",
     "content_block":{"type":"tool_use","name":"Read", ...}}}
   ```
2. **`assistant`** — the complete message; `message.content` is a LIST of blocks
   (claude shape). The agy backend instead puts a bare STRING at top-level
   `content` (no `message` wrapper):
   ```json
   {"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"HELLO"}]}}
   {"type":"assistant","content":"hi there"}
   ```
3. **`result`** — terminal, authoritative answer + session id:
   ```json
   {"type":"result","subtype":"success","is_error":false,"result":"HELLO","session_id":"..."}
   ```

## The required behaviour

Keep calling `stream_parser.handle_event(event)` on EVERY decoded raw line FIRST
(before any unwrapping), and keep the init/session-id branch. Then, per event:

- **Unwrap `stream_event` FIRST:** if the event's `type` is `"stream_event"`,
  replace `event = event.get('event') or {}` and re-read its `type`, so the
  existing `content_block_delta` / `content_block_start` logic runs on the INNER
  event.
- **`content_block_delta` → `text_delta`:** accumulate the chunk into a deltas
  accumulator AND relay it to `sink` (preserve live streaming for the SSE relay).
- **`content_block_start` → `tool_use`:** append the block to `turn.tool_uses`.
- **`assistant`:** read `event['message']['content']` when `message` is a dict
  (claude: a list of blocks → concat the `text` of each `{"type":"text"}` block),
  ELSE read top-level `event['content']` (agy: a bare string). Store as the
  assistant text.
- **`result` with `is_error` falsy:** store `event.get('result')` (a string) as
  the result text, and defensively capture `session_id` from it too.

**Single source of truth — do NOT sum the three.** Build `turn.text` so that the
complete terminal text wins over the partial deltas (a parser that dropped a
delta must still return the whole answer): prefer the `assistant` text, then the
`result` text, then the accumulated deltas. Concretely: start empty; if deltas
are non-empty use them; if a non-empty result text exists overwrite with it; if a
non-empty assistant text exists overwrite with it. (So precedence is
assistant > result > deltas, and an empty later source never blanks an earlier
one.) Assign the chosen text to `turn.text` before `return turn`.

# Non-Goals

INTEGRATION is out of scope — do not wire, call, or alter `turn_runner.py`,
`web_api.py`, `service.py`, `_build_argv`, or any seam builder; do not spawn a
real agent / subprocess / model API / SSE / network (the injected `runner`
remains the only process path). Do not add `--settings`/`--mcp-config` flags
(separate concern). Stdlib + sibling overseer modules only. Edit no test; touch
no file other than `overseer/driver.py`. Do NOT collect `tool_use` blocks out of
the `assistant` message (the `content_block_start` path is the sole tool source —
avoid double-counting).

# Edge Cases

- An `assistant` event arrives but NO `stream_event` deltas: `turn.text` must be
  the assistant text (regression test).
- ONLY a `result` event carries text (no deltas, no assistant): `turn.text` must
  be the result text as a last resort (regression test).
- Both partial deltas AND a complete assistant/result exist: the COMPLETE text
  wins (no truncation, no concatenation/double-count).
- `result` with `is_error` truthy: ignore its `result` text.
- agy bare-string `assistant` (top-level `content` is a str): still captured.
- A malformed/empty `stream_event` (`event` missing): unwrap to `{}` and skip
  without raising.

# Deliverables

`overseer/driver.py`, GREEN under
`python -m pytest tests/overseer/test_driver_stream_shapes.py tests/overseer/test_driver.py -q`.
