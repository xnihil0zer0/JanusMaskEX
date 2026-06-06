---
interfaces: "ngv2/huntr_data.py exposes `parse_bounties(...) -> list[RepoBounty]` and `parse_existing_submissions(...)` plus a typed `RepoBounty` record."
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

ngv2-huntr-data

# Scope

Implement the new single-file, whole-file, pure/deterministic stdlib-only Python module ngv2/huntr_data.py to load huntr eligibility/bounty/submission JSON into typed RepoBounty records, exposing `parse_bounties` and `parse_existing_submissions`. It is IMPL-only, verified with `python -m pytest tests/test_huntr_data.py -q` under working_dir `/home/xnihil0zer0/NobleGreedv2`.

# Non-Goals

No live exploit execution (stays at NobleGreedv2 runtime). No tests authored by leaves (oracles already committed). No file or network I/O; injected runners only. No third-party imports (stdlib only). No leaf depends on another Epic-3 leaf and none depends on sibling sub-epics (grounding/triage/submission). No cross-module wiring or integration glue is added in this epic.

# Inputs

The external NobleGreedv2 repo at working_dir /home/xnihil0zer0/NobleGreedv2, already containing the committed Epic-1 substrate (ngv2/contracts.py with the stable Finding shape, ngv2/state_machine.py, ngv2/detonation.py) and committed Epic-2 modules. The committed leaf oracle: tests/test_huntr_data.py.

# Deliverables

A new single-file whole-file module ngv2/huntr_data.py exposing `parse_bounties(...) -> list[RepoBounty]` and `parse_existing_submissions(...)` plus a typed `RepoBounty` record. Every brief at every level carries working_dir /home/xnihil0zer0/NobleGreedv2; verification_command is `python -m pytest tests/test_huntr_data.py -q`.
