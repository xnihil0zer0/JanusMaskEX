---
interfaces: "overseer/actions.py: dispatch_action(mode, command, args, *, seams) -> dict; ACTION_ROUTES: dict[mode -> dict[command -> seam_key]]. Imports overseer.mode_gate (ModeViolation) + overseer.modes."
meta_task_type: data_model
---

# Title

overseer/actions.py

# Scope

Build the NEW single-file, whole-file, stdlib-only module overseer/actions.py,
IMPL-only against its pre-committed RED oracle tests/overseer/test_actions.py
(AUTHORITATIVE). `dispatch_action` enforces mode authority FIRST (fail-closed:
an out-of-mode or unknown-mode command raises `overseer.mode_gate.ModeViolation`
and NO seam fires), then routes the command to the EXISTING operator action via
an INJECTED `seams` bundle, so the tested surface has zero side effects.

# Required plan shape

Emit EXACTLY ONE task (do NOT decompose / split into subtasks):
- meta_task_type: data_model
- files_touched: ["overseer/actions.py"]  (this file ONLY)
- verification_command: "python -m pytest tests/overseer/test_actions.py -q"
- spec_author: null
- IMPL-only: the oracle is a pre-committed precondition — author/edit NO test; touch no other file.

# Inputs

The committed oracle tests/overseer/test_actions.py is the contract. Key facts from it:
- `ACTION_ROUTES` is a module-level dict mapping a mode name -> {command -> seam_key}.
  It MUST include at least modes "observe", "brief-author", "dispatch", "daemon-supervisor";
  every mode key MUST exist in `overseer.modes.MODE_REGISTRY`. `ACTION_ROUTES["daemon-supervisor"]`
  MUST contain "pause".
- READ-ONLY modes (observe/analyze/audit) may ONLY route to READ seams — no command under a
  read-only mode may map to a write/mutating seam_key.
- `dispatch_action(mode, command, args, *, seams) -> dict`: (1) verify the mode permits the
  command FIRST — an unknown mode or an out-of-mode command raises ModeViolation BEFORE any seam
  call; (2) resolve the seam via `seams.<seam_key>` (the oracle's RecordingSeams exposes a seam
  per key via attribute access) and call it with `args`, returning its dict result. EXACTLY ONE
  seam fires on a valid command; ZERO seams fire on any rejection.

# Non-Goals

No agent spawn / subprocess / model call / SSE / network. The injected `seams` bundle is the only
side-effect path; the module itself performs no real operator action. Stdlib only. No other files.
Does not author its own oracle.

# Deliverables

overseer/actions.py, GREEN under `python -m pytest tests/overseer/test_actions.py -q`.
