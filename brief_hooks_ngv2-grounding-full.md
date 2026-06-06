---
interfaces: "ngv2/semgrep_adapter.py exposes `build_semgrep_argv(...)` and `run_semgrep(target, *, runner)`. ngv2/fp_filter.py exposes `FPPattern`, `load_fp_patterns(...)`, `matches(...)`, and `filter_findings(...)`. ngv2/confidence.py exposes `CONFIDENCE_TIERS` and `classify(signals)`."
working_dir: "/home/xnihil0zer0/NobleGreedv2"
epic: true
---

# Title

Sub-epic B — GROUNDING & confidence (epic: true)

# Scope

An epic (epic: true, plan_kind: epic) that decomposes into EXACTLY THREE leaf module briefs covering static-analysis grounding, false-positive filtering, and multi-tool confidence scoring, all under ngv2/ in the external NobleGreedv2 repo (working_dir: /home/xnihil0zer0/NobleGreedv2). The three leaves: (1) ngv2-semgrep-adapter -> ngv2/semgrep_adapter.py: exposing `build_semgrep_argv(...)` and injected-runner `run_semgrep(target, *, runner)`. (2) ngv2-fp-filter -> ngv2/fp_filter.py: exposing `FPPattern`, `load_fp_patterns`, `matches`, and `filter_findings` to drop by-design / protocol-mandated false positives. (3) ngv2-confidence -> ngv2/confidence.py: exposing `CONFIDENCE_TIERS` and `classify(signals)` for 4-tier confidence from multi-tool agreement. Each leaf is a NEW single-file, whole-file, pure/deterministic stdlib-only Python module, IMPL-only (oracle already committed at tests/test_<leaf>.py), verified with `python -m pytest tests/test_<leaf>.py -q`. The three leaves are mutually independent.

# Non-Goals

No live exploit execution (stays at NobleGreedv2 runtime). No tests authored by leaves (oracles already committed). No file or network I/O — semgrep execution is reached only through an injected `runner`, never a real subprocess/network call. No third-party imports (stdlib only). No leaf depends on another Epic-3 leaf and none depends on sibling sub-epics (intake/triage/submission). No cross-module wiring or integration glue is added in this epic.

# Inputs

The external NobleGreedv2 repo at working_dir /home/xnihil0zer0/NobleGreedv2, already containing the committed Epic-1 substrate (ngv2/contracts.py, ngv2/state_machine.py, ngv2/detonation.py) and committed Epic-2 modules (ngv2/grounding.py, ngv2/poc_runner.py, ngv2/report.py, ngv2/pipeline.py), consumed only via plain imports of stable, already-tested public shapes. The three committed leaf oracles for this sub-epic: tests/test_semgrep_adapter.py, tests/test_fp_filter.py, tests/test_confidence.py.

# Deliverables

Three NEW single-file whole-file ngv2/ modules, each IMPL-only and pinned by its committed oracle: ngv2/semgrep_adapter.py (`build_semgrep_argv(...)` and `run_semgrep(target, *, runner)` using only the injected runner), ngv2/fp_filter.py (`FPPattern`, `load_fp_patterns`, `matches`, `filter_findings` dropping by-design / protocol-mandated FPs), and ngv2/confidence.py (`CONFIDENCE_TIERS` and `classify(signals)` deterministic 4-tier confidence from multi-tool agreement). Every brief at every level carries working_dir /home/xnihil0zer0/NobleGreedv2; each leaf verification_command is `python -m pytest tests/test_<leaf>.py -q`.
