---
interfaces: "exposes pure `compute_fitness(fuzz_result, gate_results, mutation_vacuous, pathology) -> dict` (error|hard_disproof => prune-floor; deterministic, JSON-safe)"
---

# Title

Autocompiler fitness-vector contract (autocompiler/fitness.py)

# Scope

Build the NEW whole-file module `autocompiler/fitness.py` providing the pure fitness-vector contract `compute_fitness(fuzz_result, gate_results, mutation_vacuous, pathology) -> dict`. It folds the empirical-fuzzer signal (1 counterexample = hard disproof; N clean rounds = soft proof) plus the anti-gaming gate results into a deterministic, JSON-safe fitness dict. `error` or `hard_disproof` states map to the prune-floor. meta_task_type=`data_model`. verification_command: `python -m pytest tests/autocompiler/test_fitness.py tests/autocompiler/test_fitness_wired.py -q`. # Required plan shape: ONE impl task; meta_task_type=data_model; >=2 edge_cases mirrored in regression/property tests (e.g. (a) error|hard_disproof => prune-floor value, (b) determinism: same inputs => byte-identical dict, (c) JSON-safety: result round-trips through json.dumps/loads). Module dotted path pre-registered in `config/autocompiler.yaml`.

# Non-Goals

Does NOT spawn any process, model, network, or un-injected subprocess. Does NOT call the real fuzzer — it consumes an already-produced `FuzzResult`. Does NOT touch any `harness/**` or `_NEVER_AUTO_APPROVE` file. Does NOT flip a runtime flag. Does NOT author new tests. Pure/stdlib-only.

# Inputs

Fixed seams: `harness/diff_fuzzer.py` `FuzzResult`/`FuzzFailure` (`:46`) shape as the only fitness source; `overseer/gates.py::GateResult(ok, reason, fix_hint)` (`:28`) as the `gate_results` element shape. Pre-committed RED oracles `tests/autocompiler/test_fitness.py` + `tests/autocompiler/test_fitness_wired.py` (e567269) ARE the contract; wiring oracle asserts `check_wired(repo_root, 'autocompiler/fitness.py').wired`.

# Deliverables

NEW whole-file `autocompiler/fitness.py`. Exposes pure `compute_fitness(fuzz_result, gate_results, mutation_vacuous, pathology) -> dict`; `error|hard_disproof` => prune-floor; deterministic and JSON-safe. Turns `tests/autocompiler/test_fitness.py` and `tests/autocompiler/test_fitness_wired.py` GREEN.
