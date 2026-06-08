---
interfaces: "tools/webui_static/{app.js,index.html,styles.css}: add chat panel hooks — chatIsOpen() SSE-skip guard, pages.chat route, chat-transcript/chat-input/chat-resend anchors, #/chat nav link, --mode-tier-{r,w,s} CSS vars."
meta_task_type: harness_plumbing
---

# Title

EDIT tools/webui_static/app.js + tools/webui_static/index.html + tools/webui_static/styles.css

# Scope

THIN ADDITIVE frontend edit (ONE leaf — do NOT split) against its pre-committed
RED oracle tests/overseer/test_chat_ui.py (AUTHORITATIVE, STRUCTURAL — it greps
the static files for the load-bearing chat-panel hooks). Add a chat page to the
existing stdlib WebUI SPA, mirroring the EXISTING `briefEditorIsOpen()` clobber
guard precedent already in app.js. Live fidelity is verified later by the Phase-H
Playwright sweep; this leaf only guarantees the structural contract.

# Required plan shape

Emit EXACTLY ONE task (do NOT decompose / split into subtasks — a split shares
this single oracle and DEADLOCKS):
- meta_task_type: harness_plumbing
- files_touched: ["tools/webui_static/app.js", "tools/webui_static/index.html", "tools/webui_static/styles.css"]
- verification_command: "python -m pytest tests/overseer/test_chat_ui.py -q"
- spec_author: null
- IMPL-only / ADDITIVE: author/edit NO test; add the hooks below WITHOUT removing or rewriting
  existing SPA logic. Keep diffs thin.

# Inputs

The committed oracle tests/overseer/test_chat_ui.py is the contract. It requires EXACTLY these
strings to be present after the edit:
- app.js:
  - a `function chatIsOpen` predicate (mirror the existing `briefEditorIsOpen()` function);
  - the literal guard line `if (chatIsOpen()) return;` wired into the SAME SSE re-render skip path
    where `briefEditorIsOpen()` is already checked (so a live tick never clobbers the chat
    input/transcript);
  - a `pages.chat` route registration (the form `pages.chat` or `pages['chat']`);
  - the self-managed append-only DOM anchors `chat-transcript`, `chat-input`, and `chat-resend`
    (the resend-transcript control).
- index.html: a `#/chat` nav link (hash route).
- styles.css: the per-mode color custom properties `--mode-tier-r`, `--mode-tier-w`, `--mode-tier-s`
  (one source-of-truth tier hue ramp).
Find the existing `briefEditorIsOpen` guard + the SSE re-render subscriber + the `pages` route map in
app.js and extend them additively in the same style.

# Non-Goals

No build step / framework / bundler / network. No real SSE wiring beyond the existing /events channel
(already extended server-side). Do NOT rewrite existing SPA functions or remove existing routes/styles.
ONE leaf editing exactly the three named static files. Does not author its own oracle.

# Deliverables

tools/webui_static/{app.js,index.html,styles.css}, GREEN under
`python -m pytest tests/overseer/test_chat_ui.py -q`.
