---
dependencies:
  - "symbol_ledger_module"
  - "staging_resolve_interfaces"
  - "failure_propagation_status"
  - "planner_depth_and_recursion"
interfaces: "consumes `resolve_interfaces(interfaces_spec: str, state_dir: Path) -> str`, `record_symbols(state_dir: Path) -> dict[str, str]`, the extended `compute_epic_status`, and the `check_brief_depth(slug, repo_root, max_depth)` gate in planner cli.py main"
---

# Title

End-to-end Level-2 acceptance test (hermetic)

# Scope

Deliver the end-to-end acceptance test required by the epic, proving the assembled Level-2 behavior across all four siblings: epic -> child briefs -> leaf tasks; a nested epic child is re-decomposed (not treated as a leaf); a brief whose lineage exceeds the depth budget is refused with non-zero exit; a descendant failure surfaces the epic as `blocked`; and interface resolution rewrites spec.interfaces from the lazy-derived ledger. This child is TEST-ONLY — it adds NO production code, only a new hermetic test that exercises the already-built symbol_ledger_module, staging_resolve_interfaces, failure_propagation_status, and planner_depth_and_recursion. IMPLEMENTATION CONSTRAINTS (emit as implementation_notes): land entirely OUTSIDE the _NEVER_AUTO_APPROVE deny-list; create the e2e test as a NEW FILE (oracle-first); the test must be FULLY HERMETIC — use fixtures/temp dirs, never glob tests/planner/, never pip-install or touch the network, and never run a rebuild dry-run; do NOT modify any production module to make the test pass (failures mean a sibling is incomplete, not a reason to edit deny-list or production code here).

# Non-Goals

Do NOT add or modify any production code — this child is the acceptance test only. Do NOT edit any deny-list file. Do NOT re-implement the ledger, staging seam, failure propagation, or depth/recursion logic — import and exercise what the sibling children produced. Do NOT include non-hermetic steps (no network, no pip, no rebuild dry-runs, no tests/planner/ glob).

# Inputs

Consumes `resolve_interfaces(interfaces_spec: str, state_dir: Path) -> str` and `record_symbols(state_dir: Path) -> dict[str, str]` from harness/symbol_ledger.py (symbol_ledger_module). The flag-gated resolve_interfaces call at the staging/materialization seam (staging_resolve_interfaces). The extended `compute_epic_status` in harness/brief_status.py that returns 'blocked' for a transitive failed descendant when failure_propagation is enabled (failure_propagation_status). The `check_brief_depth(slug, repo_root, max_depth)` gate in harness/planner/cli.py main and the epic-recursion routing bounded by config['hierarchical_planning']['max_planner_depth'] (planner_depth_and_recursion). harness/config.yaml hierarchical_planning keys (symbol_ledger, failure_propagation, max_planner_depth).

# Deliverables

A NEW HERMETIC end-to-end acceptance test file asserting all five outcomes: (a) epic decomposes into child briefs that yield leaf tasks; (b) a nested epic child (epic: true) is re-decomposed rather than treated as a leaf; (c) a brief beyond max_planner_depth is refused with non-zero exit; (d) a descendant failure surfaces the epic as blocked via compute_epic_status with failure_propagation enabled; (e) resolve_interfaces rewrites spec.interfaces from a lazy-derived ledger at the staging seam. IMPLEMENTATION CONSTRAINTS to emit as implementation_notes: new test = new file (oracle-first); fully hermetic (fixtures/temp dirs, no network/pip, no rebuild dry-runs, no tests/planner/ glob); stay outside the deny-list; verification_command runs only this e2e file plus any hermetic fixtures it needs.
