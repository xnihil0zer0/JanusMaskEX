---
dependencies:
  - "sweep-classifier"
  - "mcp-crosscheck"
interfaces: "tests/harness/test_no_source_orphans.py imports the live classifier and asserts sweep_modules(repo_root, roots=discover_live_roots(repo_root)) yields an empty ORPHAN set modulo an explicit justified allowlist. The committed test (not any scripts/** runner) is the durable regression guard; Wave-2 remediation leaves carry dependencies:[regression_guard] so they cannot land before this guard exists to ratify them."
---

# Title

Wire-Up Sweep — committed regression guard tests/harness/test_no_source_orphans.py

# Scope

ADD the durable, load-bearing deliverable: tests/harness/test_no_source_orphans.py — a COMMITTED test that imports the live classifier, runs `sweep_modules` over the real source tree seeded from `discover_live_roots`, and asserts ZERO confirmed ORPHANs, modulo an EXPLICIT, reviewed allowlist of intentionally-deferred modules where each allowlist entry carries a one-line justification. This is the artifact that makes the no-orphan property PERMANENT: once Wave 2 remediates, the orphan class cannot silently regrow because CI fails the instant a confirmed orphan reappears. Its own verification_command IS this test: `python -m pytest tests/harness/test_no_source_orphans.py -q`. (A scripts/** human-invoked runner that regenerates the ledger is an acceptable convenience but is NOT the durable artifact — the committed test is.)

# Non-Goals

Does NOT reimplement sweep_modules, the MCP cross-check, or check_wired — it imports and drives the live classifier. Does NOT remediate orphans or author Wave-2 wire/remove/reclassify leaves (the allowlist defers them with justification, it does not fix them). Does NOT gate on the MCP advisory output. No agent spawns, model/API/network calls, live MCP calls, or un-injected subprocesses.

# Inputs

Consumes `sweep_modules(repo_root, *, roots) -> SweepReport` from sweep_classifier (the live classifier it imports and runs over the real source tree) and `discover_live_roots(repo_root) -> list[str]` from root_reconciliation (via the classifier's seeding) to obtain the reconciled roots. Consumes the advisory MCP cross-check disagreement surface from mcp_crosscheck only to inform the reviewed allowlist (the cross-check never gates this test). The SweepReport's ORPHAN set is the value asserted to be empty modulo the allowlist.

# Deliverables

tests/harness/test_no_source_orphans.py — a committed regression-guard test that runs sweep_modules over the live source tree and asserts ZERO confirmed ORPHANs modulo an explicit reviewed allowlist (each entry justified one line). This is the permanent property: CI fails the instant a confirmed orphan reappears. Its verification_command is itself.
