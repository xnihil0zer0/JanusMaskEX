---
interfaces: "ngv2/semgrep_adapter.py exposes `build_semgrep_argv(...)` and `run_semgrep(target, *, runner)` (semgrep reached only via the injected `runner`)."
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

ngv2-semgrep-adapter — static-analysis grounding via injected semgrep runner

# Scope

Build a NEW single-file, whole-file, pure/deterministic, stdlib-only Python module at ngv2/semgrep_adapter.py providing static-analysis grounding. Expose `build_semgrep_argv(...)` which constructs the semgrep command-line argument vector deterministically from its inputs, and `run_semgrep(target, *, runner)` which reaches semgrep ONLY through the injected `runner` callable (passing it the argv built by build_semgrep_argv) and normalizes/returns its result. IMPL-only: the oracle is already committed at tests/test_semgrep_adapter.py. working_dir: /home/xnihil0zer0/NobleGreedv2. Verify with `python -m pytest tests/test_semgrep_adapter.py -q`.

# Non-Goals

No real subprocess, shell-out, file, or network I/O — semgrep is reached exclusively through the injected `runner`, never a real subprocess/network call. No live exploit execution. No third-party imports (stdlib only). Do NOT author or modify any test/oracle (tests/test_semgrep_adapter.py is already committed). No dependency on the fp_filter or confidence siblings, and no dependency on sibling sub-epics (intake/triage/submission). No cross-module wiring or integration glue.

# Inputs

The external NobleGreedv2 repo at working_dir /home/xnihil0zer0/NobleGreedv2, including committed Epic-1 substrate (ngv2/contracts.py, ngv2/state_machine.py, ngv2/detonation.py) and committed Epic-2 modules (ngv2/grounding.py, ngv2/poc_runner.py, ngv2/report.py, ngv2/pipeline.py), consumed only via plain imports of stable, already-tested public shapes if needed. The committed oracle tests/test_semgrep_adapter.py pins the exact expected behavior and signatures and is the source of truth for argv shape and runner contract.

# Deliverables

One NEW single-file whole-file module ngv2/semgrep_adapter.py, IMPL-only, pinned by tests/test_semgrep_adapter.py. It exposes `build_semgrep_argv(...)` and `run_semgrep(target, *, runner)` where semgrep is invoked only through the injected `runner`. verification_command: `python -m pytest tests/test_semgrep_adapter.py -q`. working_dir: /home/xnihil0zer0/NobleGreedv2.
