---
interfaces: "discover_live_roots(repo_root) -> list[str]  # reconciled roots = shipped LIVE_ROOTS UNIONED with config/** hook/entrypoint-table modules + modules with an `if __name__ == '__main__'` block + service/web entrypoints. Pure, stdlib-only, reads config/** via plain filesystem. Lives in harness/wire_up.py alongside the unchanged check_wired/WireResult/LIVE_ROOTS/_grep_config seams."
---

# Title

Wire-Up Sweep — reconcile the live-root set from ground truth

# Scope

EDIT harness/wire_up.py (protected-path write, meta_task_type=harness_self_fix + operator decision file). Add a pure stdlib function `discover_live_roots(repo_root) -> list[str]` that returns the SHIPPED LIVE_ROOTS UNIONED with entrypoints discovered from ground truth: every module named in a config/** hook/entrypoint table (plain filesystem reads + the existing `_grep_config` stem supplement), every module carrying an `if __name__ == '__main__'` block, and the known service/web entrypoints. Cure the stale LIVE_ROOTS constant so the per-event hook modules under harness/hooks/claude/**, harness/hooks/gemini/**, harness/hook_pre_tool.py, and harness/mcp_server.py are seeded as roots. The function is a pure addition to an already-WIRED module (harness/orchestrator.py imports check_wired), so it rides an existing live import edge and is born reachable. Ships an EDGE-ASSERTING oracle tests/harness/test_live_root_reconciliation.py that drives the REAL import graph and asserts: (a) the config hook entrypoints harness/hooks/claude/pre_tool.py, harness/mcp_server.py, harness/hook_pre_tool.py appear in the reconciled roots; (b) harness/hooks/_paths.py (15 importers, the proven false positive) classifies WIRED once seeded from the reconciled roots; (c) a synthetic zero-importer module is still ORPHAN. verification_command: `python -m pytest tests/harness/test_live_root_reconciliation.py -q`.

# Non-Goals

Does NOT reimplement check_wired, WireResult, _grep_config, or discover.module_import_graph — it only adds discover_live_roots and seeds from it. Does NOT build the tree-wide sweep/classifier or the report (that is sweep_classifier). Does NOT touch the overseer accept-time wired gate. No agent spawns, model/API/network calls, or un-injected subprocesses; reads config/** via plain filesystem only. Does NOT hand-edit production outside the planner -> stage -> worker pipeline.

# Inputs

Fixed seams (do NOT rebuild): harness/wire_up.py exposing `check_wired(repo_root, new_module_rel, *, roots=LIVE_ROOTS, exclude=()) -> WireResult(wired: bool, importers: list[str], reason: str, fix_hint: str)`, the `LIVE_ROOTS` seed constant, and `_grep_config(repo_root, stem)`. harness/rebuild/discover.py exposing `discover_modules(source_root) -> (modules, tests, seeds)` and `module_import_graph(source_root, modules) -> {module_rel -> set(intra-project imports)}` (AST-walks the full tree, catches function-local imports). config/** hook/entrypoint tables on disk. harness/orchestrator.py already imports check_wired (the existing live edge this addition rides).

# Deliverables

harness/wire_up.py gains a pure stdlib function with the frozen signature `discover_live_roots(repo_root) -> list[str]` returning the reconciled root set (shipped LIVE_ROOTS unioned with config/** entrypoints, __main__-bearing modules, and service/web entrypoints), and LIVE_ROOTS is corrected so the real hook entrypoints are seeded. Committed RED oracle tests/harness/test_live_root_reconciliation.py asserting the config hook entrypoints are in the reconciled roots, harness/hooks/_paths.py classifies WIRED under them, and a synthetic zero-importer is still ORPHAN.
