---
interfaces: "ngv2/cvss.py exposes `parse_vector(...)`, `base_score(vector)` (deterministic CVSS v3.1), and `severity_label(score)`."
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

ngv2/cvss.py — deterministic CVSS v3.1 scoring

# Scope

Build ngv2/cvss.py as a NEW single-file, whole-file, pure/deterministic, stdlib-only Python module (IMPL-only; oracle already committed at tests/test_cvss.py). Implement `parse_vector(...)` to parse a CVSS v3.1 vector string into its metric components, deterministic `base_score(vector)` computing the CVSS v3.1 base score per the official spec arithmetic (exploitability + impact subscores, scope-aware roundup), and `severity_label(score)` mapping a numeric base score to its qualitative severity rating. All functions must be pure and deterministic with no I/O. working_dir: /home/xnihil0zer0/NobleGreedv2. Verify with `python -m pytest tests/test_cvss.py -q`.

# Non-Goals

No file or network I/O. No third-party imports (stdlib only). No tests authored (oracle tests/test_cvss.py already committed). Must NOT import any sibling leaf (ngv2/huntr_form.py, ngv2/submission.py) nor any sibling sub-epic module. No live exploit execution. No cross-module wiring or integration glue.

# Inputs

The NobleGreedv2 repo at working_dir /home/xnihil0zer0/NobleGreedv2 with committed Epic-1/Epic-2 substrate available via plain imports of stable public shapes if needed (ngv2/contracts.py etc.). The committed oracle tests/test_cvss.py pins exact behavior. No inputs from sibling leaves.

# Deliverables

NEW file ngv2/cvss.py exposing `parse_vector(...)`, deterministic CVSS v3.1 `base_score(vector)`, and `severity_label(score)`. Pure/deterministic, stdlib-only. verification_command: `python -m pytest tests/test_cvss.py -q`.
