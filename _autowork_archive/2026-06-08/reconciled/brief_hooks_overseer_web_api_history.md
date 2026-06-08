---
interfaces: "overseer/web_api.py: OverseerWebApi.chat_list() -> {'conversations': [summary,...]} via store.list_conversations; chat_load(cid) -> {'conversation_id','current_mode','turns':[...]} (KeyError if unknown)."
meta_task_type: data_model
---

# Title

overseer/web_api.py

# Scope

EDIT the EXISTING module overseer/web_api.py (single file, IMPL-only) to ADD TWO
new methods to OverseerWebApi — `chat_list` and `chat_load` — backing the
browsable chat session-history feature. Do not modify any existing method.

# Required plan shape

Emit EXACTLY ONE task (do NOT decompose / split):
- meta_task_type: data_model
- files_touched: ["overseer/web_api.py"]  (this file ONLY)
- verification_command: "python -m pytest tests/overseer/test_web_api_history.py tests/overseer/test_web_api.py -q"
- spec_author: null
- IMPL-only: both oracles are pre-committed; author/edit NO test; touch no other file.
- test_spec MUST satisfy the plan validator (prior drafts were REJECTED for missing
  these — emit them):
  - non_goals MUST contain the literal word "integration" — this is an IMPL-only task
    verified by a pre-committed oracle, so NO integration test is authored here; state
    that explicitly to claim the integration excuse.
  - regression_tests MUST list AT LEAST TWO entries reflecting the edge cases below, e.g.
    [{"name": "test_chat_list_empty"},
     {"name": "test_chat_load_unknown_conversation_raises"}].

# Inputs

The current overseer/web_api.py is staged into your inbox/targets — READ it on
your second turn. OverseerWebApi wraps `self._store` (a SessionStore) which now
exposes `list_conversations()` (one {conversation_id, current_mode, turn_count,
preview} summary per conversation). The class already has `_transcript(rec)`
(static) returning a record's turn list, and `chat_history(cid)`.

Add these two methods (emit as TWO symbol patches — names
'OverseerWebApi.chat_list' and 'OverseerWebApi.chat_load' — each a single method
with NO sibling nodes):
- `def chat_list(self) -> Dict[str, Any]:` returns `{"conversations":
  self._store.list_conversations()}` (a JSON-able dict).
- `def chat_load(self, cid: str) -> Dict[str, Any]:` returns the full
  conversation for loading back into the panel:
  `{"conversation_id": cid, "current_mode": rec["current_mode"], "turns":
  self._transcript(rec)}` where `rec = self._store.get(cid)`. An unknown cid must
  propagate the store's KeyError (do NOT catch it) — mirrors chat_history.

# Implementation notes

WHOLE-FILE EMISSION REQUIRED: chat_list and chat_load are BRAND-NEW methods. The
symbol-patch applier can only REPLACE existing symbols and raises KeyError on a
new 2-part qualname (e.g. 'OverseerWebApi.chat_list'). Therefore emit the COMPLETE
overseer/web_api.py file as a whole-file submission (NOT a __JANUSMASK_PATCHES__
symbol patch): output the entire module verbatim with the two new methods added
and every existing method byte-identical.

# Non-Goals

INTEGRATION out of scope — do not touch session_store.py, service.py, the
frontend, or any existing method. No driver/agent/subprocess. Stdlib + sibling
overseer modules only. Edit no test.

# Edge Cases

- empty store -> chat_list returns {"conversations": []}.
- chat_load on an unknown conversation -> raises KeyError (uncaught).

# Deliverables

overseer/web_api.py GREEN under
`python -m pytest tests/overseer/test_web_api_history.py tests/overseer/test_web_api.py -q`.
