---
working_dir: "/home/xnihil0zer0/JanusMaskJR"
required_task_ids:
  - redispatch-pertask-identity-oracle
  - redispatch-pertask-identity-impl
priority: high
---

# Title
Make brief-edit re-plans surgical: dedup re-dispatch on per-task spec identity, not whole-brief sha

# Scope
A RED-PAIR fix to two EXISTING harness files; READ both before editing.

Today `harness/brief_status.py` `compute_brief_status` dedups already-accepted tasks on the WHOLE-BRIEF sha (`source_brief_sha256`). So editing a brief (which re-stamps the brief sha) requeues EVERY already-accepted task of that brief — even a task whose own spec is byte-identical. Re-running a converged task against a tree that already has its change makes both agents emit no patch block, yielding `synthesis_or_ast_failed` -> blocked -> cascaded `dependency_failed` (the c7-gate-bridge-impl incident). The fix keys the dedup on PER-TASK spec identity: stamp a per-task spec fingerprint on the accept row, and skip re-dispatch when the live task spec still matches that fingerprint.

TASK 1 — `redispatch-pertask-identity-oracle` (`test_authoring`, priority `high`): author one NEW hermetic RED oracle at `tests/harness/test_redispatch_pertask_identity.py` that pins the post-fix behavior of the REAL `harness.brief_status.compute_brief_status`. mutation_target is `harness.brief_status`. The oracle builds its own `tmp_path` repo_root + state_dir and never touches the live `state/`. It imports `compute_brief_status` AND the new helper `_task_spec_sha256` from `harness.brief_status` via importlib (NOT exec/eval/__import__) and uses `_task_spec_sha256` to compute the fingerprints it writes into accept rows, so test and impl agree on the canonical fingerprint by construction. It covers four cases under a live plan stamped with a fresh on-disk brief sha S2 and accept rows stamped under an older sha S1: (a) an already-accepted task whose accept row carries a `task_spec_sha256` equal to its current plan-task fingerprint lands in `accepted` and is NOT in `remaining`/`unstaged_task_ids`; (b) a genuinely-unaccepted task IS in `remaining`/`unstaged_task_ids`; (c) an already-accepted task whose stored `task_spec_sha256` does NOT match its current spec (its spec changed) IS re-dispatched (in `remaining`/`unstaged_task_ids`, not `accepted`); (d) a legacy accept row with NO `task_spec_sha256` field is conservatively treated as `remaining` (never falsely skipped).

TASK 2 — `redispatch-pertask-identity-impl` (`harness_self_fix`, priority `high`, depends on TASK 1): edit `harness/brief_status.py` AND `harness/orchestrator.py` and deliver as `__JANUSMASK_PATCHES__` with one entry per modified symbol. Both files live under `harness/**` (sensitive). An operator decision file `state/control/decisions/redispatch-pertask-identity-impl.json` already approves the orchestrator.py edit.

# Non-Goals
Integration is out of scope for both tasks (the literal word `integration` MUST appear here to excuse the integration-test requirement — neither task needs an integration test; `compute_brief_status` and the accept-row writer are already on the live path, so no new wiring step exists or is wanted). Do NOT touch `harness/autowork_daemon.py`, the daemon dispatch loop, the consumers of `unstaged_task_ids`, the retry budget, or the `synthesis_or_ast_failed` -> `no_diff` degrade path. Do NOT change the ledger schema beyond ADDING the one optional `task_spec_sha256` key to the accept row; legacy rows lacking it MUST keep working via the conservative fallback. Do NOT alter the whole-brief `source_brief_sha256` plan-staleness drop gate in `brief_status.py` — that behavior is correct and unrelated. Do NOT author any test beyond the one oracle.

# Inputs
READ `harness/brief_status.py` and `harness/orchestrator.py` first — they are the source of truth. In `compute_brief_status`: the accept-row harvest builds `accepted_map[tid]` from `accepted`/`auto_commit` ledger rows but currently drops the row's `task_spec_sha256`; the live plan is parsed into per-task dicts and `stamped = plan_data.get('source_brief_sha256')`; the dedup loop requeues an accepted task whenever its stored brief sha differs from `stamped`, with no per-task spec check. In `orchestrator.py` `_auto_commit_accepted`, a nested helper resolves the matching plan-task dict and the brief sha, and the subsequent `write_jsonl_row({... 'event': 'auto_commit' ...})` call (near line 3319) writes the accept row.

# Deliverables
A RED oracle (TASK 1) and a `harness_self_fix` (TASK 2). The impl agent writes the actual `__JANUSMASK_PATCHES__` (one entry per modified symbol). The implementation must:

1. Add a top-level helper `_task_spec_sha256(task)` to `harness/brief_status.py`, R-anchored on the existing top-level `compute_brief_status`. It returns a stable sha256 hex digest over a canonical dict of the task's identity fields (`task_id`, `verification_command`, `files_touched`, `partial_edit`, `spec`), each read via `task.get(...)` with `files_touched` normalized to a list of str, hashed via `hashlib.sha256(json.dumps(canonical, sort_keys=True, default=str).encode('utf-8')).hexdigest()`. On any error it returns `''` (treated as "cannot prove convergence"). `hashlib` and `json` are already imported at module level.

2. Edit `compute_brief_status` (one symbol patch): also carry the accept row's `task_spec_sha256` into `accepted_map[tid]`; build a `tid -> live plan-task dict` map alongside the existing task-id list; and in the dedup loop, when an accepted task's stored brief sha differs from `stamped`, only skip re-dispatch when its stored `task_spec_sha256` is a non-empty str AND equals `_task_spec_sha256` of the live plan-task. Otherwise (changed spec, or no stored fingerprint) requeue conservatively. When the brief sha is unchanged, keep today's accept behavior.

3. Edit the accept-row write in `orchestrator.py` `_auto_commit_accepted` (one symbol patch on the enclosing top-level method): have the existing nested resolver also surface the located plan-task dict, compute its fingerprint via a lazy `from harness.brief_status import _task_spec_sha256` (inside the method, to avoid an import cycle), and add `'task_spec_sha256'` to the `auto_commit` accept-row dict. The addition must be fail-safe — any error yields `''` and the accept-row write must never raise.

Both tasks share the verification_command `python -m pytest tests/harness/test_redispatch_pertask_identity.py -q`. The impl task depends on the oracle. Both priorities are `high`.

# Required plan shape
Emit EXACTLY TWO tasks: tasks[0] is the oracle, tasks[1] is the impl. Both `task_id`s MUST appear (the frontmatter `required_task_ids` pins them).

- Task `redispatch-pertask-identity-oracle` (tasks[0]):
  - meta_task_type: `test_authoring`; priority `high`.
  - mutation_target: `harness.brief_status` (bare dotted module-under-test).
  - files_touched: `["tests/harness/test_redispatch_pertask_identity.py"]`.
  - verification_command: `python -m pytest tests/harness/test_redispatch_pertask_identity.py -q`.
  - The oracle imports via importlib only (NOT exec/eval/__import__) and never touches the live `state/`.
  - This task's `non_goals` MUST contain the literal word `integration` (no integration test is wanted for the oracle either).

- Task `redispatch-pertask-identity-impl` (tasks[1]):
  - meta_task_type: `harness_self_fix`; priority `high`; dependencies: `["redispatch-pertask-identity-oracle"]`.
  - files_touched: `["harness/brief_status.py", "harness/orchestrator.py"]` (both sensitive; an operator decision file already approves `orchestrator.py`).
  - Emit a `__JANUSMASK_PATCHES__` SYMBOL patch with one entry per modified symbol (do NOT emit `__JANUSMASK_MANIFEST__`); R-anchor the new top-level `_task_spec_sha256` helper on the existing `compute_brief_status`.
  - OMIT `mutation_target`.
  - verification_command: `python -m pytest tests/harness/test_redispatch_pertask_identity.py -q` (a bare `python -m pytest …`, NO `cd ` re-root).
  - **This task's `non_goals` MUST contain the literal word `integration`.** This is load-bearing: the plan validator requires an `integration_test` for any non-`test_*` task carrying a `spec`/`test_spec` (a `harness_self_fix` task triggers it) UNLESS the literal word `integration` appears in **this task's own** `spec.non_goals`. Neither file needs an integration test — `compute_brief_status` and the accept-row writer are already on the live path, so no new wiring step exists. State the integration excuse directly in `tasks[1].non_goals` (e.g. "integration is out of scope: both edited symbols are already on the live dispatch path; no new wiring").
