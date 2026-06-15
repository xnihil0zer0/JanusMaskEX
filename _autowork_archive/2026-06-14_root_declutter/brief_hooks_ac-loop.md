---
dependencies:
  - "ac_flags"
  - "ac_population_db"
  - "ac_fitness_vector"
  - "ac_elo"
  - "ac_selection"
  - "ac_crossover"
  - "ac_containment"
  - "ac_vacuity"
interfaces: "exposes pure `step(db, seams) -> db'` (select->operate->run_seam->fitness->insert->rate; never spawns a process/model). Consumes: `Candidate`/`PopulationDB.add/get/save/load` (ac_population_db), `p_ucb(cands, c, total_n)` (ac_selection), `ast_crossover(a, b)`/`file_crossover(...)` (ac_crossover), `compute_fitness(fuzz_result, gate_results, mutation_vacuous, pathology) -> dict` (ac_fitness_vector), `expected_score`/`update_elo`/`tournament_round(pairs, rater_seam)` (ac_elo), `check_write_containment(parent, cand, ranges) -> GateResult` (ac_containment), `check_vacuity_stub`/`check_complexity_floor(min_by_type)`/`check_no_exception_swallow -> GateResult` (ac_vacuity), `ac_enabled(key, state_dir=None) -> bool` (ac_flags)"
---

# Title

Autocompiler pure evolutionary step (autocompiler/loop.py)

# Scope

Build the NEW whole-file module `autocompiler/loop.py` providing the pure orchestration `step(db, seams) -> db'`: select (P-UCB) -> operate (crossover) -> run_seam (test run) -> compute fitness -> insert into population -> rate (Elo). It composes the sibling Phase-A pure modules over INJECTED seams (`model_seam`, `run_seam`, `git_seam`, and the injected `state_dir`) and NEVER spawns a real process or model. This is the population loop the worker's post-synthesis region will later route through (Phase C), accepting the population winner via the UNCHANGED `_auto_commit_accepted` gate. meta_task_type=`orchestration`. verification_command: `python -m pytest tests/autocompiler/test_loop.py tests/autocompiler/test_loop_wired.py -q`. # Required plan shape: ONE impl task; meta_task_type=orchestration; >=2 edge_cases mirrored in regression/property tests (e.g. (a) one step grows the population by the operated candidate and updates Elo via the injected rater, (b) a hard_disproof candidate is scored to the prune-floor (kept as memory, not crashed on), (c) all I/O routes through injected seams — no real process/model spawned). Module dotted path pre-registered in `config/autocompiler.yaml`.

# Non-Goals

Does NOT spawn any real process, model, network, or un-injected subprocess — every spawn/test-run/git op flows through an injected seam. Does NOT bypass the verifier — the empirical fuzzer/test gate still decides truth. Does NOT touch any `harness/**` or `_NEVER_AUTO_APPROVE` file or wire itself into the worker (that is Phase C). Does NOT flip a runtime flag. Does NOT author new tests. Pure/stdlib-only.

# Inputs

Consumes from siblings: `ac_population_db` (`Candidate`; `PopulationDB.add/get/save/load` under injected `state_dir`), `ac_selection` (`p_ucb(cands, c, total_n)`), `ac_crossover` (`ast_crossover(a, b)` via injected `_ast_merge` seam; `file_crossover`), `ac_fitness_vector` (`compute_fitness(fuzz_result, gate_results, mutation_vacuous, pathology) -> dict`), `ac_elo` (`expected_score`/`update_elo`; `tournament_round(pairs, rater_seam)`), `ac_containment` (`check_write_containment(parent, cand, ranges) -> GateResult`), `ac_vacuity` (`check_vacuity_stub`/`check_complexity_floor`/`check_no_exception_swallow -> GateResult`), and `ac_flags` (`ac_enabled(key, state_dir=None) -> bool`). Fixed seams: `harness/diff_fuzzer.py::differential_fuzz` (`:641`) shape behind `run_seam`; `harness/orchestrator.py::_auto_commit_accepted` (`:2407`) as the unchanged terminal accept (referenced, not called this run). Pre-committed RED oracles `tests/autocompiler/test_loop.py` + `tests/autocompiler/test_loop_wired.py` (e567269) ARE the contract; wiring oracle asserts `check_wired(repo_root, 'autocompiler/loop.py').wired`.

# Deliverables

NEW whole-file `autocompiler/loop.py`. Exposes pure `step(db, seams) -> db'` performing select->operate->run_seam->fitness->insert->rate; never spawns a process/model. Turns `tests/autocompiler/test_loop.py` and `tests/autocompiler/test_loop_wired.py` GREEN.
