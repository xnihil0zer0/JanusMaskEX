---
interfaces: "exposes `check_vacuity_stub(...)` / `check_complexity_floor(min_by_type)` / `check_no_exception_swallow(...)` -> `GateResult` (reuses `should_run_embedded_tests` to dodge the `test_*`-API false positive)"
---

# Title

Autocompiler anti-gaming vacuity/complexity gates (autocompiler/vacuity.py)

# Scope

Build the NEW whole-file module `autocompiler/vacuity.py` providing the net-new AST anti-gaming gates absent from `ast_enforcer._ValidationVisitor` (`:25`): `check_vacuity_stub`, `check_complexity_floor(min_by_type)`, and `check_no_exception_swallow`, each returning a `GateResult`. It reuses `should_run_embedded_tests` to dodge the `test_*`-API false positive (legitimate test scaffolding must not trip the stub gate). These keep the fitness signal trustworthy. meta_task_type=`validation`. verification_command: `python -m pytest tests/autocompiler/test_vacuity.py tests/autocompiler/test_vacuity_wired.py -q`. # Required plan shape: ONE impl task; meta_task_type=validation; >=2 edge_cases mirrored in regression/property tests (e.g. (a) `pass`/`...`/`raise NotImplementedError` stub body => ok=False, (b) below complexity floor for the node type => ok=False, (c) bare `except: pass` exception-swallow => ok=False, while a real `test_*` body via should_run_embedded_tests => ok=True). Module dotted path pre-registered in `config/autocompiler.yaml`.

# Non-Goals

Does NOT spawn any process, model, network, or un-injected subprocess. Does NOT modify `ast_enforcer` or any `harness/**`/`_NEVER_AUTO_APPROVE` file. Does NOT enforce by prompt — only by pure gate functions. Does NOT flip a runtime flag. Does NOT author new tests. Pure/stdlib-only.

# Inputs

Fixed seams: `overseer/gates.py::GateResult(ok, reason, fix_hint)` (`:28`) as the return type; the existing `should_run_embedded_tests` helper (reused to avoid the `test_*`-API false positive); `ast_enforcer._ValidationVisitor` (`:25`) as the prior-art reference only. Pre-committed RED oracles `tests/autocompiler/test_vacuity.py` + `tests/autocompiler/test_vacuity_wired.py` (e567269) ARE the contract; wiring oracle asserts `check_wired(repo_root, 'autocompiler/vacuity.py').wired`.

# Deliverables

NEW whole-file `autocompiler/vacuity.py`. Exposes `check_vacuity_stub` / `check_complexity_floor(min_by_type)` / `check_no_exception_swallow` -> `GateResult`; reuses `should_run_embedded_tests` to dodge the `test_*`-API false positive. Turns `tests/autocompiler/test_vacuity.py` and `tests/autocompiler/test_vacuity_wired.py` GREEN.
