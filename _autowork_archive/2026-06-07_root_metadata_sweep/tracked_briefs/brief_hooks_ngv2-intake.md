---
interfaces: "ngv2/huntr_data.py exposes `parse_bounties(...) -> list[RepoBounty]` and `parse_existing_submissions(...)` plus a typed `RepoBounty` record. ngv2/prioritize.py exposes `expected_payout(bounty, severity)` and `rank_targets(bounties, *, severity)`. ngv2/dedup.py exposes `normalize_title(...)`, `is_duplicate(...)`, and `filter_new(findings, existing_titles)` over ngv2.contracts.Finding."
working_dir: "/home/xnihil0zer0/NobleGreedv2"
epic: true
---

# Title

Sub-epic A — INTAKE & prioritization (epic: true)

# Scope

An epic (epic: true, plan_kind: epic) that decomposes into EXACTLY THREE leaf module briefs covering huntr target intake and ROI prioritization, all under the ngv2/ package of the external NobleGreedv2 repo (working_dir: /home/xnihil0zer0/NobleGreedv2). The three leaves: (1) ngv2-huntr-data -> ngv2/huntr_data.py: load huntr eligibility/bounty/submission JSON into typed RepoBounty records, exposing `parse_bounties` and `parse_existing_submissions`. (2) ngv2-prioritize -> ngv2/prioritize.py: deterministic ROI ranking, exposing `expected_payout(bounty, severity)` and `rank_targets(bounties, *, severity)` with a saturation tie-break. (3) ngv2-dedup -> ngv2/dedup.py: dedup over ngv2.contracts.Finding, exposing `normalize_title`, `is_duplicate`, and `filter_new(findings, existing_titles)`. Each leaf is a NEW single-file, whole-file, pure/deterministic stdlib-only Python module, IMPL-only (its oracle is already committed at tests/test_<leaf>.py), verified with `python -m pytest tests/test_<leaf>.py -q`. No Epic-3 leaf depends on another; the three leaves here are mutually independent and may build in any order.

# Non-Goals

No live exploit execution (stays at NobleGreedv2 runtime). No tests authored by leaves (oracles already committed). No file or network I/O; injected runners only. No third-party imports (stdlib only). No leaf depends on another Epic-3 leaf and none depends on sibling sub-epics (grounding/triage/submission). No cross-module wiring or integration glue is added in this epic.

# Inputs

The external NobleGreedv2 repo at working_dir /home/xnihil0zer0/NobleGreedv2, already containing the committed Epic-1 substrate (ngv2/contracts.py with the stable `Finding` shape, ngv2/state_machine.py, ngv2/detonation.py) and committed Epic-2 modules (ngv2/grounding.py, ngv2/poc_runner.py, ngv2/report.py, ngv2/pipeline.py), consumed only via plain imports of stable, already-tested public shapes. The three committed leaf oracles for this sub-epic: tests/test_huntr_data.py, tests/test_prioritize.py, tests/test_dedup.py.

# Deliverables

Three NEW single-file whole-file ngv2/ modules, each IMPL-only and pinned by its committed oracle: ngv2/huntr_data.py (typed `RepoBounty` records; `parse_bounties` and `parse_existing_submissions` loading huntr eligibility/bounty/submission JSON), ngv2/prioritize.py (`expected_payout(bounty, severity)` and `rank_targets(bounties, *, severity)` deterministic ROI ranking with saturation tie-break), and ngv2/dedup.py (`normalize_title`, `is_duplicate`, `filter_new(findings, existing_titles)` over ngv2.contracts.Finding). Every brief at every level carries working_dir /home/xnihil0zer0/NobleGreedv2; each leaf verification_command is `python -m pytest tests/test_<leaf>.py -q`.
