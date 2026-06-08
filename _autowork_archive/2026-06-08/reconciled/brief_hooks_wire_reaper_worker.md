---
interfaces: "harness/orchestrator_worker.py: _print_json_line(payload: dict) -> None (existing, EDIT in place) + _reap_spent_briefs_safe(payload: dict) -> None (NEW top-level helper). The worker emits every terminal outcome through _print_json_line; on an 'accepted' outcome the spent brief+plan should be archived via tools.brief_reaper.reap_for_task, behind a default-off config flag, fully fail-safe."
meta_task_type: harness_self_fix
---

# Title

harness/orchestrator_worker.py

# Scope

EDIT the EXISTING module `harness/orchestrator_worker.py` (single file, IMPL-only)
to wire archive-on-integrate into the worker's accept chokepoint. Two changes,
BOTH inside this one file:

1. EDIT the existing `_print_json_line(payload)` so that, AFTER it writes and
   flushes the JSON line as it does today, it ALSO calls
   `_reap_spent_briefs_safe(payload)` — but wrapped so that ANY exception from
   that call is swallowed and never prevents the line from being emitted or
   propagates to the caller. The existing write+flush behaviour MUST be
   preserved byte-for-byte and happen FIRST.

2. ADD a NEW top-level function `_reap_spent_briefs_safe(payload)` (see contract
   below).

Touch NO other symbol and NO other file. Do NOT change `main()`, the accept
paths, `_emit_lifecycle_safe`, or any import.

# Required plan shape

Emit EXACTLY ONE task (do NOT decompose):
- meta_task_type: harness_self_fix
- files_touched: ["harness/orchestrator_worker.py"]  (this file ONLY)
- verification_command: "python -m pytest tests/harness/test_worker_reap_wiring.py -q"
- spec_author: null
- IMPL-only: the oracle `tests/harness/test_worker_reap_wiring.py` is a
  PRE-COMMITTED precondition — author/edit NO test; touch no other file.
- The task spec.non_goals MUST contain the literal word "integration".
- test_spec MUST carry >=2 regression_tests reflecting the edge cases below.

# How to submit (PARTIAL EDIT — this file is large)

`harness/orchestrator_worker.py` is a large existing module, so submit a
`__JANUSMASK_PATCHES__` symbol patch keyed on `_print_json_line`. Because the
NEW helper `_reap_spent_briefs_safe` is a brand-new top-level symbol, RIDE IT as
a TRAILING def inside that SAME patch: the patch `code` is the fully
reconstructed `def _print_json_line(...)` IMMEDIATELY FOLLOWED by the complete
`def _reap_spent_briefs_safe(...)` at module scope. One patch entry, two
top-level defs. Do NOT emit a second patch entry for the new symbol.

# Contract for `_reap_spent_briefs_safe(payload)`

A pure side-effecting bridge; returns None. Wrap the WHOLE body in
`try: ... except Exception: return` so it can NEVER raise (it runs on the hot
accept path):

1. If `payload.get('outcome') != 'accepted'`: return (do nothing).
2. Read the flag: lazily `from harness.orchestrator import load_config`, call
   `load_config()` (it has a default config path), and read
   `cfg['autowork']['archive_spent_briefs']` defensively via nested `.get(...)`
   so a missing section / missing key is falsy (default OFF). If not truthy:
   return.
3. `task_id = payload.get('task_id')`; if it is not a non-empty string: return.
4. Compute the repo root as the parent of this file's `harness/` directory:
   `pathlib.Path(__file__).resolve().parents[1]`.
5. Compute a date stamp: `datetime.date.today().isoformat()`.
6. Lazily `from tools.brief_reaper import reap_for_task` and call
   `reap_for_task(repo_root, task_id, stamp=<the stamp>)`. Ignore its return.

All imports used ONLY here (load_config, reap_for_task, datetime, pathlib) must
be imported INSIDE the function body (this file's top-level import block must not
grow), consistent with the worker's existing in-body-import style.

# Inputs

The contract is the committed oracle `tests/harness/test_worker_reap_wiring.py`.
It monkeypatches `harness.orchestrator.load_config` (flag on/off), and
`tools.brief_reaper.reap_for_task` (a recorder / a raiser), then asserts:
`_print_json_line` still prints and calls the bridge; the bridge calls
`reap_for_task` with the task_id + a keyword `stamp` ONLY when outcome=='accepted'
AND the flag is on; and the bridge swallows config/reap exceptions. READ it.

# Non-Goals

INTEGRATION is out of scope — do NOT spawn a real build, real subprocess, real
model, or touch the filesystem from the test's perspective beyond delegating to
`tools.brief_reaper.reap_for_task` (which the oracle stubs). Do NOT edit
`main()`, the synthesis/fuzz/commit paths, `tools/brief_reaper.py`, the config
file, or any other module. Do NOT add new top-level imports. Do NOT change the
JSON that `_print_json_line` prints.

# Edge Cases

- outcome != 'accepted' (e.g. 'rejected', 'timeout', 'no_diff'): bridge is a
  no-op, `reap_for_task` never called (regression test).
- flag absent / off: no-op (regression test).
- `reap_for_task` raises: swallowed; `_reap_spent_briefs_safe` does not raise.
- `load_config` raises: swallowed; no reap.
- `_print_json_line` with a throwing bridge: the JSON line is STILL printed and
  no exception escapes.
- `payload` missing 'task_id' on an accepted outcome: no-op.

# Deliverables

`harness/orchestrator_worker.py`, GREEN under
`python -m pytest tests/harness/test_worker_reap_wiring.py -q`, with zero change
to any other test's outcome.
