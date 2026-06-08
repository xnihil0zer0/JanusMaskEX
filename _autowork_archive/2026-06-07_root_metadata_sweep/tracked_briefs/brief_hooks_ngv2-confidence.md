---
interfaces: "ngv2/confidence.py exposes `CONFIDENCE_TIERS` and `classify(signals)`."
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

ngv2-confidence — 4-tier confidence scoring from multi-tool agreement

# Scope

Build a NEW single-file, whole-file, pure/deterministic, stdlib-only Python module at ngv2/confidence.py providing multi-tool confidence scoring. Expose `CONFIDENCE_TIERS` (the ordered set/definition of the 4 confidence tiers) and `classify(signals)` which deterministically maps multi-tool agreement signals to one of the 4 tiers. IMPL-only: the oracle is already committed at tests/test_confidence.py. working_dir: /home/xnihil0zer0/NobleGreedv2. Verify with `python -m pytest tests/test_confidence.py -q`.

# Non-Goals

No file or network I/O. No live exploit execution. No third-party imports (stdlib only). Output must be deterministic — no randomness, wall-clock, or environment dependence. Do NOT author or modify any test/oracle (tests/test_confidence.py is already committed). No dependency on the semgrep_adapter or fp_filter siblings, and no dependency on sibling sub-epics. No cross-module wiring or integration glue.

# Inputs

The external NobleGreedv2 repo at working_dir /home/xnihil0zer0/NobleGreedv2, including committed Epic-1 substrate (ngv2/contracts.py, ngv2/state_machine.py, ngv2/detonation.py) and committed Epic-2 modules (ngv2/grounding.py, ngv2/poc_runner.py, ngv2/report.py, ngv2/pipeline.py), consumed only via plain imports of stable, already-tested public shapes if needed. The committed oracle tests/test_confidence.py pins the exact tier definitions and classify semantics and is the source of truth.

# Deliverables

One NEW single-file whole-file module ngv2/confidence.py, IMPL-only, pinned by tests/test_confidence.py. It exposes `CONFIDENCE_TIERS` and `classify(signals)` producing a deterministic 4-tier confidence from multi-tool agreement. verification_command: `python -m pytest tests/test_confidence.py -q`. working_dir: /home/xnihil0zer0/NobleGreedv2.
