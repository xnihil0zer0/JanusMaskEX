# HANDOFF — Overseer chat STILL produces "(no output)" after the headless-argv fix

**Date:** 2026-06-08
**Status:** Root cause CONFIRMED with live evidence. Fix designed, not yet landed.
**Severity:** Blocks the entire overseer chat panel — every turn returns an empty assistant message.

---

## TL;DR

The earlier fix (`overseer/driver._build_argv`, commit `ff42461`) was **necessary but
not sufficient**. It made the claude argv a correct headless invocation, and claude now
**genuinely runs and answers**. The remaining bug is in the **stream parser** in
`overseer/driver.run_turn`: it looks for the WRONG event shapes, so it captures the
session id but **none of the assistant text** → `turn.text == ""` → the WebUI renders
`res.text || "(no output)"`.

**The unit oracle (`tests/overseer/test_driver.py`) passed the whole time because its
`CLAUDE_STREAM` fixture is UNREALISTIC** — it feeds bare top-level `content_block_delta`
events that claude's real `-p --output-format stream-json` output never emits. So the
test is GREEN against a fiction while the live path is broken. This is the crux: **fix
the oracle fixture to real event shapes FIRST (it will go RED), then fix `run_turn`.**

---

## Evidence (reproduced live, no jail, real auth)

Command (the exact driver argv for `observe` mode + prompt on stdin):

```bash
CLAUDE="/home/xnihil0zer0/JanusMaskJR/.agents/claude-code/node_modules/.bin/claude"
echo "Say the single word HELLO and nothing else." | "$CLAUDE" \
  -p --output-format stream-json --verbose --include-partial-messages \
  --model opus --permission-mode acceptEdits --tools Read,Grep,Glob
```

claude exited 0 and **answered "HELLO"**. A full 12-line capture is saved at
`_autowork_archive/overseer_no_output_evidence/real_claude_stream_sample.jsonl`.
The event sequence was:

| line | `type` | notes |
|---|---|---|
| 0 | `system` (subtype `init`) | carries `session_id` — driver DOES capture this ✓ |
| 1 | `system` (subtype `status`) | |
| 2 | `rate_limit_event` | |
| 3–6 | **`stream_event`** | the partial-message deltas, **NESTED** under `event` |
| 7 | **`assistant`** | `message.content = [{"type":"text","text":"HELLO"}]` — the full text |
| 8–10 | **`stream_event`** | |
| 11 | **`result`** (subtype `success`) | `is_error=false`, **`result":"HELLO"`**, has `session_id` |

The live `state/overseer/sessions.json` shows exactly this symptom: each turn captures a
fresh `claude_session_id` (init event received) but `transcript[assistant].content == ""`.

### Exact shapes the parser must handle

**`stream_event` envelope** (this is where `--include-partial-messages` puts the deltas —
the real `content_block_delta`/`content_block_start` are INSIDE `event`, never top-level):
```json
{"type":"stream_event","event":{"type":"content_block_delta",
  "delta":{"type":"text_delta","text":"HEL"}}}
{"type":"stream_event","event":{"type":"content_block_start",
  "content_block":{"type":"tool_use","name":"Read", ...}}}
```

**`assistant`** (complete, non-partial message — simplest source of full text):
```json
{"type":"assistant","message":{"role":"assistant",
  "content":[{"type":"text","text":"HELLO"}], ...}}
```

**`result`** (final, authoritative answer + session id):
```json
{"type":"result","subtype":"success","is_error":false,
  "result":"HELLO","session_id":"28097c97-...","stop_reason":"end_turn", ...}
```

---

## The bug, precisely

`overseer/driver.py` → `run_turn` parse loop (currently ~lines 155–180):
- `if _is_init_event(event):` → captures `session_id`. **WORKS.**
- `if etype == 'content_block_delta':` → accumulates `delta.text` into `turn.text`.
  **NEVER MATCHES** — real deltas are wrapped in `type=="stream_event"`.
- `if etype == 'content_block_start':` → collects `tool_use`. **NEVER MATCHES** — same reason.
- There is **no handler** for `stream_event`, `assistant`, or `result`.

Net: `turn.text` stays `""`, `turn.tool_uses` stays empty. The init event alone yields a
session id, which is why the symptom is "session captured, text empty".

---

## The fix (design)

In `run_turn`'s per-event loop, BEFORE the existing `content_block_delta`/`content_block_start`
checks:

1. **Unwrap `stream_event`:** if `event.get('type') == 'stream_event'`, replace
   `event = event.get('event') or {}` and re-read `etype` so the existing
   `content_block_delta` (→ `turn.text` + `sink`) and `content_block_start` (→ `tool_uses`)
   logic runs on the inner event. This preserves live streaming for the SSE relay.
2. **Handle the `assistant` message event:** when `etype == 'assistant'`, walk
   `event['message']['content']` and append each `{"type":"text"}` block's `text` to
   `turn.text` (covers the non-partial path; also tool_use blocks live here).
   NOTE the existing agy fixture uses a DIFFERENT assistant shape
   (`{"type":"assistant","content":"hi there"}`, a bare string) — keep that working too:
   accept either `message.content` (list, claude) or top-level `content` (str, agy).
3. **Capture `result` as the authoritative fallback:** when `etype == 'result'` and
   `not is_error`, if `turn.text` is still empty set it from `event.get('result')`; also
   capture `session_id` from here (defensive — init already provides it).

To avoid DOUBLE-counting (deltas + assistant + result can all carry the same text),
recommended approach: **accumulate streaming text from `stream_event`→`text_delta` for the
live sink, but treat the terminal `assistant`/`result` text as the source of truth** — e.g.
build `turn.text` from deltas, then if a non-partial `assistant`/`result` text exists, prefer
it (overwrite) so a parser that misses some deltas still returns the complete message. Pick
one source of truth and make the oracle pin it; do not sum all three.

### Oracle-first (REQUIRED — this is what let the bug ship)

`tests/overseer/test_driver.py` `CLAUDE_STREAM` must be rewritten to the REAL shapes above
(stream_event envelopes + an `assistant` event + a `result` event). Against today's
`run_turn`, the realistic fixture makes `test_returns_assistant_turn_with_session_text_and_tools`
go **RED** (text == "" instead of "Hello world"). That red test is the contract. Add a
dedicated `tests/overseer/test_driver_stream_shapes.py` asserting:
- text is recovered from a `stream_event`-wrapped `text_delta` stream,
- text is recovered when ONLY an `assistant` event carries it (no deltas),
- text is recovered from the `result` event as a last resort,
- a `tool_use` inside a `stream_event`→`content_block_start` is collected,
- the agy bare-`assistant` shape still works (don't regress `test_agy_backend_*`),
- session id still captured from init.
Commit the oracle(s) BEFORE dispatching the fix (the gate verifies from HEAD — see lessons).

---

## Secondary issues found (note, fix opportunistically — NOT the no-output cause)

1. **MCP / settings isolation gap.** The overseer argv has NO `--settings`,
   `--mcp-config`, `--strict-mcp-config`, or `--setting-sources ''` (the worker argv in
   `harness/config.yaml agents.claude.args` has all four). Consequence: the init event shows
   the jailed overseer inherited the OPERATOR's full MCP surface — Gmail/Calendar/Drive
   (`needs-auth`), `codebase-memory-mcp` (`connected`), playwright, noblegreed — plus all the
   operator's slash commands. The overseer should run isolated like the worker. Add the four
   flags to `_build_argv` (claude branch) and point `--settings` at a dedicated overseer
   settings file (or reuse `config/claude_worker.json`). This is a privilege/containment
   concern; the mode `--tools` allowlist still constrains tool USE, but the agent should not
   see the operator's servers/commands at all.
2. **Mode not applied in the live test.** The failing live turn ran in `current_mode:
   observe` (the user's "testing" send), not `brief-author`. The mode-on-send fix (`f1aa33c`)
   is backend-correct, but verify the FRONTEND actually transmits `body.mode` on the very
   first send AND that the mode select reflects the user's choice before the first send
   (re-check `sendChat` / `overseerChat.mode` init in `tools/webui_static/app.js`). Not the
   no-output cause, but confirm during the live re-test.

---

## How to land it (pipeline, per this project's rules)

`overseer/driver.py` is the target. Single-file edit of the EXISTING `run_turn` function →
symbol patch is fine (it MODIFIES an existing symbol; do NOT add new top-level symbols — nest
any helper inside `run_turn`). Recipe proven this session:

1. Rewrite `CLAUDE_STREAM` in `test_driver.py` to real shapes + add
   `test_driver_stream_shapes.py`. Run them — confirm RED against current `run_turn`.
2. `git commit` the oracle changes (test-only, hand-authoring allowed). **Gate verifies from
   HEAD — uncommitted oracles are invisible and the build will roll back.**
3. Author `brief_hooks_overseer_driver_stream_parse.md` (meta_task_type `data_model`,
   files_touched `["overseer/driver.py"]`, verification_command naming BOTH oracle files).
   Spell out the three event shapes + the single-source-of-truth rule in implementation_notes.
   Include the test_spec block (≥2 edge-case regression_tests + the word "integration" in
   non_goals — the plan validator rejects drafts without them).
4. Allowlist the slug, clear `state/control/autowork/full_stop` + `state/control/orchestrator.flag`,
   run the daemon (or `python -m harness.autowork_daemon --state-dir state --once`).
5. After commit: restore safe posture (recreate `full_stop`, `orchestrator.flag=pause`,
   allowlist → deny-all, kill the daemon).

All the autonomous-loop gotchas are in memory `overseer-chat-fix-features-session` (commit
oracles first; harden the PLAN not the brief; planner's generic `T1` id collides with old
`processed/` markers — rename; daemon can wedge → kill -9 + restart).

---

## Live verification recipe (after the fix)

```bash
# 1. confirm the parser recovers text from a REAL stream sample (no model spend):
python3 - <<'PY'
import json
from overseer.driver import run_turn
lines = open('_autowork_archive/overseer_no_output_evidence/real_claude_stream_sample.jsonl').read().splitlines()
class P:  # no-op stream parser
    def handle_event(self, e): pass
def runner(argv, *, env=None, stdin=None, **k): return lines
out = run_turn({'agent_backend':'claude','model':'opus','current_mode':'observe','claude_session_id':None},
               'hi', runner=runner, env_builder=lambda *a,**k:{}, jail_builder=lambda c,**k:list(c), stream_parser=P())
print('text=', repr(out.text), '| session=', out.session_id)   # MUST be 'HELLO', not ''
PY

# 2. then live: start the server and send a chat turn
#    ! JANUSMASK_OVERSEER_ENABLED=1 python -m tools.webui_server   (operator runs; CC can't hold the bind)
#    open #/chat, pick brief-author, send a message → expect real assistant text
```

The step-1 snippet is also the seed of the new RED oracle — it returns `''` today and must
return `'HELLO'` after the fix.

---

## Key files

- `overseer/driver.py` — `run_turn` parse loop (the fix) + `_build_argv` (already fixed `ff42461`).
- `tests/overseer/test_driver.py` — `CLAUDE_STREAM` fixture is the unrealistic one to replace.
- `overseer/turn_runner.py` — real seams (`make_seams`/`run_chat_turn`); folds the stream, writes
  `logs/overseer_chat.jsonl`, persists to the store. The `result`/`is_error` are visible here too.
- `_autowork_archive/overseer_no_output_evidence/real_claude_stream_sample.jsonl` — captured evidence.
- memory `overseer-chat-fix-features-session` — full session log + 8 pipeline lessons.
