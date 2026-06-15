---
dependencies:
  - "ac_population_db"
interfaces: "exposes `ast_crossover(a, b)` (composes non-overlapping symbols via injected `_ast_merge` seam) and `file_crossover(...)` (picks per-file winners; no real git)"
---

# Title

Autocompiler AST/file crossover over injected git seam (autocompiler/crossover.py)

# Scope

Build the NEW whole-file module `autocompiler/crossover.py` providing `ast_crossover(a, b)` which composes the non-overlapping top-level symbols of two `Candidate`s by delegating to the INJECTED `_ast_merge` seam (the additive by-name top-level merge `harness/git_integration.py::_ast_merge` `:103`), plus `file_crossover` which picks per-file winners. No real git or worktree is touched — staging/merge flow strictly through the injected `git_seam`. This recombines partial successes. meta_task_type=`harness_plumbing`. verification_command: `python -m pytest tests/autocompiler/test_crossover.py tests/autocompiler/test_crossover_wired.py -q`. # Required plan shape: ONE impl task; meta_task_type=harness_plumbing; >=2 edge_cases mirrored in regression/property tests (e.g. (a) non-overlapping symbols from a+b both appear in the merged result via the injected seam, (b) overlapping/colliding symbol resolved by the additive merge rule, (c) file_crossover picks the per-file winner; no real git invoked). Module dotted path pre-registered in `config/autocompiler.yaml`.

# Non-Goals

Does NOT call real git, create real staging worktrees, or invoke the real `_ast_merge` directly — all flows through the injected `git_seam`/`_ast_merge` seam. Does NOT spawn any process, model, network, or un-injected subprocess. Does NOT touch any `harness/**` or `_NEVER_AUTO_APPROVE` file. Does NOT flip a runtime flag. Does NOT author new tests. Pure/stdlib-only.

# Inputs

Consumes from `ac_population_db`: `Candidate` (JSON-serializable record with id, source/files, parent lineage, `fitness: dict`, `elo: float`, visit-count). Fixed seam: `harness/git_integration.py::_ast_merge` (`:103`) is injected, not called directly. Pre-committed RED oracles `tests/autocompiler/test_crossover.py` + `tests/autocompiler/test_crossover_wired.py` (e567269) ARE the contract; wiring oracle asserts `check_wired(repo_root, 'autocompiler/crossover.py').wired`.

# Deliverables

NEW whole-file `autocompiler/crossover.py`. Exposes `ast_crossover(a, b)` composing non-overlapping symbols via the injected `_ast_merge` seam, and `file_crossover` picking per-file winners; no real git. Turns `tests/autocompiler/test_crossover.py` and `tests/autocompiler/test_crossover_wired.py` GREEN.
