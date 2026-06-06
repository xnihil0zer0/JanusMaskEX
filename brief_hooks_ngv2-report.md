---
interfaces: "from ngv2.contracts import VERDICTS; build_report(state, reports) -> dict  # {'phase': state.phase, 'findings': [f.to_dict() ...], 'results': [r.to_dict() ...], 'summary': {'total_findings': int, 'confirmed': int, 'refuted': int, 'error': int, 'inconclusive': int}}; render_markdown(report: dict) -> str"
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

ngv2/report.py — deterministic report builder + markdown renderer

# Scope

Build NEW file ngv2/report.py: a pure (no I/O), deterministic, stdlib-only report builder and markdown renderer over a HuntState's findings and the detonation LiveTestReports. It receives objects and calls their .to_dict(); it does NOT re-implement the dataclasses. IMPL-ONLY (oracle tests/test_report.py already committed). Expose `build_report(state, reports) -> dict`: state is a HuntState-like object exposing .phase (str) and .findings (list of Finding); reports is a list of LiveTestReport. Returns a dict with EXACT keys {'phase': state.phase, 'findings': [f.to_dict() for f in state.findings], 'results': [r.to_dict() for r in reports], 'summary': {...}}, where the summary sub-dict has 'total_findings': len(state.findings) plus one count per verdict in VERDICTS — 'confirmed', 'refuted', 'error', 'inconclusive' — each being the number of reports whose .verdict equals that value. Expose `render_markdown(report: dict) -> str`: returns a huntr-submission-shaped markdown string that STARTS with '#' (top-level header) and, for each finding, CONTAINS its title and target, and CONTAINS each result's verdict text (e.g. a confirmed result's section contains the word 'confirmed'); build it by reading the dict produced by build_report (do not require live objects).

# Non-Goals

Do NOT author, create, or modify any test file — tests/test_report.py is already committed; emit NO test_authoring task. Do NOT do any I/O, file access, subprocess, socket, or network. Do NOT use eval, exec, or __import__. No globals or randomness; stdlib only. Do NOT re-implement or redefine Finding, LiveTestReport, HuntState, or VERDICTS — read the imported VERDICTS and call the objects' .to_dict(). Do NOT add fields, public functions, or symbols beyond build_report and render_markdown; do NOT change their names, signatures, dict keys, or return shapes. Do NOT depend on or import any other Epic-2 child module (grounding, poc_runner, pipeline).

# Inputs

The already-committed Epic-1 substrate module ngv2.contracts, for VERDICTS = ('confirmed','refuted','error','inconclusive') and the dataclass shapes. state is a HuntState-like object with .phase (str) and .findings (list of Finding, each with .to_dict()). reports is a list of LiveTestReport(poc_finding_id, verdict, exit_code, stdout, stderr, duration_ms), each with .verdict and .to_dict(). render_markdown consumes only the dict returned by build_report. The committed oracle tests/test_report.py pins behavior.

# Deliverables

NEW file ngv2/report.py exposing `build_report(state, reports) -> dict` with EXACT keys 'phase', 'findings', 'results', 'summary' (summary = {'total_findings': len(state.findings)} plus a per-VERDICTS-member count of reports by .verdict: 'confirmed', 'refuted', 'error', 'inconclusive') and `render_markdown(report: dict) -> str` that starts with '#' and contains each finding's title and target and each result's verdict text. Verified by the committed tests/test_report.py via `python -m pytest tests/test_report.py -q`.
