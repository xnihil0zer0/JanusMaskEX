---
interfaces: "ngv2/triage_parser.py exposes `parse_triage(debate)` returning a normalized verdict dict (TP/FP label + confidence)."
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

ngv2-triage-parser — parse_triage(debate) to normalized verdict dict

# Scope

Build ONE new whole-file, pure/deterministic, stdlib-only Python module ngv2/triage_parser.py in the external NobleGreedv2 repo (working_dir /home/xnihil0zer0/NobleGreedv2). It exposes `parse_triage(debate)` which maps an ng-triage debate JSON structure to a normalized verdict dict (TP/FP label + confidence, matching the shared verdict shape described as prose). IMPL-only: the oracle is already committed at tests/test_triage_parser.py. Verify with `python -m pytest tests/test_triage_parser.py -q`.

# Non-Goals

Do NOT author or modify any test files (oracle already committed at tests/test_triage_parser.py). No file or network I/O; no third-party imports (stdlib only). Must NOT import ngv2/verdict.py or any other Epic-3 leaf — the normalized verdict dict shape is restated as prose only, not imported. No cross-module wiring, integration glue, or live exploit execution. Do not depend on sibling sub-epics.

# Inputs

The external NobleGreedv2 repo at /home/xnihil0zer0/NobleGreedv2 with committed Epic-1/Epic-2 modules consumed only via plain imports of stable public shapes if needed. The committed oracle tests/test_triage_parser.py pins the exact behavior. Shared shape (prose, NOT imported): a normalized verdict dict carries a TP/FP label field and a confidence value, the same conceptual shape that ngv2/verdict.py's `Verdict.to_dict()` produces.

# Deliverables

NEW single-file module ngv2/triage_parser.py exposing `parse_triage(debate)` that returns a normalized verdict dict (TP/FP label + confidence). working_dir /home/xnihil0zer0/NobleGreedv2; verification_command `python -m pytest tests/test_triage_parser.py -q`.
