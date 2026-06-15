---
dependencies:
  - "integration_smoke_classifiers"
  - "integration_smoke_config_flag"
interfaces: "_integration_smoke_gate_enabled(state_dir) -> bool; _run_integration_smoke_gate(task, files_touched, state_dir, task_id, staging_path, worktree_root, result, working_dir) -> bool (True == reject); invoked inside _auto_commit_accepted(state_dir, task, task_id) -> bool immediately after the wire-up block; reject arm uses _mark_blocked(outcome='missing_integration_smoke')"
---

# Title

Accept-time gate: wire the classifiers into _auto_commit_accepted (Layer 1)

# Scope

EDIT `harness/orchestrator.py` to add the load-bearing accept-time gate, mirroring the wire-up gate line-for-line. Add `_integration_smoke_gate_enabled(state_dir) -> bool` (reads `load_config()['autowork'].get('integration_smoke_gate', False)`) and `_run_integration_smoke_gate(task, files_touched, state_dir, task_id, staging_path, worktree_root, result, working_dir) -> bool` (returns True to REJECT, mirroring `_run_wire_up_gate`). Call them inside `_auto_commit_accepted` IMMEDIATELY AFTER the existing wire-up block, in the identical shape: `if _integration_smoke_gate_enabled(state_dir): if _run_integration_smoke_gate(...): return False`. The gate reads each touched module's source through the injected seam, classifies it with `is_io_bound`, and for every I/O-bound touched module checks the leaf's committed test set with `has_executing_integration_oracle`. If an I/O-bound module ships no executing integration oracle, REJECT exactly as the orphan_unwired arm does: `_rollback_rejected_commit(staging_path, sha, rel, task_id, reason)` + `git_integration.remove_staging_worktree(...)` + `_mark_blocked(state_dir, task_id, outcome='missing_integration_smoke')` + `write_jsonl_row(state_dir / 'impl_progress.jsonl', {...})` + `return False`. On a proven (or non-I/O-bound) module, proceed unchanged. The gate keys off I/O-boundness, NOT the meta_task_type skip-list (the Hole-A fix). This child re-plans into the single orchestrator-edit leaf with an EDGE-ASSERTING oracle that drives the real `_auto_commit_accepted` over a temp git: a monkeypatch wrapper that records the live accept path actually invoked `_run_integration_smoke_gate`, asserts an I/O-bound hermetic-only task is BLOCKED (`return False`), asserts an I/O-bound task WITH an executing integration oracle MERGES (True), and asserts a pure-logic module MERGES with no oracle required.

# Non-Goals

Do NOT create any new file in this leaf (NEW file + EXISTING-file edit in one leaf trips `auto_commit_failed`); the classifiers come from the substrate child. Do NOT modify `smoke_import` (additive/complementary). Do NOT alter the wire-up gate or any current behaviour/passing test; the edit is additive and inert while the flag is OFF. Do NOT spawn agents, make model/API/network calls, or add un-injected subprocesses. Do NOT flip the flag. Do NOT re-implement the classifiers — import them. Do NOT ship an isolated unit oracle for the call site — only the EDGE-ASSERTING shape is acceptable here.

# Inputs

Consumes from `integration_smoke_classifiers`: `is_io_bound(module_rel, module_src, *, signals=BOUNDARY_SIGNALS) -> IoBoundResult(io_bound, signals, reason)` and `has_executing_integration_oracle(module_rel, test_srcs, *, entrypoints=ENTRYPOINT_NAMES) -> SmokeOracleResult(present, oracle_files, reason, fix_hint)` from `harness/integration_smoke.py`. Consumes from `integration_smoke_config_flag`: the flag `load_config()['autowork'].get('integration_smoke_gate', False)` (default False). Reuses verbatim from `harness/orchestrator.py`: `_auto_commit_accepted(state_dir, task, task_id) -> bool` (insertion point right after the wire-up block), `_run_wire_up_gate`/`_wire_up_gate_enabled` (exact templates), `_rollback_rejected_commit(staging_path, sha, rel, task_id, reason)`, `git_integration.remove_staging_worktree(...)`, `_mark_blocked(state_dir, task_id, outcome=...)`, and `write_jsonl_row(state_dir / 'impl_progress.jsonl', {...})` (the orphan_unwired arm is the model).

# Deliverables

`harness/orchestrator.py` exposes `_integration_smoke_gate_enabled(state_dir) -> bool` and `_run_integration_smoke_gate(task, files_touched, state_dir, task_id, staging_path, worktree_root, result, working_dir) -> bool` (returns True to reject), both invoked from `_auto_commit_accepted` immediately after the wire-up block; rejection emits `_mark_blocked(outcome='missing_integration_smoke')`, an `impl_progress.jsonl` row, rolls back the staged commit, removes the staging worktree, and returns False. Plus `tests/harness/test_integration_smoke_accept_gate.py` — the EDGE-ASSERTING oracle proving the live accept path invokes the gate and blocks an unproven I/O-bound module while merging a proven one and a pure-logic one.
