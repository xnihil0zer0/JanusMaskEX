---
interfaces: "ngv2/cvss.py exposes `parse_vector(...)`, `base_score(vector)` (deterministic CVSS v3.1), and `severity_label(score)`. ngv2/huntr_form.py exposes `HUNTR_FORM_FIELDS`, `CWE_VULN_TYPES`, and `build_form(finding, poc, context)` returning the 12 huntr form fields. ngv2/submission.py exposes `render_submission(form)` and `assemble_package(finding, poc, live_test)`."
working_dir: "/home/xnihil0zer0/NobleGreedv2"
epic: true
---

# Title

Sub-epic D — SUBMISSION packaging (epic: true)

# Scope

An epic (epic: true, plan_kind: epic) that decomposes into EXACTLY THREE leaf module briefs covering CVSS scoring, huntr form construction, and submission-package rendering, all under ngv2/ in the external NobleGreedv2 repo (working_dir: /home/xnihil0zer0/NobleGreedv2). The three leaves: (1) ngv2-cvss -> ngv2/cvss.py: `parse_vector(...)`, deterministic CVSS v3.1 `base_score(vector)`, and `severity_label(score)`. (2) ngv2-huntr-form -> ngv2/huntr_form.py: `HUNTR_FORM_FIELDS`, `CWE_VULN_TYPES`, and `build_form(finding, poc, context)` producing the 12 huntr form fields. (3) ngv2-submission -> ngv2/submission.py: `render_submission(form)` markdown and `assemble_package(finding, poc, live_test)`. Each leaf is a NEW single-file, whole-file, pure/deterministic stdlib-only Python module, IMPL-only (oracle already committed at tests/test_<leaf>.py), verified with `python -m pytest tests/test_<leaf>.py -q`. The three leaves are mutually independent — none may import another (e.g. ngv2/submission.py must not import ngv2/huntr_form.py or ngv2/cvss.py); shared shapes are restated as prose only.

# Non-Goals

No live exploit execution (the `live_test` argument to assemble_package is passed-through data, never executed; live work stays at NobleGreedv2 runtime). No tests authored by leaves (oracles already committed). No file or network I/O; injected runners only. No third-party imports (stdlib only). No leaf depends on another Epic-3 leaf (including no intra-sub-epic imports among cvss/huntr_form/submission) and none depends on sibling sub-epics. No cross-module wiring or integration glue is added in this epic.

# Inputs

The external NobleGreedv2 repo at working_dir /home/xnihil0zer0/NobleGreedv2, already containing the committed Epic-1 substrate (ngv2/contracts.py with the stable `Finding` shape, ngv2/state_machine.py, ngv2/detonation.py) and committed Epic-2 modules (ngv2/grounding.py, ngv2/poc_runner.py, ngv2/report.py, ngv2/pipeline.py), consumed only via plain imports of stable, already-tested public shapes. The three committed leaf oracles for this sub-epic: tests/test_cvss.py, tests/test_huntr_form.py, tests/test_submission.py.

# Deliverables

Three NEW single-file whole-file ngv2/ modules, each IMPL-only and pinned by its committed oracle: ngv2/cvss.py (`parse_vector(...)`, deterministic CVSS v3.1 `base_score(vector)`, `severity_label(score)`), ngv2/huntr_form.py (`HUNTR_FORM_FIELDS`, `CWE_VULN_TYPES`, `build_form(finding, poc, context)` -> the 12 huntr form fields), and ngv2/submission.py (`render_submission(form)` markdown and `assemble_package(finding, poc, live_test)`). Every brief at every level carries working_dir /home/xnihil0zer0/NobleGreedv2; each leaf verification_command is `python -m pytest tests/test_<leaf>.py -q`.
