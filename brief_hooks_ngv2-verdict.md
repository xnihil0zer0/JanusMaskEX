---
interfaces: "ngv2/verdict.py exposes a `Verdict` dataclass (TP/FP + confidence) with `to_dict()`, `from_dict(...)`, and `validate(...)`."
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

ngv2-verdict — Verdict dataclass (TP/FP + confidence)

# Scope

Build ONE new whole-file, pure/deterministic, stdlib-only Python module ngv2/verdict.py in the external NobleGreedv2 repo (working_dir /home/xnihil0zer0/NobleGreedv2). It defines a `Verdict` dataclass carrying a TP/FP label and a confidence value, with serialization and validation helpers: `to_dict()` returning a plain dict representation, `from_dict(...)` reconstructing a `Verdict` from such a dict, and `validate(...)` checking the verdict's invariants (e.g. label is one of the allowed TP/FP values and confidence is in range). IMPL-only: the oracle is already committed at tests/test_verdict.py. Verify with `python -m pytest tests/test_verdict.py -q`.

# Non-Goals

Do NOT author or modify any test files (oracle already committed at tests/test_verdict.py). No file or network I/O; no third-party imports (stdlib only). Must NOT import any sibling Epic-3 leaf module (ngv2/triage_parser.py, ngv2/triage_aggregate.py) and must NOT be imported by them; this module stands alone. No cross-module wiring, integration glue, or live exploit execution. Do not depend on sibling sub-epics.

# Inputs

The external NobleGreedv2 repo at /home/xnihil0zer0/NobleGreedv2, containing committed Epic-1 substrate (ngv2/contracts.py, ngv2/state_machine.py, ngv2/detonation.py) and Epic-2 modules (ngv2/grounding.py, ngv2/poc_runner.py, ngv2/report.py, ngv2/pipeline.py), consumed only via plain imports of stable, already-tested public shapes if needed. The committed oracle tests/test_verdict.py pins the exact behavior.

# Deliverables

NEW single-file module ngv2/verdict.py exposing a `Verdict` dataclass (TP/FP label + confidence) with `to_dict()`, `from_dict(...)`, and `validate(...)`. working_dir /home/xnihil0zer0/NobleGreedv2; verification_command `python -m pytest tests/test_verdict.py -q`.
