---
dependencies:
  - "integration_smoke_classifiers"
  - "integration_smoke_config_flag"
interfaces: "plan_validator emits violation code 'missing_integration_smoke' when is_io_bound(target) and not has_executing_integration_oracle(declared tests); gated by load_config()['autowork'].get('integration_smoke_gate', False)"
---

# Title

Plan-validation requirement: missing_integration_smoke (Layer 2, pre-spawn)

# Scope

EDIT `harness/planner/plan_validator.py` to add a `missing_integration_smoke` violation beside the existing `missing_wiring_oracle` check, mirroring it. A leaf that creates or edits an I/O-bound module (classified by `is_io_bound` over the leaf's target source) but whose declared test set contains no executing integration oracle (per `has_executing_integration_oracle`) is REJECTED pre-spawn, before any worker is dispatched, with a `missing_integration_smoke` violation. A leaf that does declare such an oracle passes. This is belt-and-suspenders ahead of the Layer-1 accept gate. This child re-plans into the single plan_validator-edit leaf plus an oracle that asserts the violation fires on the LIVE validator path: a new-module / io_adapter / hooks_integration leaf with only hermetic (import-only / fake-build_deps) declared tests is rejected, while the same leaf with a declared executing integration oracle passes.

# Non-Goals

Do NOT create any new file in this leaf — import the classifiers from the substrate child. Do NOT consult the meta_task_type skip-list to decide applicability (key off I/O-boundness, the Hole-A fix). Do NOT spawn agents, processes, or make network/model calls — pure AST + injected reads. Do NOT alter the existing `missing_wiring_oracle` check or any current validator behaviour; add additively. Do NOT touch orchestrator, config, or the classifiers' source. Do NOT add an end-to-end integration test for this leaf: this is a pure-AST plan_validator edit with no I/O boundary, so an executing integration test is out of scope and not applicable — the leaf is verified solely by its hermetic `tests/planner/test_missing_integration_smoke.py` oracle exercising the live validator path. (Integration-test requirement excused on this purely in-process check.)

# Inputs

Consumes from `integration_smoke_classifiers`: `is_io_bound(module_rel, module_src, *, signals=BOUNDARY_SIGNALS) -> IoBoundResult(io_bound, signals, reason)` and `has_executing_integration_oracle(module_rel, test_srcs, *, entrypoints=ENTRYPOINT_NAMES) -> SmokeOracleResult(present, oracle_files, reason, fix_hint)` from `harness/integration_smoke.py`, plus the task-declared `spec['integration_entrypoints']` extension to ENTRYPOINT_NAMES. Consumes from `integration_smoke_config_flag`: the flag `load_config()['autowork'].get('integration_smoke_gate', False)` (default False) gating the check. Studies and mirrors `harness/planner/plan_validator.py::missing_wiring_oracle` (the line-for-line model).

# Deliverables

`harness/planner/plan_validator.py` emits a `missing_integration_smoke` violation (beside `missing_wiring_oracle`) that rejects, pre-spawn, any leaf creating/editing an I/O-bound module without a declared executing integration oracle, and passes leaves that declare one. Plus `tests/planner/test_missing_integration_smoke.py` asserting the violation fires on the live validator path for a hermetic-only I/O leaf and does not fire when an executing oracle is declared.
