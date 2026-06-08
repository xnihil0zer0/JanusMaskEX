---
interfaces: "tools/webui_static/app.js: newChatSession() resets overseerChat (cid=null, buffer=[]) + clears transcript and is wired to a #chat-clear button in pages.chat; sendChat() puts body.mode = overseerChat.mode on the POST."
meta_task_type: harness_plumbing
---

# Title

EDIT tools/webui_static/app.js + tools/webui_static/styles.css

# Scope

THIN ADDITIVE frontend edit (ONE leaf — do NOT split) against its pre-committed
RED structural oracle tests/overseer/test_chat_ui_clear_mode.py (AUTHORITATIVE —
it greps the static files for the load-bearing hooks). Adds, to the EXISTING chat
panel: (1) a CLEAR button that starts a NEW chat session, and (2) mode-on-send so
the operator-selected mode reaches the server on the first send. Live fidelity is
verified later by the Phase-H Playwright sweep; this leaf guarantees the
structural contract only. Do NOT remove or rewrite existing SPA logic.

# Required plan shape

Emit EXACTLY ONE task (do NOT decompose / split — a split shares this one oracle
and DEADLOCKS):
- meta_task_type: harness_plumbing
- files_touched: ["tools/webui_static/app.js", "tools/webui_static/styles.css"]
- verification_command: "python -m pytest tests/overseer/test_chat_ui_clear_mode.py tests/overseer/test_chat_ui.py -q"
- spec_author: null
- IMPL-only / ADDITIVE: author/edit NO test; KEEP all existing chat hooks
  (chatIsOpen, pages.chat, chat-transcript/chat-input/chat-resend, the SSE skip
  guard) intact so the existing test_chat_ui.py oracle stays green.

# Inputs

The current tools/webui_static/app.js + styles.css are staged into your
inbox/targets — READ them on your second turn. The chat panel already exists:
`pages.chat` renders the HTML and `setTimeout(_wireChatPanel, 0)` wires the
controls; `overseerChat = { cid, mode, buffer }` is the in-memory state;
`sendChat()` builds `const body = { text };` then `if (overseerChat.cid)
body.conversation_id = overseerChat.cid;` and POSTs to `/api/chat/send`;
`pushChatTurn`/`_wireChatPanel` manage the `#chat-transcript` DOM.

The two committed oracles require EXACTLY these strings to be present after the edit:
- app.js:
  - a `#chat-clear` button anchor — add `<button id="chat-clear" class="btn">🗑 Clear</button>`
    into the controls row of `pages.chat` (the row that already holds `#chat-resend`).
  - a `function newChatSession()` that resets the session for a fresh start. It MUST contain
    the literal statements `overseerChat.cid = null` and `overseerChat.buffer = []`, then clear
    the `#chat-transcript` container's DOM (e.g. set its innerHTML to ""). The NEXT send then
    boots a brand-new conversation server-side (chat_send with no conversation_id).
  - wire it in `_wireChatPanel`: `document.getElementById("chat-clear")?.addEventListener("click", newChatSession);`
  - in `sendChat()`, transmit the active mode: add the literal line `body.mode = overseerChat.mode;`
    after the body is constructed and BEFORE the POST (pairs with the server-side chat_send
    mode-on-create fix so the new conversation boots in the selected mode).
- styles.css: leave the existing chat styling intact (the oracle only asserts the chat surface
  is still styled — `chat-input`/`chat-transcript` remain). The clear button may reuse `.btn`.

Mirror the existing function/handler style in app.js exactly. Keep diffs thin and additive.

# Non-Goals

INTEGRATION/backend is out of scope — do not touch any Python file, the server, or the history
panel (a separate leaf). Do not remove existing chat hooks. No new dependencies.

# Edge Cases

- newChatSession must work whether or not `#chat-transcript` is currently in the DOM (guard the
  getElementById result before touching innerHTML).
- mode-on-send must not break a reused conversation: sending `body.mode` is harmless because the
  server ignores mode when conversation_id is present.

# Deliverables

app.js + styles.css GREEN under
`python -m pytest tests/overseer/test_chat_ui_clear_mode.py tests/overseer/test_chat_ui.py -q`.
