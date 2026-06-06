---
interfaces: "ngv2/submission.py exposes `render_submission(form)` and `assemble_package(finding, poc, live_test)`."
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

ngv2/submission.py — submission-package rendering

# Scope

Build ngv2/submission.py as a NEW single-file, whole-file, pure/deterministic, stdlib-only Python module (IMPL-only; oracle already committed at tests/test_submission.py). Implement `render_submission(form)` producing a deterministic markdown rendering of a huntr form (a 12-field form mapping/object), and `assemble_package(finding, poc, live_test)` building the full submission package from a Finding-shaped object, a poc-shaped object, and a passed-through `live_test` data value (never executed). All pure and deterministic with no I/O. working_dir: /home/xnihil0zer0/NobleGreedv2. Verify with `python -m pytest tests/test_submission.py -q`.

# Non-Goals

No file or network I/O. No third-party imports (stdlib only). No tests authored (oracle tests/test_submission.py already committed). Must NOT import any sibling leaf — ngv2/submission.py must NOT import ngv2/huntr_form.py or ngv2/cvss.py — nor any sibling sub-epic module; shared shapes (form fields, Finding) are restated as prose only. The `live_test` argument is passed-through data and must NEVER be executed (live work stays at NobleGreedv2 runtime). No cross-module wiring or integration glue.

# Inputs

The NobleGreedv2 repo at working_dir /home/xnihil0zer0/NobleGreedv2 with the committed stable `Finding` shape from ngv2/contracts.py (consumed via plain import) and other Epic-1/Epic-2 public shapes as needed. `render_submission(form)` consumes a huntr form object/mapping shaped as the 12 huntr form fields (restated as prose, NOT imported from ngv2/huntr_form.py). `assemble_package(finding, poc, live_test)` consumes a Finding-shaped object, a poc-shaped object, and an opaque pass-through `live_test` value. The committed oracle tests/test_submission.py pins exact markdown output and package shape. No inputs from sibling leaves.

# Deliverables

NEW file ngv2/submission.py exposing `render_submission(form)` (markdown) and `assemble_package(finding, poc, live_test)`. Pure/deterministic, stdlib-only, with no import of any sibling leaf. verification_command: `python -m pytest tests/test_submission.py -q`.
