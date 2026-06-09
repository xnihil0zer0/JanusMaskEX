---
dependencies:
  - "sweep-classifier"
interfaces: "MCP cross-check takes the MCP query as an INJECTED callable and operates over the SweepReport produced by sweep_modules(repo_root, *, roots) -> SweepReport; for each ORPHAN/ORPHAN_CLUSTER candidate it queries inbound CALLS/IMPORTS/USAGE and appends a DISAGREEMENT note to WIRE_UP_SWEEP_REPORT.md. ADVISORY ONLY — never flips a verdict, never gates. Stubbed in tests; no live MCP call."
---

# Title

Wire-Up Sweep — injected, advisory MCP cross-check enrichment

# Scope

ADD a cross-checker (in harness/wire_up.py) that takes the MCP query as an INJECTED callable and, for each static ORPHAN/ORPHAN_CLUSTER candidate in a SweepReport, queries the MCP graph for inbound CALLS/IMPORTS/USAGE edges and appends a DISAGREEMENT note to the report when the MCP shows inbound edges (e.g. 'static says orphan, MCP shows N inbound usages -> likely dynamic wiring, do not auto-remove'). The MCP is STRICTLY advisory: it RAISES disagreements for human triage, NEVER flips a verdict automatically and NEVER gates. The injected callable seam is the ONE external-service touch in the epic and exists so oracles drive it hermetically. Ships an oracle tests/harness/test_mcp_crosscheck_advisory.py that feeds a STUB MCP client (no live MCP call) and asserts: a disagreement is RAISED into the report when the stub reports inbound edges, AND the underlying classification verdict is UNCHANGED (advisory, never gates). verification_command: `python -m pytest tests/harness/test_mcp_crosscheck_advisory.py -q`.

# Non-Goals

The MCP cross-check NEVER changes a verdict, NEVER auto-removes a module, and NEVER gates a build — output is report decoration only. No live MCP call in any test or oracle; the MCP query is an injected callable stubbed in tests. Does NOT reimplement check_wired or sweep_modules. Does NOT author the regression guard or any Wave-2 remediation. No agent spawns or un-injected subprocesses.

# Inputs

Consumes `sweep_modules(repo_root, *, roots) -> SweepReport` from sweep_classifier — specifically the SweepReport's ORPHAN and ORPHAN_CLUSTER candidate sets to cross-check, and the WIRE_UP_SWEEP_REPORT.md it decorates. Consumes an injected MCP query callable matching the codebase-memory-mcp surface (query_graph / search_graph / trace_call_path exposing CALLS / IMPORTS / USAGE / DEFINES / TESTS edges); in tests this is a stub. The MCP is proven unreliable both ways (misses agy_pool's function-local wiring; reports live state.py as zero-import), hence advisory-only.

# Deliverables

harness/wire_up.py gains an advisory MCP cross-checker with an INJECTED mcp_query callable that, for each ORPHAN/ORPHAN_CLUSTER candidate in a SweepReport, queries inbound CALLS/IMPORTS/USAGE edges and appends a DISAGREEMENT note to WIRE_UP_SWEEP_REPORT.md without altering any verdict. Committed RED oracle tests/harness/test_mcp_crosscheck_advisory.py feeding a STUB MCP client and asserting a disagreement is RAISED while the verdict stays UNCHANGED.
