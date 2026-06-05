---
dependencies:
  - "symbol_ledger_module"
interfaces: "consumes `resolve_interfaces(interfaces_spec: str, state_dir: Path) -> str`"
---

# Title

Call resolve_interfaces at the staging/materialization seam (flag-gated)

# Scope

Wire the ledger into execution (item 2 of the epic). At the staging/materialization seam where the plan/task dict is materialized for execution — NOT prepare_task_prompt (which never reads spec.interfaces) and NOT inside any deny-list file (orchestrator, etc.) — call `resolve_interfaces(interfaces_spec, state_dir)` on the task's spec.interfaces prose so the resolved signatures flow through the normal specification. Gate the call on config['hierarchical_planning']['symbol_ledger']; when off, leave the spec untouched. IMPLEMENTATION CONSTRAINTS (emit as implementation_notes): land entirely OUTSIDE the _NEVER_AUTO_APPROVE deny-list (harness/agent_jail.py, harness/dbus_proxy.py, harness/paths.py, harness/git_integration.py, harness/orchestrator.py, harness/interceptors.py, harness/selfheal.py, harness/autowork_daemon.py, services/) — pick the staging-seam module that is NOT on that list; any BRAND-NEW top-level helper added to an existing module must ride as a TRAILING extra node inside an existing symbol's patch block (same patch `code` string, 1-part qualname), NOT its own standalone patch entry; do NOT modify existing class methods via partial edit — add a NEW top-level helper and call it from the seam; keep the verification_command to this child's own oracle plus HERMETIC regression files only (never glob tests/planner/, never network/pip).

# Non-Goals

Do NOT touch prepare_task_prompt. Do NOT edit any _NEVER_AUTO_APPROVE deny-list file (especially harness/orchestrator.py). Do NOT re-implement resolve_interfaces — import it from harness/symbol_ledger. Do NOT add a new config flag (gate on the existing symbol_ledger key). Do NOT change the ledger's lazy-derivation logic.

# Inputs

Consumes `resolve_interfaces(interfaces_spec: str, state_dir: Path) -> str` from harness/symbol_ledger.py (produced by symbol_ledger_module). harness/config.yaml — hierarchical_planning.symbol_ledger flag. The staging/materialization seam where the task dict is built for execution (outside the deny-list; not prepare_task_prompt).

# Deliverables

The staging/materialization seam now calls `resolve_interfaces(interfaces_spec: str, state_dir: Path) -> str` on spec.interfaces, flag-gated on config['hierarchical_planning']['symbol_ledger'], so resolved signatures flow into the normal specification. Plus a NEW HERMETIC oracle test proving: flag on + a ledger hit rewrites spec.interfaces; flag off leaves it unchanged; a miss leaves it unchanged. IMPLEMENTATION CONSTRAINTS to emit as implementation_notes: any new top-level helper rides as a trailing extra node in an existing symbol's patch block (1-part qualname); no partial edits of class methods; stay outside the deny-list; verification_command = this child's own oracle plus hermetic regression files only.
