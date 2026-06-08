---
interfaces: "ngv2/fp_filter.py exposes `FPPattern`, `load_fp_patterns(...)`, `matches(...)`, and `filter_findings(...)`."
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

ngv2-fp-filter — false-positive filtering of by-design / protocol-mandated findings

# Scope

Build a NEW single-file, whole-file, pure/deterministic, stdlib-only Python module at ngv2/fp_filter.py providing false-positive filtering. Expose `FPPattern` (a false-positive pattern type), `load_fp_patterns(...)` (build/load the set of FPPattern entries), `matches(...)` (decide whether a finding matches an FPPattern), and `filter_findings(...)` (drop by-design / protocol-mandated false positives from a collection of findings). IMPL-only: the oracle is already committed at tests/test_fp_filter.py. working_dir: /home/xnihil0zer0/NobleGreedv2. Verify with `python -m pytest tests/test_fp_filter.py -q`.

# Non-Goals

No file or network I/O — load_fp_patterns must not read real files or network resources (patterns are sourced deterministically per the oracle). No live exploit execution. No third-party imports (stdlib only). Do NOT author or modify any test/oracle (tests/test_fp_filter.py is already committed). No dependency on the semgrep_adapter or confidence siblings, and no dependency on sibling sub-epics. No cross-module wiring or integration glue.

# Inputs

The external NobleGreedv2 repo at working_dir /home/xnihil0zer0/NobleGreedv2, including committed Epic-1 substrate (ngv2/contracts.py, ngv2/state_machine.py, ngv2/detonation.py) and committed Epic-2 modules (ngv2/grounding.py, ngv2/poc_runner.py, ngv2/report.py, ngv2/pipeline.py), consumed only via plain imports of stable, already-tested public shapes if needed. The committed oracle tests/test_fp_filter.py pins the exact expected behavior, the FPPattern shape, and the filtering semantics and is the source of truth.

# Deliverables

One NEW single-file whole-file module ngv2/fp_filter.py, IMPL-only, pinned by tests/test_fp_filter.py. It exposes `FPPattern`, `load_fp_patterns(...)`, `matches(...)`, and `filter_findings(...)` to drop by-design / protocol-mandated false positives. verification_command: `python -m pytest tests/test_fp_filter.py -q`. working_dir: /home/xnihil0zer0/NobleGreedv2.
