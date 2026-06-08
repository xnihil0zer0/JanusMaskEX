---
interfaces: "ngv2/triage_aggregate.py exposes `aggregate(verdicts)` and `keep_true_positives(verdicts)` over a collection of verdict dicts."
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

ngv2-triage-aggregate — aggregate and keep_true_positives over verdicts

# Scope

Build ONE new whole-file, pure/deterministic, stdlib-only Python module ngv2/triage_aggregate.py in the external NobleGreedv2 repo (working_dir /home/xnihil0zer0/NobleGreedv2). It exposes `aggregate(verdicts)` producing counts over a collection of verdict dicts, and `keep_true_positives(verdicts)` filtering to the true-positive verdicts. IMPL-only: the oracle is already committed at tests/test_triage_aggregate.py. Verify with `python -m pytest tests/test_triage_aggregate.py -q`.

# Non-Goals

Do NOT author or modify any test files (oracle already committed at tests/test_triage_aggregate.py). No file or network I/O; no third-party imports (stdlib only). Must NOT import ngv2/verdict.py or any other Epic-3 leaf — the verdict dict shape is restated as prose only, not imported. No cross-module wiring, integration glue, or live exploit execution. Do not depend on sibling sub-epics.

# Inputs

The external NobleGreedv2 repo at /home/xnihil0zer0/NobleGreedv2 with committed Epic-1/Epic-2 modules consumed only via plain imports of stable public shapes if needed. The committed oracle tests/test_triage_aggregate.py pins the exact behavior. Shared shape (prose, NOT imported): each verdict is a dict carrying a TP/FP label field and a confidence value, the same conceptual shape produced by ngv2/triage_parser.py's `parse_triage(debate)` and ngv2/verdict.py's `Verdict.to_dict()`.

# Deliverables

NEW single-file module ngv2/triage_aggregate.py exposing `aggregate(verdicts)` (counts) and `keep_true_positives(verdicts)` (filter to TP verdicts). working_dir /home/xnihil0zer0/NobleGreedv2; verification_command `python -m pytest tests/test_triage_aggregate.py -q`.
