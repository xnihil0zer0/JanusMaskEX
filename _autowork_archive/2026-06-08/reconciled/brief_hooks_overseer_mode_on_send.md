---
interfaces: "overseer/web_api.py: OverseerWebApi.chat_send(body) -> dict (honours body['mode'] on conversation create). Imports overseer.modes (get_mode/list_available_modes/requires_unlock)."
meta_task_type: data_model
---

# Title

overseer/web_api.py

# Scope

EDIT the EXISTING module overseer/web_api.py (single file, IMPL-only) so
`OverseerWebApi.chat_send` honours the operator-selected mode when it CREATES a
new conversation. Today chat_send always boots a new conversation as
`self.DEFAULT_MODE` ('observe'), so a "brief-author" send silently ran read-only
'observe' — the second half of the chat "(no output)" bug.

Fix ONLY `OverseerWebApi.chat_send` (and a small private helper you may add to
the class) — do NOT touch any other method, module, or file.

# Required plan shape

Emit EXACTLY ONE task (do NOT decompose / split into subtasks):
- meta_task_type: data_model
- files_touched: ["overseer/web_api.py"]  (this file ONLY)
- verification_command: "python -m pytest tests/overseer/test_web_api_mode_on_send.py tests/overseer/test_web_api.py -q"
- spec_author: null
- IMPL-only: BOTH oracles are pre-committed preconditions — author/edit NO test; touch no other file.

# Inputs

The current overseer/web_api.py is staged into your inbox/targets — READ it on
your second turn and edit chat_send in place, preserving every other method
(chat_history, chat_resend, mode_get, mode_set, mode_unlock, model_list, the
static helpers) byte-for-byte.

Behaviour the two committed oracles
(tests/overseer/test_web_api_mode_on_send.py + the existing
tests/overseer/test_web_api.py) pin:
- chat_send with NO conversation_id CREATES a conversation. When `body` carries a
  `mode` that is SELF-SELECTABLE, boot the conversation with that mode; otherwise
  boot 'observe'.
- "self-selectable" == a known mode that is default-available and NOT unlock-only
  (Tier-R or default Tier-W). Determine this WITHOUT hardcoding the mode list:
  use overseer.modes — a mode is self-selectable iff it is in
  `list_available_modes()` (the default-available set, no unlocks) which already
  excludes every Tier-S unlock-only mode. (Equivalently: `get_mode(mode)` does
  not raise AND `not requires_unlock(mode)`.) Catch the KeyError that
  `get_mode`/`requires_unlock` raise for an unknown name and fall back to 'observe'.
- 'brief-author' and 'analyze' boot into themselves; 'push' (Tier-S) and an
  unknown name fall back to 'observe'; a send with no `mode` boots 'observe'
  (unchanged).
- Reusing an EXISTING conversation (conversation_id present) IGNORES `body['mode']`
  entirely — do not switch the stored mode here (that is mode_set's job). The user
  turn is still appended and both turns remain recorded.
- The return shape is unchanged: {"conversation_id", "job_id"} with a non-empty
  job_id. No driver/agent/subprocess is spawned (record-only layer).

# Non-Goals

INTEGRATION is out of scope — do not alter service.py, turn_runner.py, the
frontend, or any other method of OverseerWebApi; no driver/agent/subprocess/
network. Stdlib + sibling overseer modules only. Edit no test.

# Edge Cases

- mode key absent / None / empty string -> boot 'observe'.
- unknown mode name (get_mode raises KeyError) -> boot 'observe', never raise.
- Tier-S unlock-only mode ('push','flag-steward','harness-self-fix', etc.) ->
  boot 'observe' (not self-selectable).
- existing conversation: ignore mode, still append the user turn.

# Deliverables

overseer/web_api.py, GREEN under
`python -m pytest tests/overseer/test_web_api_mode_on_send.py tests/overseer/test_web_api.py -q`.
