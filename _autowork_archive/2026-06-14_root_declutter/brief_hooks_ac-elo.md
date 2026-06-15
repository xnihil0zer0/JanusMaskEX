---
interfaces: "exposes `expected_score(...)`/`update_elo(...)` (standard K-factor formula) and `tournament_round(pairs, rater_seam)` (uses the injected rater only; never spawns a real model)"
---

# Title

Autocompiler Elo rating math (autocompiler/elo.py)

# Scope

Build the NEW whole-file module `autocompiler/elo.py` providing the pairwise Elo math: `expected_score` and `update_elo` matching the standard K-factor formula, plus `tournament_round(pairs, rater_seam)` which runs a pairwise Flash-rater tournament strictly through the INJECTED `rater_seam` (no real model spawn). This is the smooth fitness landscape that lets near-misses accumulate retained rating. meta_task_type=`data_model`. verification_command: `python -m pytest tests/autocompiler/test_elo.py tests/autocompiler/test_elo_wired.py -q`. # Required plan shape: ONE impl task; meta_task_type=data_model; >=2 edge_cases mirrored in regression/property tests (e.g. (a) expected_score symmetry / equal-ratings => 0.5, (b) update_elo conserves total under the K-factor, (c) tournament_round consults ONLY the injected rater_seam, never a real model). Module dotted path pre-registered in `config/autocompiler.yaml`.

# Non-Goals

Does NOT spawn any real model, process, network, or un-injected subprocess — the rater is always the injected `rater_seam`. Does NOT touch any `harness/**` or `_NEVER_AUTO_APPROVE` file. Does NOT flip a runtime flag. Does NOT author new tests. Pure/stdlib-only.

# Inputs

Fixed seams: the `model_seam` (rater-spawn) injection discipline; `overseer/gates.py` pure-function discipline. Pre-committed RED oracles `tests/autocompiler/test_elo.py` + `tests/autocompiler/test_elo_wired.py` (e567269) ARE the contract; wiring oracle asserts `check_wired(repo_root, 'autocompiler/elo.py').wired`.

# Deliverables

NEW whole-file `autocompiler/elo.py`. Exposes `expected_score`/`update_elo` matching the K-factor formula and `tournament_round(pairs, rater_seam)` that uses the injected rater only. Turns `tests/autocompiler/test_elo.py` and `tests/autocompiler/test_elo_wired.py` GREEN.
