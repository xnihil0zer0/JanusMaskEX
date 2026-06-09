---
interfaces: "Consumes frozen: `check_wired(repo_root, module_rel, *, roots, exclude) -> WireResult`; `discover_live_roots(repo_root) -> list[str]`; `sweep_modules(repo_root, *, roots) -> SweepReport`; `SweepReport.wired/.config_wired/.orphan_cluster/.orphan`. WIRE oracle contract: `check_wired(repo_root, m, roots=discover_live_roots(repo_root)).wired is True`. `KNOWN_ORPHAN_ALLOWLIST` keys removed by this category: harness/hooks/rpc/clarification.py, harness/hooks/rpc/error_report.py, harness/hooks/rpc/submit_code.py, harness/hooks/rpc/submit_plan_draft.py, harness/hooks/rpc/submit_reconciliation.py."
---

# Title

Wave-2 Remediation — hook-rpc-wiring (harness/hooks/rpc/{clarification,error_report,submit_code,submit_plan_draft,submit_reconciliation}.py)

# Scope

Discharge the 5 hook RPC handler orphans — harness/hooks/rpc/clarification.py, error_report.py, submit_code.py, submit_plan_draft.py, submit_reconciliation.py. These are dispatched by NAME from the hook router/inbox, not via a static import edge. Triage the live tree: locate the router/inbox dispatch table and determine whether the intended wiring was a static dispatch-table import that was never authored (WIRE) or a genuinely dynamic config/name-keyed surface (RECLASSIFY). If WIRE: add the missing dispatch-table import/registration edge from the router (a module already reachable from a live root) so the handlers actually fire, proven by a behavior assertion that drives a dispatched RPC through the live path — not an inert import. If a single dispatch edge wires all five transitively, one leaf owns that edge and its siblings confirm/RECLASSIFY. If RECLASSIFY: ensure each handler's config/dispatch-table reference exists so it classifies CONFIG_WIRED, or rewrite its allowlist justification to the final dynamic-wired reason. Decompose into per-handler leaves (or one dispatch-edge leaf + confirmations) after deciding the connecting edge. Owner gate stays paused.

# Non-Goals

Do NOT reimplement the hook router/inbox, check_wired, sweep_modules, discover_live_roots, or the guard. No inert `import m` that satisfies reachability while the handler stays dead — a WIRE leaf must make the handler actually fire (behavior assertion). No REMOVE here unless a handler is positively proven dead (no static OR dynamic/name-keyed dispatch, no config reference) — ambiguity RECLASSIFIES, never removes. No new agent/model/network/subprocess in deterministic parts. No silent allowlist growth; no 'pending Wave-2' justifications. Do not touch overseer, rebuild, narrow-fuzz, misc-harness, or tools modules or their allowlist keys. Decomposition only — author no oracle, dispatch no build at this level.

# Inputs

ALREADY BUILT (verified at HEAD 6744b1a) — consume, do not rebuild: harness/wire_up.py exposing `check_wired(repo_root, module_rel, *, roots, exclude) -> WireResult`, `discover_live_roots(repo_root) -> list[str]`, `sweep_modules(repo_root, *, roots) -> SweepReport`, `SweepReport` (`.wired/.config_wired/.orphan_cluster/.orphan`). tests/harness/test_no_source_orphans.py exposing `KNOWN_ORPHAN_ALLOWLIST` baselining the 36, including keys harness/hooks/rpc/clarification.py, error_report.py, submit_code.py, submit_plan_draft.py, submit_reconciliation.py. Live modules to triage: the five harness/hooks/rpc/*.py handlers and the hook router/inbox dispatch site. harness/** writes are protected-path ⇒ meta_task_type=harness_self_fix + operator decision file, routed through planner→stage→worker.

# Deliverables

A remediation sub-tree resolving the five hook RPC handlers to WIRE or RECLASSIFY. Each leaf names a pre-committed RED edge-asserting oracle as its verification_command. A WIRE leaf's oracle asserts `check_wired(repo_root, m, roots=discover_live_roots(repo_root)).wired is True` with the new router importer named, PLUS a behavior assertion that a dispatched RPC reaches and executes the handler via the live path. A RECLASSIFY leaf's oracle asserts the handler classifies CONFIG_WIRED (or the guard passes with a rewritten justification). Each leaf edits ONE production file (the dispatch-table importer/config edit) PLUS deletes/rewrites the module's KNOWN_ORPHAN_ALLOWLIST key atomically. End state: the five rpc handlers are no longer in `.orphan ∪ .orphan_cluster` (or are CONFIG_WIRED/justified), allowlist keys removed, guard green.
