---
interfaces: "ngv2/huntr_form.py exposes `HUNTR_FORM_FIELDS`, `CWE_VULN_TYPES`, and `build_form(finding, poc, context)` returning the 12 huntr form fields."
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

ngv2/huntr_form.py — huntr submission form construction

# Scope

Build ngv2/huntr_form.py as a NEW single-file, whole-file, pure/deterministic, stdlib-only Python module (IMPL-only; oracle already committed at tests/test_huntr_form.py). Define `HUNTR_FORM_FIELDS` (the ordered set of huntr form field identifiers), `CWE_VULN_TYPES` (CWE-to-vulnerability-type mapping), and `build_form(finding, poc, context)` which assembles and returns the 12 huntr form fields from a Finding-shaped object, a poc-shaped object, and a context-shaped object. All pure and deterministic with no I/O. working_dir: /home/xnihil0zer0/NobleGreedv2. Verify with `python -m pytest tests/test_huntr_form.py -q`.

# Non-Goals

No file or network I/O. No third-party imports (stdlib only). No tests authored (oracle tests/test_huntr_form.py already committed). Must NOT import any sibling leaf (ngv2/cvss.py, ngv2/submission.py) nor any sibling sub-epic module — shared shapes are restated as prose only. No live exploit execution. No cross-module wiring or integration glue.

# Inputs

The NobleGreedv2 repo at working_dir /home/xnihil0zer0/NobleGreedv2 with the committed stable `Finding` shape from ngv2/contracts.py (consumed via plain import) and other Epic-1/Epic-2 public shapes as needed. `build_form(finding, poc, context)` consumes a Finding-shaped object, a poc result/object, and a context object as plain data. The committed oracle tests/test_huntr_form.py pins exact field names, the 12-field output, and the CWE mapping. No inputs from sibling leaves.

# Deliverables

NEW file ngv2/huntr_form.py exposing `HUNTR_FORM_FIELDS`, `CWE_VULN_TYPES`, and `build_form(finding, poc, context)` returning the 12 huntr form fields. Pure/deterministic, stdlib-only. verification_command: `python -m pytest tests/test_huntr_form.py -q`.
