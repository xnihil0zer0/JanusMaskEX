---
interfaces: "ngv2/verdict.py exposes a `Verdict` dataclass (TP/FP + confidence) with `to_dict()`, `from_dict(...)`, and `validate(...)`. ngv2/triage_parser.py exposes `parse_triage(debate)` returning a normalized verdict dict. ngv2/triage_aggregate.py exposes `aggregate(verdicts)` and `keep_true_positives(verdicts)`."
working_dir: "/home/xnihil0zer0/NobleGreedv2"
epic: true
---

# Title

Sub-epic C — TRIAGE & verdict (epic: true)

# Scope

An epic (epic: true, plan_kind: epic) that decomposes into EXACTLY THREE leaf module briefs covering verdict modeling, triage-debate parsing, and verdict aggregation, all under ngv2/ in the external NobleGreedv2 repo (working_dir: /home/xnihil0zer0/NobleGreedv2). The three leaves: (1) ngv2-verdict -> ngv2/verdict.py: a `Verdict` dataclass (TP/FP + confidence) with `to_dict`/`from_dict`/`validate`. (2) ngv2-triage-parser -> ngv2/triage_parser.py: `parse_triage(debate)` mapping an ng-triage debate JSON to a normalized verdict dict. (3) ngv2-triage-aggregate -> ngv2/triage_aggregate.py: `aggregate(verdicts)` producing counts plus `keep_true_positives(verdicts)`. Each leaf is a NEW single-file, whole-file, pure/deterministic stdlib-only Python module, IMPL-only (oracle already committed at tests/test_<leaf>.py), verified with `python -m pytest tests/test_<leaf>.py -q`. The three leaves are mutually independent — note ngv2-triage-parser and ngv2-triage-aggregate must NOT import ngv2/verdict.py (no leaf depends on another Epic-3 leaf); shared shape is restated as prose only.

# Non-Goals

No live exploit execution (stays at NobleGreedv2 runtime). No tests authored by leaves (oracles already committed). No file or network I/O; injected runners only. No third-party imports (stdlib only). No leaf depends on another Epic-3 leaf (including no intra-sub-epic import of ngv2/verdict.py by the parser/aggregate leaves) and none depends on sibling sub-epics. No cross-module wiring or integration glue is added in this epic.

# Inputs

The external NobleGreedv2 repo at working_dir /home/xnihil0zer0/NobleGreedv2, already containing the committed Epic-1 substrate (ngv2/contracts.py, ngv2/state_machine.py, ngv2/detonation.py) and committed Epic-2 modules (ngv2/grounding.py, ngv2/poc_runner.py, ngv2/report.py, ngv2/pipeline.py), consumed only via plain imports of stable, already-tested public shapes. The three committed leaf oracles for this sub-epic: tests/test_verdict.py, tests/test_triage_parser.py, tests/test_triage_aggregate.py.

# Deliverables

Three NEW single-file whole-file ngv2/ modules, each IMPL-only and pinned by its committed oracle: ngv2/verdict.py (`Verdict` dataclass carrying TP/FP + confidence with `to_dict`, `from_dict`, `validate`), ngv2/triage_parser.py (`parse_triage(debate)` mapping an ng-triage debate JSON to a normalized verdict dict), and ngv2/triage_aggregate.py (`aggregate(verdicts)` counts and `keep_true_positives(verdicts)`). Every brief at every level carries working_dir /home/xnihil0zer0/NobleGreedv2; each leaf verification_command is `python -m pytest tests/test_<leaf>.py -q`.
