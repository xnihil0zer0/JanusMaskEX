---
working_dir: "/home/xnihil0zer0/JanusMaskJR"
epic: true
required_child_slugs:
  - report02_p1_dict_synth
  - report02_p2_onesided_oracle
interfaces: >
  EPIC implementing INTEGRATION_REPORT_02 (the fuzzable-surface / trust program).
  Decomposes into FIVE child phases P1-P5. ONLY P1 (dict-synth) and P2 (one-sided
  oracle) are activated/built in this cycle; P3-P5 are declared as structural
  children only and are NOT allowlisted. Every phase follows the STEP-ZERO rollout
  pattern: a default-OFF autowork.* flag whose OFF path is byte-identical to HEAD,
  shadow-mode first (compute + log, never block), verified in the REAL bwrap jail.
  All phases are sensitive-path (harness/**) work -> meta_task_type harness_self_fix.
---

# Title
Report 02 — Maximize the differentially-fuzzable surface (dict-synth + one-sided oracle), shadow-mode, default-OFF

# Scope
This is an EPIC (`epic: true`). It implements the phased roadmap of
`/home/xnihil0zer0/AI-Data/Research-JanusMask/INTEGRATION_REPORT_02_fuzzable_surface.md`
(§4 per-piece seam design, §5 phased roadmap, §6 anti-pattern register). The epic
decomposes into FIVE child phases:

- **P1 — domain-dict input synthesis** (child slug `report02_p1_dict_synth`). ACTIVATED
  this cycle. Two LOCK-STEP seams in ONE change-set: (Seam 1) add a domain-dict strategy
  dispatch branch in `harness/diff_fuzzer.py` mirroring the existing `_AST_*_CORPUS` /
  `_PATH_CORPUS` precedent — when a param's name+annotation map to a registered domain
  dict, return `st.sampled_from(corpus)`; unknown -> unchanged fallback; and (Seam 2)
  widen `harness/rebuild/harvest.py::_is_fuzzable_annotation` for the SAME domain-dict
  names so classification stays in lock-step with capability (anti-pattern A7). Gated
  behind `autowork.dict_corpus_synthesis` (default false -> byte-identical to HEAD).

- **P2 — one-sided oracle** (child slug `report02_p2_onesided_oracle`). ACTIVATED this
  cycle, AFTER P1 lands (it also edits `diff_fuzzer.py`; the file-overlap dispatch veto
  serializes it — declared via `dependencies: [report02_p1_dict_synth]`). Replaces the
  unconditional `equivalent=True` ONE-SIDE waiver at the `diff_fuzzer.py` `not a_has or
  not b_has` region with a real fail-closed degrade ladder (golden -> metamorphic ->
  determinism-only); `unverified` is fail-closed (`equivalent` False) and EMITs a
  `skipped_reason` — never a silent pass. The genuinely-absent-on-BOTH-sides branch
  stays a documented skip. Gated behind `autowork.onesided_oracle` (default false ->
  byte-identical skip). Conservative relations only (idempotence / round-trip /
  order-invariance / determinism).

- **P3 — decision_core meta type** (DEFERRED — declared for structure only, NOT
  allowlisted, NOT built this cycle). P3 is the COMPLEMENTARY POLICY HALF: P1 makes the
  fuzzer CAPABLE of synthesizing domain dicts; P3 makes those now-fuzzable pure cores
  actually USED (routes them to `'fuzz'` instead of collapsing into `harness_self_fix`).
  Per the verdict and report §5 ★-complementarity note, P1 WITHOUT P3 makes the fuzzer
  capable but still unused for the meta-types where most work lands. P3 is sequenced
  later by owner decision.

- **P4 — CrossHair `diffbehavior` advisory** (DEFERRED — structure only). Non-blocking,
  advisory-only, permanently behind its own default-OFF flag.

- **P5 — RuleBasedStateMachine model-mirror** (DEFERRED — structure only). For the
  irreducible stateful tail; built only after P1-P3 shrink the residual stateful set.

The SHADOW-MODE discipline (report §5, A4, A9) is binding for the activated phases: the
"on" state computes the new strategy/verdict and LOGS it (false-divergence telemetry /
skipped_reason counts) but does NOT block dispatch in this build. Flipping to a BLOCKING
gate is a LATER operator decision after measuring false-divergence.

# Inputs
SPEC: `/home/xnihil0zer0/AI-Data/Research-JanusMask/INTEGRATION_REPORT_02_fuzzable_surface.md`
(§4 seams, §5 roadmap, §6 register A1-A12). VERDICT: `PRIORITIZATION_VERDICT_v3.md` §4
SECOND + §6 backlog (P1 dict-synth row; P1🔒 one-sided oracle row — "the single
best-substantiated finding in the whole audit … the one truly trust-critical item").

PoC SEED material (the source for the child leaf oracles/corpus/relations — NOT a
license to hand-edit prod): `/home/xnihil0zer0/AI-Data/Research-JanusMask/wave2_poc/`
— `dict_synth.py` + `test_dict_synth_poc.py` (8/8 green), `onesided_oracle.py` +
`test_onesided_oracle.py` (11/11 green).

VERIFIED current code (HEAD c61140e): `harness/diff_fuzzer.py` ships `_AST_*_CORPUS` /
`_PATH_CORPUS` (~:67-116) + `_ast_strategy_for` / `_path_strategy` dispatch (~:131-159);
the primary stateless strategy builder `build_input_strategy` (~:506) iterates
`name -> annotation` and calls `_strategy_for_annotation(annotation)` per param (name IS
in scope — the natural dict-synth seam). The ONE-SIDE waiver lives in `fuzz_from_task`
(~:899) at the `not a_has or not b_has` region (~:925-938): the absent-BOTH branch and
the one-side branch each `return FuzzResult(equivalent=True, skipped_reason=...)`.
`harvest.py::_is_fuzzable_annotation` (~:228) carries the LOAD-BEARING lock-step comment
(~:231-235). `PYTHONHASHSEED` is already pinned in the sandbox child env
(`sandbox.py` `python_hash_seed`, 3 copies) — A1 determinism is already covered, the
seam need not re-add it. `hypothesis_jsonschema` is NOT installed in the factory
interpreter, so tier-3 schema synthesis MUST be import-guarded (any error -> None) and
the tier-2 corpus path (the highest-ROI lever) MUST work with `hypothesis` alone.
`autowork.dict_corpus_synthesis` and `autowork.onesided_oracle` do NOT exist yet
(added by the children, default false). Fail-safe flag idiom = `load_config()` guarded
so any error -> flag off -> byte-identical (mirror `orchestrator.py::_wire_up_gate_enabled`
~:2030-2047). `diff_fuzzer.py` and `harvest.py` are `harness/**` but NOT in the
irreducible `_NEVER_AUTO_APPROVE` set -> `harness_self_fix`, auto-approve-eligible, NO
decision files needed.

# Non-Goals
Integration is out of scope for the child leaves' core implementation tasks (the literal
word `integration` is carried here and restated in each child's `# Required plan shape`
to excuse the integration-test requirement on a `.py`-editing task). This epic does NOT
weaken `BYPASS_FUZZER_TYPES` in any way (anti-pattern A6 / held-brief directive) — it
ADDS capability (dict synth) and a fail-closed one-sided verdict; it removes NOTHING from
the bypass set. It does NOT make either gate BLOCKING — both ship SHADOW-MODE
(non-blocking) in this build; flipping to blocking is a later operator decision. It does
NOT build P3 (`decision_core`), P4 (CrossHair), or P5 (RBSM) — those are declared as
structural children only and are not allowlisted. It does NOT add `hypothesis_jsonschema`
as a hard dependency (tier-3 stays import-guarded/optional). It does NOT hand-author
oracles or hand-edit production — the pipeline authors the RED oracles from the seed PoCs.

# Deliverables
A decomposed epic plan (`plan_hooks_report02_fuzzable_surface.json`, `plan_kind: "epic"`)
naming the five children, with P1 and P2 emitted as standalone allowlistable child briefs
at the repo root. P1 + P2 each land as `harness_self_fix` commits whose OFF-flag path is
byte-identical to HEAD and whose ON path is shadow-mode (computed + logged, non-blocking),
each GREEN under its scoped verification_command, verified in the real bwrap jail, with
`BYPASS_FUZZER_TYPES` unchanged. P3/P4/P5 are declared children, not built.

# Required plan shape
Decompose into EXACTLY FIVE children with these slugs (required_child_slugs enforces it):
`report02_p1_dict_synth`, `report02_p2_onesided_oracle`, `report02_p3_decision_core`,
`report02_p4_crosshair_advisory`, `report02_p5_rbsm_model_mirror`.

- The TWO activated children (`report02_p1_dict_synth`, `report02_p2_onesided_oracle`)
  are authored as full standalone leaf briefs (the operator allowlists them; P2 carries
  `dependencies: [report02_p1_dict_synth]`).
- The THREE deferred children are decomposition placeholders ONLY — `epic_planning` /
  structure entries, NOT allowlisted, with no implementation tasks built this cycle.
- Every code-touching child task is `meta_task_type: harness_self_fix` (sensitive
  `harness/**` writes).
- State in P1's body that P3 is the complementary policy half (capability vs. usage).
