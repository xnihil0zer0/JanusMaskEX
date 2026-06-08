---
interfaces: "overseer/transcript.py: Turn(index,role,mode,content) + Message(role,content) dataclasses; to_jsonl(turn)->str; from_jsonl(line)->Turn; redact(text)->str; reconstruct_prefix(turns,up_to_index)->list[Message]."
meta_task_type: data_model
---

# Title

overseer/transcript.py

# Scope

Build the NEW single-file, whole-file, stdlib-only Python module overseer/transcript.py, IMPL-only against its pre-committed RED oracle tests/overseer/test_transcript.py. The committed oracle is AUTHORITATIVE — reproduce the exact public surface it imports (names, signatures, dataclass fields). Append-only conversation model. Turn carries index/role/mode/content; Message is role/content. Lossless one-line JSONL round-trip (to_jsonl/from_jsonl). redact() strips operator-secret-shaped tokens (e.g. >=40-hex) to [REDACTED], leaving ordinary text untouched. reconstruct_prefix(turns,up_to_index) returns Messages for turns with index<=up_to_index, VERBATIM/byte-identical, in order (the cache-friendly prefix).

# Required plan shape

Emit EXACTLY ONE task (do NOT decompose, do NOT split into subtasks):
- meta_task_type: data_model
- files_touched: ["overseer/transcript.py"]  (this file ONLY)
- verification_command: "python -m pytest tests/overseer/test_transcript.py -q"
- spec_author: null
- Build IMPL-only: the oracle is a pre-committed precondition — do NOT author or edit any test. Do NOT touch any other file. A brand-new top-level symbol may ride as a trailing node via an implementation_notes R-anchor hint.

# Non-Goals

No agent spawn, subprocess, model API call, SSE write, or network. Stdlib only (it MAY import harness internals or sibling overseer modules by path, but edits none). Does not author its own oracle. Touches no file other than overseer/transcript.py.

# Inputs

The committed oracle tests/overseer/test_transcript.py is authoritative. Per-leaf contract is the committed oracle.

# Deliverables

overseer/transcript.py, GREEN under `python -m pytest tests/overseer/test_transcript.py -q`.
