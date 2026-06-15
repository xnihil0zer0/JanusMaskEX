---
dependencies:
  - "ac_population_db"
interfaces: "exposes `p_ucb(cands, c, total_n)` = argmax `Elo + c*sqrt(ln N / n_i)` over `Candidate`s (unseen n=0 explores; ties deterministic)"
---

# Title

Autocompiler P-UCB selection (autocompiler/selection.py)

# Scope

Build the NEW whole-file module `autocompiler/selection.py` providing `p_ucb(cands, c, total_n)` = argmax over candidates of `Elo + c*sqrt(ln N / n_i)`, where each candidate carries an Elo and a visit count `n_i` (the `Candidate` shape from `autocompiler/population.py`). Unseen candidates (n=0) are forced to explore; ties resolve deterministically. This steers the generation budget toward the promising lineage. meta_task_type=`planner_tooling`. verification_command: `python -m pytest tests/autocompiler/test_selection.py tests/autocompiler/test_selection_wired.py -q`. # Required plan shape: ONE impl task; meta_task_type=planner_tooling; >=2 edge_cases mirrored in regression/property tests (e.g. (a) an unseen n=0 candidate is selected (infinite exploration term), (b) equal-score ties broken deterministically (stable order), (c) higher-Elo wins when visit counts equal). Module dotted path pre-registered in `config/autocompiler.yaml`.

# Non-Goals

Does NOT spawn any process, model, network, or un-injected subprocess. Does NOT mutate the population DB or re-rate candidates (selection is read-only over the candidate list). Does NOT touch any `harness/**` or `_NEVER_AUTO_APPROVE` file. Does NOT flip a runtime flag. Does NOT author new tests. Pure/stdlib-only.

# Inputs

Consumes from `ac_population_db`: `Candidate` (JSON-serializable record with id, source/files, parent lineage, `fitness: dict`, `elo: float`, visit-count). Pre-committed RED oracles `tests/autocompiler/test_selection.py` + `tests/autocompiler/test_selection_wired.py` (e567269) ARE the contract; wiring oracle asserts `check_wired(repo_root, 'autocompiler/selection.py').wired`.

# Deliverables

NEW whole-file `autocompiler/selection.py`. Exposes `p_ucb(cands, c, total_n)` = argmax `Elo + c*sqrt(ln N / n_i)`; unseen (n=0) explores; ties deterministic. Turns `tests/autocompiler/test_selection.py` and `tests/autocompiler/test_selection_wired.py` GREEN.
