---
epic: false
working_dir: "/home/xnihil0zer0/NobleGreedv2"
interfaces: "pure stdlib functions; no I/O, no LLM calls, no third-party deps"
---

# Title

Token-ROI evolutionary selection layer for NobleGreedv2 (Agentic Spine Epic A)

Build the pure, deterministic token-ROI optimization layer for the NobleGreedv2 bug-hunting
pipeline: AlphaZero-PUCT + Elo payload-mutation selection, Shannon-entropy/KL debate early-stopping,
source-metadata ablation, a Swiss-system finding ranker, and a narrowly-scoped PoC success-marker
stub checker. Every deliverable is a pure, standard-library-only function or AST transform with no
network, subprocess, or LLM dependency — chosen as the first epic because it is fully verifiable by
the dual-agent differential fuzzer and carries no side-effecting or hallucinated-target risk. This
epic proves the external-build spine end-to-end before any SQLite/MCP/detonation work is attempted.
It is a single multi-task **leaf** brief (five tasks), NOT a decomposed epic — see `# Required plan
shape`.

# Scope

- `ngv2/payload_selection.py` (NEW, whole-file): `select_next_mutation(state, arms, elo, visits,
  values, c=1.414)` using the **AlphaZero PUCT** form `Q(a) + c·P(a)·√N/(1+N(a))` with `P(a)` a
  softmax over Elo ratings, plus `update_elo(winner, loser, outcome, k=32)` and
  `expected_score(a, b)`. **Port the Elo math verbatim** from JanusMaskJR `autocompiler/elo.py`
  (verified: `expected_score(ra, rb)`, `update_elo(ra, rb, score_a, k=32.0)` — the `k=32` default and
  the logistic `expected_score` match). The PUCT selection itself is **new code**, NOT a port:
  JanusMaskJR `autocompiler/selection.py::p_ucb` is plain **UCB1** (`elo + c·√(ln N / n)`), so use it
  only as the structural reference for the candidate/visit seam (each arm carries a rating and a visit
  count; counts are injected) — do **not** copy its formula. Do NOT import either module — keep NGv2
  stdlib-only and decoupled.
- `ngv2/ablation.py` (NEW, whole-file): `ablate_source_code(src)` (AST docstring/comment strip +
  inline-comment regex) and `obfuscate_pathnames(src, file_map)`. Pure AST-in/string-out.
- `ngv2/swiss_tournament.py` (NEW, whole-file): `swiss_rank(items, judge)` over an injected pairwise
  `judge` seam — deterministic pairing and tie-break, O(R·N) rounds.
- `ngv2/debate_router.py` (EDIT, ADDITIVE): add `calculate_shannon_entropy(probs)` and
  `calculate_kl_divergence(p, q)` and an `early_stop(history, h_thresh=0.1, kl_thresh=0.05)` helper.
  Preserve EVERY existing top-level symbol: `route_finding`, `DebateFinding`, `AUTO_SUBMIT_THRESHOLD`,
  `AUTO_REJECT_THRESHOLD`, `_coerce_score`, `_extract_confidence` (verified — there are no existing
  entropy/KL helpers; you are adding new ones).
- `ngv2/ast_verifier.py` (EDIT, ADDITIVE): add a **narrowly-scoped** `PocMarkerStubChecker` that
  flags a function returning a hardcoded success-marker **string** constant (e.g. `"VULNERABLE"`,
  `"CONFIRMED"`, `"SUCCESS"`) — and NOTHING else. Preserve the existing top-level symbols `Violation`,
  `ASTResult`, `ASTVerifier`, `SEVERITY_ERROR`, `SEVERITY_WARNING` (verified). Match the existing
  checker pattern: `ASTVerifier` walks the tree and dispatches to private `_check_*` methods that
  append `Violation`s — add the marker check the same way. Do NOT flag `True`/`False`/`None`/numeric
  returns.

# Non-Goals

The word integration appears here deliberately: this epic ships pure unit-level functions and does
not require cross-module integration tests. Out of bounds: any LLM call, any subprocess/network, any
SQLite or session-DB work, any change to `rl_debate_weights.py` (it is already a working UCB1 bandit
at `:15`/`:90` — `UCB_C=1.41`, `accuracy + UCB_C·√(ln total/n)` — do not replace it with Elo), any
global constant-return ban (the checker is success-marker-string-only), importing JanusMaskJR's
`autocompiler/` package into NGv2, and any third-party dependency (numpy, scipy, choix). The softmax
temperature must be Elo-scaled (default ~174 = 400/ln10, or normalize Elos first) — do not hardcode
τ=100.

# Inputs

Reuse, do not rebuild. Cleanroom math references (do NOT import): JanusMaskJR `autocompiler/elo.py`
(`expected_score`/`update_elo`/`tournament_round` — the Elo port source), `autocompiler/selection.py`
(`p_ucb` — **UCB1**, structural seam reference only, not a formula source), `autocompiler/crossover.py`,
`autocompiler/vacuity.py` (`check_vacuity_stub`/`check_complexity_floor`/`check_no_exception_swallow`).
NGv2 targets to consume/preserve: `ngv2/debate_router.py` (symbols above), `ngv2/ast_verifier.py`
(symbols above), `ngv2/ast_constraint.py` (`is_clean` at `:136`), `ngv2/contracts.py`. The new checker
oracle must prove it clears the real source of all of these. NGv2 is stdlib-only: `requirements.txt`
is `pytest>=7` and the core has zero runtime deps — keep it that way.

# Deliverables

Five committed modules/edits, each behind a pre-committed non-vacuous oracle that is RED against a
`NotImplementedError` stub and GREEN against the implementation:

1. `ngv2/payload_selection.py` — selection + Elo math; oracle asserts deterministic arm choice on a
   fixed table (the PUCT form, NOT UCB1 — unseen arms still get a finite prior-weighted score), Elo
   symmetry (`update_elo` conserves total ±rounding), and softmax normalization with an Elo-scaled τ.
2. `ngv2/ablation.py` — oracle asserts docstrings/comments removed, code semantics preserved
   (re-parse equals), and idempotence (`ablate(ablate(x)) == ablate(x)`).
3. `ngv2/swiss_tournament.py` — oracle asserts a fixed bracket yields a deterministic ranking and the
   judge seam is called O(R·N) times, not O(N²).
4. `ngv2/debate_router.py` (additive) — oracle asserts `H([0.98,0.02])≈0.141`, `KL(p,p)=0`, monotone
   early-stop, and that `route_finding` and every other existing symbol are unchanged.
5. `ngv2/ast_verifier.py` (additive) — oracle FIRST asserts the new checker returns CLEAN on the real
   source of `ast_constraint.py`, `contracts.py`, `state_machine.py`, `debate_router.py` (no false
   positives on the codebase's own green code), THEN asserts it flags a synthetic
   `def poc(): return "VULNERABLE"`.

# Required plan shape

Produce exactly five leaf tasks, one file each, in this order (module-creating tasks first). This is
a single non-epic plan — the planner emits these five tasks directly; do NOT decompose into child
briefs.

- LEAF A1 `payload_selection` — meta_task_type `planner_tooling`, NEW whole-file, pure/fuzzable.
- LEAF A2 `ablation` — meta_task_type `planner_tooling`, NEW whole-file, pure/fuzzable.
- LEAF A3 `swiss_tournament` — meta_task_type `planner_tooling`, NEW whole-file, pure/fuzzable over
  the injected `judge` seam.
- LEAF A4 `debate_router_entropy` — meta_task_type `validation`, EDIT existing `ngv2/debate_router.py`
  additively.
- LEAF A5 `ast_verifier_marker` — meta_task_type `validation`, EDIT existing `ngv2/ast_verifier.py`
  additively. Oracle proves no-false-positive on the four named existing modules before asserting the
  positive case.

**Plan-shape invariants for EVERY leaf (NEW and EDIT alike):** every leaf MUST list at least two edge_cases in its test_spec and mirror EACH into regression_tests or property_tests (the plan validator hard-drops any leaf without this); name a `*_wired` oracle in
`verification_command` (e.g. `tests/ngv2/test_payload_selection_wired.py`) — required because the
plan validator resolves `files_touched` against the JanusMaskJR repo root, where these NGv2 paths are
absent, so every leaf reads as module-creating and a `*_wired` oracle name is mandatory to pass
validation (the runtime wire-up gate itself no-ops for external/rootless target trees). Carry the
literal word `integration` in each leaf's `non_goals` (these are unit leaves; no cross-module
integration test is wanted). Each NEW module is emitted whole-file (the patch path cannot create
files); each EDIT leaf preserves every existing top-level symbol and emits additively. One file per
task.

Sequencing is by holding the allowlist, not frontmatter deps: build A first (it proves the spine).
A and B have no code dependency and may run concurrently; allowlist B/C/D only as each prior epic
goes green.
