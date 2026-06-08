---
interfaces: "overseer/web_api.py: OverseerWebApi(session_store); .chat_send(body)->{conversation_id,job_id}; .chat_history(cid); .mode_get(cid)->{current_mode,available_modes}; .mode_set(cid,mode)->{ok,current_mode}; .mode_unlock(cid,mode); .model_list(); .chat_resend(cid,*,rewind_to_index=None). Imports session_store + modes + model_select."
meta_task_type: data_model
---

# Title

overseer/web_api.py

# Scope

Build the NEW single-file, whole-file, stdlib-only module overseer/web_api.py,
IMPL-only against its pre-committed RED oracle tests/overseer/test_web_api.py
(AUTHORITATIVE). `OverseerWebApi` operates on an INJECTED `session_store`
(a `overseer.session_store.SessionStore`) and returns plain JSON-able dicts. It
is the JSON handler layer for the chat panel; the tested paths do NOT spawn an
agent (chat_send appends the user turn and returns a job_id without running the
driver). Build it AFTER session_store/modes/model_select (all already built).

# Required plan shape

Emit EXACTLY ONE task (do NOT decompose / split into subtasks):
- meta_task_type: data_model
- files_touched: ["overseer/web_api.py"]  (this file ONLY)
- verification_command: "python -m pytest tests/overseer/test_web_api.py -q"
- spec_author: null
- IMPL-only: the oracle is a pre-committed precondition — author/edit NO test; touch no other file.
- test_spec hygiene (so the plan validates): reflect AT LEAST TWO of the spec edge_cases as
  `regression_tests` or `property_tests` entries; the integration test is EXCUSED in non_goals
  (this is a unit-level oracle — see Non-Goals).

# Inputs

The committed oracle tests/overseer/test_web_api.py is the contract. Key facts from it:
- Constructor: `OverseerWebApi(store)` — a single positional `session_store`. All methods return
  JSON-serializable dicts (the oracle calls json.dumps on them).
- `chat_send(body)`: body is a dict; if `body["conversation_id"]` is absent, CREATE a new
  conversation (default boot mode "observe"), else REUSE it; append a user turn with
  `{"role":"user","content": body["text"]}`; return `{"conversation_id", "job_id"}` (job_id a
  non-empty str). No agent spawn in this path.
- `chat_history(cid)`: returns the conversation's turns (each a dict with "role"/"content").
- `mode_get(cid)`: returns `{"current_mode": <mode>, "available_modes": [...]}` — available_modes
  EXCLUDES locked Tier-S modes (e.g. "push" absent) and INCLUDES Tier-R (e.g. "observe"); default
  current_mode is "observe". Use overseer.modes.list_available_modes / requires_unlock.
- `mode_set(cid, mode)`: to a permitted (Tier-R or unlocked) target returns `{"ok": True,
  "current_mode": mode}` and persists; to a LOCKED Tier-S target returns `{"ok": False, ...}` and
  does NOT change current_mode.
- `mode_unlock(cid, mode)`: records the per-session unlock so a subsequent mode_set to that Tier-S
  mode succeeds.
- `model_list()`: returns the available models (overseer.model_select.AVAILABLE_MODELS).
- `chat_resend(cid, *, rewind_to_index=None)`: None resends the whole transcript; an index
  branches/rewinds from that turn.
Persist all mutations through the injected session_store (create/get/append_turn/set_mode/
unlock_mode/set_model/set_session_id, store_path seam) — re-reading via the store must reflect them.

# Non-Goals

No agent spawn / subprocess / model call / SSE / network in any tested path (the driver/actions are
NOT exercised here). Stdlib only. No other files. Does not author its own oracle. This is a
UNIT-level oracle exercising in-process handler logic over an injected store; no integration test
is authored or required (integration coverage is excused).

# Deliverables

overseer/web_api.py, GREEN under `python -m pytest tests/overseer/test_web_api.py -q`.
