---
interfaces: "exposes `extract_evolve_ranges(src)` (tokenizer; malformed => `[]`) and `check_write_containment(parent, cand, ranges) -> GateResult` (node outside range => ok=False)"
---

# Title

Autocompiler EVOLVE-BLOCK write-containment gate (autocompiler/containment.py)

# Scope

Build the NEW whole-file module `autocompiler/containment.py` providing `extract_evolve_ranges(src)` — a comment-tokenizer (mirroring the `# JANUSMASK_DELETE:` precedent `harness/git_integration.py:840-857`) that returns the EVOLVE-BLOCK line ranges and yields `[]` on malformed markers — plus `check_write_containment(parent, cand, ranges) -> GateResult` which fails (`ok=False`) when the candidate edits any AST node outside the permitted ranges. This makes the fitness signal un-gameable by containing where evolution may write. meta_task_type=`validation`. verification_command: `python -m pytest tests/autocompiler/test_containment.py tests/autocompiler/test_containment_wired.py -q`. # Required plan shape: ONE impl task; meta_task_type=validation; >=2 edge_cases mirrored in regression/property tests (e.g. (a) malformed/unbalanced EVOLVE markers => extract returns [], (b) edit fully inside range => ok=True, (c) any node changed outside range => ok=False). Module dotted path pre-registered in `config/autocompiler.yaml`.

# Non-Goals

Does NOT spawn any process, model, network, or un-injected subprocess. Does NOT enforce containment by prompt — only by the pure gate function. Does NOT touch any `harness/**` or `_NEVER_AUTO_APPROVE` file. Does NOT flip a runtime flag. Does NOT author new tests. Pure/stdlib-only.

# Inputs

Fixed seams: the `# JANUSMASK_DELETE:` comment-tokenizer precedent (`harness/git_integration.py:840-857`); `overseer/gates.py::GateResult(ok, reason, fix_hint)` (`:28`) as the return type. Pre-committed RED oracles `tests/autocompiler/test_containment.py` + `tests/autocompiler/test_containment_wired.py` (e567269) ARE the contract; wiring oracle asserts `check_wired(repo_root, 'autocompiler/containment.py').wired`.

# Deliverables

NEW whole-file `autocompiler/containment.py`. Exposes `extract_evolve_ranges(src)` (tokenizer; malformed => `[]`) and `check_write_containment(parent, cand, ranges) -> GateResult` (node outside range => ok=False). Turns `tests/autocompiler/test_containment.py` and `tests/autocompiler/test_containment_wired.py` GREEN.
