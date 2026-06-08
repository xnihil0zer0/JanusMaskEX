---
interfaces: "overseer/session_store.py: SessionStore.list_conversations() -> list[dict] — one {conversation_id, current_mode, turn_count, preview} summary per stored conversation, insertion order, non-mutating."
meta_task_type: data_model
---

# Title

overseer/session_store.py

# Scope

EDIT the EXISTING module overseer/session_store.py (single file, IMPL-only) to
ADD ONE new method, `SessionStore.list_conversations`, backing the browsable chat
session-history feature. Add NOTHING else; do not modify any existing method.

# Required plan shape

Emit EXACTLY ONE task (do NOT decompose / split):
- meta_task_type: data_model
- files_touched: ["overseer/session_store.py"]  (this file ONLY)
- verification_command: "python -m pytest tests/overseer/test_session_store_list.py tests/overseer/test_session_store.py -q"
- spec_author: null
- IMPL-only: both oracles are pre-committed; author/edit NO test; touch no other file.
- test_spec MUST satisfy the plan validator (prior drafts were REJECTED for missing
  these — emit them):
  - non_goals MUST contain the literal word "integration" — this is an IMPL-only task
    verified by a pre-committed oracle, so NO integration test is authored here; state
    that explicitly to claim the integration excuse.
  - regression_tests MUST list AT LEAST TWO entries reflecting the edge cases below, e.g.
    [{"name": "test_preview_is_empty_for_a_conversation_with_no_turns"},
     {"name": "test_list_does_not_mutate_the_store"}].

# Inputs

The current overseer/session_store.py is staged into your inbox/targets — READ it
on your second turn. The store maps conversation id -> record dict with keys
{claude_session_id, current_mode, unlocked_modes, model, agent_backend,
transcript}; internal state is `self._data` (an insertion-ordered dict).

Add `def list_conversations(self) -> List[Dict[str, Any]]:` that returns a list
with ONE summary dict per stored conversation, in `self._data` iteration
(insertion) order. Each summary has EXACTLY these JSON-able keys:
- "conversation_id": the conversation id (the dict key).
- "current_mode": the record's current_mode.
- "turn_count": len(record["transcript"]).
- "preview": the `content` of the FIRST turn whose role == "user" (str), or "" if
  the conversation has no turns / no user turn. (A short preview is fine; you may
  keep the full first-user content — the oracle only checks a substring is present.)

The method MUST NOT mutate the store (no writes, no _save) and must be a single
new method — emit it as ONE symbol patch named 'SessionStore.list_conversations'
with no sibling nodes.

# Non-Goals

INTEGRATION out of scope — do not touch web_api.py, service.py, the frontend, or
any existing method. Stdlib only. Edit no test.

# Edge Cases

- empty store -> returns [].
- a conversation with an empty transcript -> turn_count 0, preview "".
- a conversation whose first turn is an assistant turn -> preview is the first
  USER turn's content (or "" if none).

# Deliverables

overseer/session_store.py GREEN under
`python -m pytest tests/overseer/test_session_store_list.py tests/overseer/test_session_store.py -q`.
