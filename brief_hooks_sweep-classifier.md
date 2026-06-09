---
dependencies:
  - "root-reconciliation"
interfaces: "sweep_modules(repo_root, *, roots) -> SweepReport  # builds import graph ONCE via discover.module_import_graph; source set = discover_modules non-test modules MINUS _archive/** _autowork_archive/** samples/** scripts/** tests/** venv/**; classifies each into WIRED | CONFIG_WIRED | ORPHAN_CLUSTER | ORPHAN over BFS-reachable set from `roots`; SweepReport carries per-class sets and serializes deterministic sorted JSON + WIRE_UP_SWEEP_REPORT.md. `roots` is the list returned by discover_live_roots(repo_root). Lives in harness/wire_up.py."
---

# Title

Wire-Up Sweep — tree-wide classifier + WIRE_UP_SWEEP_REPORT.md producer

# Scope

ADD `sweep_modules(repo_root, *, roots) -> SweepReport` to harness/wire_up.py (born-wired by riding the existing orchestrator import edge). Build the import graph ONCE via discover.module_import_graph (NOT per-module check_wired — that is O(n^2) and timed out at authoring). Apply the explicit source-set filter: discover_modules' non-test modules MINUS _archive/**, _autowork_archive/**, samples/**, scripts/**, tests/**, venv/**. From the BFS-reachable set over the supplied reconciled roots, classify every source module into exactly one of WIRED (>=1 reachable live importer, own-oracle excluded), CONFIG_WIRED (no static importer but referenced by stem in config/**), ORPHAN_CLUSTER (inbound importers exist but none reachable from a root — a connected component), or ORPHAN (zero inbound importers and no config reference). Serialize a deterministic sorted JSON ledger AND a human-readable WIRE_UP_SWEEP_REPORT.md whose header states the source-set filter explicitly. Ships an EDGE-ASSERTING oracle tests/harness/test_sweep_classifier.py that drives a fixture import graph + fixture config dir and asserts each of the four classes lands on the right module, archives/samples/scripts excluded, own-oracle excluded, and output is deterministic (sorted). verification_command: `python -m pytest tests/harness/test_sweep_classifier.py -q`.

# Non-Goals

Does NOT reimplement check_wired or module_import_graph — it WRAPS them, building the graph once and reusing it. Does NOT query the MCP or attach advisory disagreements (that is mcp_crosscheck). Does NOT remediate any orphan or author Wave-2 leaves. Does NOT add the regression-guard test (that is regression_guard). No agent spawns, model/API/network calls, or un-injected subprocesses; roots arrive as an injected parameter and config reads are plain filesystem.

# Inputs

Consumes `discover_live_roots(repo_root) -> list[str]` from root_reconciliation as the source of the reconciled `roots` it is seeded with (the reconciled roots = shipped LIVE_ROOTS unioned with config/** entrypoints + __main__ modules + service/web entrypoints). Fixed seams: harness/rebuild/discover.py `discover_modules(source_root) -> (modules, tests, seeds)` and `module_import_graph(source_root, modules) -> {module_rel -> set(intra-project imports)}`; harness/wire_up.py `_grep_config(repo_root, stem)` for the CONFIG_WIRED stem check and the existing check_wired/WireResult/LIVE_ROOTS symbols (unchanged).

# Deliverables

harness/wire_up.py gains `sweep_modules(repo_root, *, roots) -> SweepReport` — a pure function that builds the import graph once, applies the source-set filter (MINUS _archive/**, _autowork_archive/**, samples/**, scripts/**, tests/**, venv/**), and partitions every source module into WIRED / CONFIG_WIRED / ORPHAN_CLUSTER / ORPHAN. SweepReport exposes the per-class module sets and serializes a deterministic sorted JSON ledger plus WIRE_UP_SWEEP_REPORT.md (header states the filter). Committed RED oracle tests/harness/test_sweep_classifier.py asserting all four classes, exclusions, and deterministic sorted output.
