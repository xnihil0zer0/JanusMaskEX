---
interfaces: "exposes `Candidate` (JSON-serializable record with id, source/files, parent lineage, `fitness: dict`, `elo: float`, visit-count) and `PopulationDB.add/get/save/load` (round-trips Candidate JSON under injected `state_dir`; unknown DB => empty, not raise)"
---

# Title

Autocompiler persistent population DB (autocompiler/population.py)

# Scope

Build the NEW whole-file module `autocompiler/population.py` providing the durable candidate store: a JSON-serializable `Candidate` record and a `PopulationDB` with `add`/`get`/`save`/`load` that round-trips `Candidate` JSON under an injected `state_dir` (the durable-JSON-state pattern mirrored from `overseer/procedure_state.py`). Loading an unknown/absent DB yields an empty population (never raises). This is the cross-attempt memory that replaces `main()`'s local `valid_cache`. meta_task_type=`data_model`. verification_command: `python -m pytest tests/autocompiler/test_population.py tests/autocompiler/test_population_wired.py -q`. # Required plan shape: ONE impl task; meta_task_type=data_model; >=2 edge_cases mirrored in regression/property tests (e.g. (a) add->save->load round-trip preserves Candidate fields incl. fitness/elo/visit-count, (b) unknown/absent DB path => empty population not raise, (c) corrupt JSON => empty not raise). Module dotted path pre-registered in `config/autocompiler.yaml`.

# Non-Goals

Does NOT spawn any process, model, network, or un-injected subprocess (all FS I/O under the injected `state_dir`). Does NOT touch any `harness/**` or `_NEVER_AUTO_APPROVE` file. Does NOT flip a runtime flag. Does NOT author new tests. Pure/stdlib-only.

# Inputs

Fixed seams: `overseer/procedure_state.py` durable-JSON-state pattern; the injected `state_dir` discipline. Pre-committed RED oracles `tests/autocompiler/test_population.py` + `tests/autocompiler/test_population_wired.py` (e567269) ARE the contract; wiring oracle asserts `check_wired(repo_root, 'autocompiler/population.py').wired`.

# Deliverables

NEW whole-file `autocompiler/population.py`. Exposes a JSON-serializable `Candidate` record (carrying at minimum an id, source/files, parent lineage, a `fitness` dict, an `elo` float, and a visit-count) and `PopulationDB.add/get/save/load` round-tripping `Candidate` JSON under an injected `state_dir`; unknown DB => empty, not raise. Turns `tests/autocompiler/test_population.py` and `tests/autocompiler/test_population_wired.py` GREEN.
