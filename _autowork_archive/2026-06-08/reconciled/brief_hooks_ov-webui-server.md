---
interfaces: "tools/webui_server.py: build_tailer(state_dir, logs_dir, buffer_size) -> StateTailer — ADD logs_dir/'overseer_chat.jsonl' to its fixed_paths."
meta_task_type: harness_plumbing
---

# Title

EDIT tools/webui_server.py

# Scope

THIN ADDITIVE edit to the existing module tools/webui_server.py against its
pre-committed RED oracle tests/overseer/test_webui_server_tailer.py
(AUTHORITATIVE). Add `logs_dir / "overseer_chat.jsonl"` to the `fixed_paths`
list built inside `build_tailer(state_dir, logs_dir, buffer_size)` so the
overseer driver's streamed deltas relay over the existing /events SSE channel.
PRESERVE every existing watched path.

# Required plan shape

Emit EXACTLY ONE task (do NOT decompose / split into subtasks):
- meta_task_type: harness_plumbing
- files_touched: ["tools/webui_server.py"]  (this file ONLY)
- verification_command: "python -m pytest tests/overseer/test_webui_server_tailer.py -q"
- spec_author: null
- IMPL-only: the oracle is a pre-committed precondition — author/edit NO test; touch no other file.

# Inputs

The committed oracle tests/overseer/test_webui_server_tailer.py is the contract. The existing
`build_tailer` (tools/webui_server.py) currently builds:
`fixed_paths = [state_dir/'impl_progress.jsonl', state_dir/'track_record_events.jsonl',
logs_dir/'claude_stream.jsonl', logs_dir/'gemini_stream.jsonl', logs_dir/'antigravity_stream.jsonl']`.
The ONLY change: append `logs_dir / "overseer_chat.jsonl"` to that list (keeping all existing
entries) so `StateTailer(...).paths` includes it. The oracle asserts overseer_chat.jsonl is watched
AND that claude_stream.jsonl + impl_progress.jsonl remain watched.

# Non-Goals

No new SSE socket / network / agent spawn. Do NOT rewrite the StateTailer class or any other
function. Do NOT modify existing fixed_paths entries. ONE-line additive change to build_tailer only.
Touch no other file. Does not author its own oracle.

# Deliverables

tools/webui_server.py, GREEN under `python -m pytest tests/overseer/test_webui_server_tailer.py -q`.
