---
interfaces: "ngv2/prioritize.py exposes `expected_payout(bounty, severity)` and `rank_targets(bounties, *, severity)`."
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

ngv2-prioritize

# Scope

Implement the new single-file, whole-file, pure/deterministic stdlib-only Python module ngv2/prioritize.py for deterministic ROI ranking, exposing `expected_payout(bounty, severity)` and `rank_targets(bounties, *, severity)` with a saturation tie-break. It is IMPL-only, verified with `python -m pytest tests/test_prioritize.py -q` under working_dir `/home/xnihil0zer0/NobleGreedv2`.

# Non-Goals

No live exploit execution (stays at NobleGreedv2 runtime). No tests authored by leaves (oracles already committed). No file or network I/O; injected runners only. No third-party imports (stdlib only). No leaf depends on another Epic-3 leaf and none depends on sibling sub-epics (grounding/triage/submission). No cross-module wiring or integration glue is added in this epic.

# Inputs

The external NobleGreedv2 repo at working_dir /home/xnihil0zer0/NobleGreedv2, already containing the committed Epic-1 substrate (ngv2/contracts.py with the stable Finding shape, ngv2/state_machine.py, ngv2/detonation.py) and committed Epic-2 modules. The committed leaf oracle: tests/test_prioritize.py.

# Deliverables

A new single-file whole-file module ngv2/prioritize.py exposing `expected_payout(bounty, severity)` and `rank_targets(bounties, *, severity)`. Every brief at every level carries working_dir /home/xnihil0zer0/NobleGreedv2; verification_command is `python -m pytest tests/test_prioritize.py -q`.
