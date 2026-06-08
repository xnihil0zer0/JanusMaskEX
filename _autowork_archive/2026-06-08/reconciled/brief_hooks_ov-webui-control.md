---
interfaces: "tools/webui_control.py: extend ControlHandlers._dispatch_post with /api/chat/send + /api/chat/resend, _dispatch_put with /api/chat/mode; add NEW handler methods delegating to overseer.web_api."
meta_task_type: harness_plumbing
---

# Title

EDIT tools/webui_control.py

# Scope

THIN ADDITIVE wiring into the existing module tools/webui_control.py against its
pre-committed RED oracle tests/overseer/test_webui_control_overseer.py
(AUTHORITATIVE). Register the overseer chat MUTATION routes in the existing
`ControlHandlers` class-attribute dispatch tables and add NEW handler methods
that DELEGATE to `overseer.web_api` — do NOT rewrite any existing method body.
Mirror the AW5a v2 autowork-route extension precedent already in this file.

# Required plan shape

Emit EXACTLY ONE task (do NOT decompose / split into subtasks):
- meta_task_type: harness_plumbing
- files_touched: ["tools/webui_control.py"]  (this file ONLY)
- verification_command: "python -m pytest tests/overseer/test_webui_control_overseer.py -q"
- spec_author: null
- IMPL-only: the oracle is a pre-committed precondition — author/edit NO test; touch no other file.
- ADDITIVE only: ADD new dispatch-table ENTRIES + new methods; never rewrite existing method bodies
  (never-patch-class-methods). The orchestrator's AST merge preserves existing entries/methods.

# Inputs

The committed oracle tests/overseer/test_webui_control_overseer.py is the contract. Exact required edits:
- Extend `ControlHandlers._dispatch_post` (a `dict[str, tuple[str,str]]` class attribute, format
  `route -> (handler_method_name, arg_shape)`) with:
    `"/api/chat/send": ("post_chat_send", "body")` and
    `"/api/chat/resend": ("post_chat_resend", "body")`.
- Add a chat mode-set MUTATION route — register `"/api/chat/mode": ("put_chat_mode", "body")` in
  `ControlHandlers._dispatch_put` (the oracle accepts a "chat/mode" route under POST or PUT).
- Add the NEW handler methods `post_chat_send`, `post_chat_resend`, `put_chat_mode` on
  ControlHandlers. Each handler body MUST reference `overseer.web_api` (import and delegate — e.g.
  construct/reuse an `OverseerWebApi` over the session store and call chat_send / chat_resend /
  mode_set). The oracle greps the handler SOURCE for the substring "web_api", so the delegation must
  be literal, not reimplemented inline. Return the handler tuple shape used by siblings
  (`tuple[int, dict]`).
- PRESERVE existing routes: /api/briefs, /api/autowork/start, /api/rebuild/start (and all others)
  must remain in _dispatch_post after the merge.

# Non-Goals

No real agent spawn / live SSE in the tested path (delegation target overseer.web_api uses injected
seams). Do NOT rewrite existing handler methods or the existing dispatch entries. Additive
dict-extension + new methods only. Touch no file other than tools/webui_control.py. Does not author
its own oracle.

# Deliverables

tools/webui_control.py, GREEN under `python -m pytest tests/overseer/test_webui_control_overseer.py -q`.
