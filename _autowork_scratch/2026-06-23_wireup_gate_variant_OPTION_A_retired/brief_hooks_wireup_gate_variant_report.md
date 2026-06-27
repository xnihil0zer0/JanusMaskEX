---
working_dir: /home/xnihil0zer0/JanusMaskJR
priority: high
required_task_ids: [wireup-gate-variant-report-oracle, wireup-gate-variant-report-impl, wireup-gate-variant-report-reauthor-accept, wireup-gate-variant-report-reauthor-enforce]
interfaces: |
  Rewire the REPORT-ONLY `uncovered` predicate inside the EXISTING accept-time
  wire-up gate `harness.orchestrator._run_wire_up_gate` (def at orchestrator.py
  line 2241; criterion currently at lines 2300-2323; report/enforce branch at
  2324-2339) so it composes the already-landed `harness/wire_up.py` detonation
  primitives instead of the current declaration-only check. The report/enforce
  branch body, the call site (orchestrator.py:3185), and ALL three knob readers
  (`_wire_up_runtime_gate_enabled` :2201 cfg `wire_up_runtime_gate`=false,
  `_wire_up_runtime_gate_enforce_enabled` :2177 =false, `_wire_up_gate_enabled`
  :2222 =true) are REUSED UNCHANGED. config/config.yaml lines 80-82 are NOT
  edited (this brief does NOT flip enforce). Primitives wired (all in
  harness/wire_up.py, confirmed present): FLOOR
  `symbol_reachable_from_live_root(repo_root, module_rel, symbol, *,
  roots=LIVE_ROOTS) -> bool` (:689); `LIVE_ROOTS` (:37); RUNNER
  `detonate_oracle(oracle_source, symbols, live_root_files, *, repo_root,
  jailed=True) -> dict[str,bool]` (:572, builds its own bwrap jail, fail-closed,
  never raises); EXEMPT `validate_exemption(category, symbol, module_rel,
  repo_root, *, roots=LIVE_ROOTS) -> ExemptionVerdict(honored, requires_recheck,
  reason)` (:667). These three are NOT yet imported in orchestrator.py
  (`new_top_level_callables, LIVE_ROOTS, check_wired, WireResult` already are);
  the impl adds the three new imports.
---

# Title

Rewire the wire-up runtime gate `uncovered` predicate to compose the landed detonation primitives (REPORT-ONLY, behind default-OFF `wire_up_runtime_gate`; enforce stays OFF and untouched)

# Scope

The accept-time gate `harness.orchestrator._run_wire_up_gate` already diffs each
already-tracked touched `.py` module against its parent HEAD (via
`new_top_level_callables`) and computes an `uncovered` set of new top-level
callables, then SHADOW-REPORTS each one (`phase=='report'`,
`event=='orphan_symbol_unwired'`) under the default-OFF `wire_up_runtime_gate`
knob. Today that `uncovered` predicate (orchestrator.py:2323) is
DECLARATION-ONLY: a symbol is uncovered unless it is named in a structurally
valid `integration_contract` OR sits verbatim in `wire_exempt`. The prior
backtest proved this declaration check ~89-100% false-positive when armed; the
fix (this brief) is to replace the predicate with the COMPOSED disjunction over
the three already-landed `harness/wire_up.py` primitives, STILL strictly
report-only.

This brief is REPORT-ONLY. The `wire_up_runtime_gate` knob is default-OFF and
stays OFF in config; the `wire_up_runtime_gate_enforce` knob is OFF, untouched,
and NOT flipped. The report/enforce branch body (orchestrator.py:2324-2339) is
reused exactly: when `wire_up_runtime_gate` is ON and enforce is OFF, a non-empty
`uncovered` set still only logs one `phase=='report'` row and the gate NEVER
rolls back and NEVER returns True.

The new `uncovered` predicate — for each new top-level callable S in
`new_top_level_callables` (already computed), S is `uncovered` iff ALL of:

  1. NOT `symbol_reachable_from_live_root(staging_path, rel, S)`  — FLOOR FIRST.
     The cheap, sound, real-teeth static check. It short-circuits on module
     un-reachability and only descends into a symbol scan when the host module
     is reachable from a LIVE_ROOT. A true zero-caller orphan returns False here
     (clause stays True -> still uncovered). A genuinely static-reachable symbol
     returns True (clause False -> SUPPRESSED). This is the net-new behavior.
  2. AND NOT (`contract_valid` AND S in `contract.symbols` AND
     `detonate_oracle(...)[S]`)  — DETONATION upgrade. Detonation runs ONLY when
     a structurally valid contract NAMES S (so the common static-reachable /
     no-contract case never pays the subprocess cost). `contract_valid` keeps
     the EXISTING definition (`entrypoints` non-empty AND every entrypoint in
     LIVE_ROOTS AND a `runtime_oracle` string declared). The oracle source is
     read DEFENSIVELY from `staging_path/<contract.runtime_oracle>` (the
     contract's `runtime_oracle` is a PATH string, not inline source); any
     read/parse failure -> empty source -> `detonate_oracle` fail-closes to
     `{S: False}` -> this clause is False -> S stays subject to clauses 1 and 3.
  3. AND NOT `wire_exempt_validated(S)`  — CHECKED exemption. `wire_exempt` is a
     FLAT list of bare symbol names with no per-symbol category, so EVERY listed
     name is validated as category `pure_helper`:
     `validate_exemption('pure_helper', S, rel, staging_path).honored`. honored
     True -> suppress; honored False (S not floor-reachable under pure_helper) ->
     S stays uncovered (reported). This is conservative: an exemption can never
     suppress a true orphan, matching the anti-gaming intent. NOTE this REPLACES
     the current verbatim `S in wire_exempt` membership test.

# Inputs

- TARGET (re-read to confirm): `harness/orchestrator.py` def `_run_wire_up_gate`
  at line 2241; the `uncovered = sorted(...)` predicate at line 2323 (with the
  contract/exempt extraction at 2300-2322); the report/enforce branch at
  2324-2339 (REUSE as-is); call site at 3185 (REUSE as-is). The three knob
  readers at 2177 / 2201 / 2222 (REUSE as-is).
- PRIMITIVES (all confirmed in `harness/wire_up.py`):
  `symbol_reachable_from_live_root` (:689), `LIVE_ROOTS` (:37, already imported),
  `detonate_oracle` (:572), `validate_exemption` + `ExemptionVerdict` (:667 /
  :662). The impl ADDS imports for `symbol_reachable_from_live_root`,
  `detonate_oracle`, `validate_exemption` (LIVE_ROOTS / new_top_level_callables
  already imported at orchestrator.py:2175).
- CONTRACT surface (unchanged): `task['constraints']['integration_contract']` =
  `{entrypoints:[subset of LIVE_ROOTS], symbols:[...], runtime_oracle:<path str>}`.
- EXEMPT surface (unchanged shape, changed semantics): `task['wire_exempt']` OR
  `task['constraints']['wire_exempt']` = a FLAT list of bare symbol names.
- IDIOM to reuse for the oracle's hermetic synthetic git tree:
  `tests/harness/test_wire_up_runtime_gate_accept.py` `_build_tree` /
  `_arm` / `_task` / `_drive` / `_read_rows` — a committed PARENT `pkg/mod.py`
  plus a sibling staging worktree whose committed child adds a new callable;
  knobs toggled by monkeypatching the module-level readers (`raising=False`);
  assertions read back from `state_dir/impl_progress.jsonl`.
- KEY FACT (verified empirically against these primitives): in the existing
  `pkg/mod.py` fixtures the new callable (`brand_new`, `wired_one`,
  `make_widget`) is NOT floor-reachable (its host module is not under any
  LIVE_ROOT and it has zero live-root callers), so
  `symbol_reachable_from_live_root` returns False — i.e. the FLOOR clause does
  NOT suppress it. To assert the net-new FLOOR-suppress behavior the oracle MUST
  build a DISTINCT fixture in which the new callable IS statically reachable from
  a LIVE_ROOT (e.g. the module is a real LIVE_ROOT or is statically imported &
  referenced along a live-root chain in the synthetic tree).

# Non-Goals

- NOT an integration test. This brief authors a hermetic, unit-level behavioral
  oracle over `_run_wire_up_gate` ONLY; it never drives the full pipeline, spawns
  a real agent, or hits a real LIVE_ROOT inline. The literal word `integration`
  appears here solely to excuse the integration-test requirement.
- Does NOT flip `wire_up_runtime_gate_enforce` and does NOT edit
  `config/config.yaml`. Behavior is byte-identical to today when
  `wire_up_runtime_gate` is OFF.
- Does NOT touch the report/enforce branch BODY, the call site, the knob
  readers, the module-level `orphan_unwired` path, or any `harness/wire_up.py`
  primitive (those are composed, not re-implemented).
- The hermetic oracle does NOT depend on a live detonation SUCCEEDING: in a unit
  test `detonate_oracle` fail-closes to False; the oracle asserts only that
  detonation is CONSULTED when (and only when) a valid contract names S, and that
  the no-contract / non-floor path still reports.

# Deliverables

A RED-PAIR plus the two re-author tasks the predicate change forces (see
`# Required plan shape` for WHY it is 4 tasks):

1. A test_authoring oracle `tests/harness/test_wire_up_gate_variant_report.py`
   that imports the REAL `_run_wire_up_gate` (normal import / importlib — NEVER
   exec/eval/__import__, AST-banned), drives it over hermetic synthetic git
   trees (reuse the accept-file idiom), arms `wire_up_runtime_gate` ON + enforce
   OFF via monkeypatch, and asserts on `state_dir/impl_progress.jsonl` rows. RED
   on HEAD (the composed predicate does not exist yet).

2. A harness_self_fix impl that, via a `__JANUSMASK_PATCHES__` SYMBOL patch,
   REPLACES the existing `_run_wire_up_gate` def in `harness/orchestrator.py`
   (no R-anchor needed — the symbol exists), adding the three new imports and
   the composed three-clause disjunction in place of the line-2323 predicate.

3. + 4. Two re-author test_authoring tasks (one per affected tracked file) that
   update the EXISTING wire-exempt assertions to the new CHECKED-exemption
   semantics (verbatim wire_exempt of a non-floor-reachable symbol is no longer
   suppressed). REQUIRED because the impl's vcmd runs ALL THREE test files
   together: the predicate change makes 3 committed wire-exempt assertions red,
   so they must be migrated to the new semantics IN THE SAME PLAN or they are
   left latently red in the committed tree. A single impl cannot edit multiple
   test files (a test_authoring task whole-file-authors exactly one file), so
   each affected file is its own task. Each re-author MUST emit the ENTIRE
   existing file verbatim and change ONLY the named wire-exempt assertions —
   every other test function preserved byte-for-byte (the worker receives the
   existing file as read-context in its inbox).

# Required plan shape

PLAN = 4 tasks (3 test_authoring + 1 harness_self_fix impl). The predicate's
clause-3 change (verbatim membership -> `validate_exemption('pure_helper', ...)`)
genuinely changes existing assertions in BOTH
`test_wire_up_runtime_gate_accept.py` AND `test_wire_up_runtime_gate_enforce.py`.
Those two files MUST be migrated to the new semantics in the SAME plan (else the
impl's all-three-files vcmd is red, or they sit latently red in the tree). A
test_authoring task whole-file-authors exactly one file, so each affected file
is its own task. SEQUENCING (critical): the impl lands LAST and DEPENDS ON all
three test tasks; the three test tasks have deps `[]` and each lands RED via
fix-forward red-pair acceptance (the impl is their in-plan sibling — its
`files_touched` is `harness/orchestrator.py` matching every test's dotted
`mutation_target`, and its vcmd string-contains every test's own file). When the
impl runs last it applies the predicate change against a HEAD that already holds
the migrated (new-semantics) tests and verifies all three GREEN together.

Tasks (IDs EXACT):

- `wireup-gate-variant-report-oracle` — meta_task_type `test_authoring`, deps
  `[]`, mutation_target `harness.orchestrator` (dotted), files
  `[tests/harness/test_wire_up_gate_variant_report.py]`. Canonical priority
  `P1`. vcmd: `python -m pytest tests/harness/test_wire_up_gate_variant_report.py -q`

- `wireup-gate-variant-report-impl` — meta_task_type `harness_self_fix`, deps
  `[wireup-gate-variant-report-oracle, wireup-gate-variant-report-reauthor-accept, wireup-gate-variant-report-reauthor-enforce]`,
  files `[harness/orchestrator.py]`. Canonical priority `P1`. LANDS LAST (after
  all three test tasks). A `__JANUSMASK_PATCHES__` SYMBOL patch replacing
  `_run_wire_up_gate` (adds 3 imports + the new disjunction; report/enforce
  branch body unchanged). vcmd MUST list ALL THREE test files (required so the
  red-pair scan accepts each red test task AND the impl verifies all three green
  together after the predicate change):
  `python -m pytest tests/harness/test_wire_up_gate_variant_report.py tests/harness/test_wire_up_runtime_gate_accept.py tests/harness/test_wire_up_runtime_gate_enforce.py -q`

- `wireup-gate-variant-report-reauthor-accept` — meta_task_type `test_authoring`,
  deps `[]`, mutation_target `harness.orchestrator` (dotted), files
  `[tests/harness/test_wire_up_runtime_gate_accept.py]`. Canonical priority `P1`.
  RED on HEAD (asserts new semantics the impl will deliver); lands via red-pair.
  Emit the ENTIRE existing file verbatim, preserving every other test function
  byte-for-byte, and change ONLY the wire-exempt assertions of
  `test_wire_exempt_suppresses_report_for_symbol_and_dataclass_constant` to the
  new checked-exemption semantics (a verbatim `wire_exempt` symbol that is NOT
  floor-reachable now STILL reports; suppression now requires the symbol to pass
  the pure_helper floor — add a floor-reachable fixture, or assert the verbatim
  non-floor symbol reports). vcmd:
  `python -m pytest tests/harness/test_wire_up_runtime_gate_accept.py -q`

- `wireup-gate-variant-report-reauthor-enforce` — meta_task_type
  `test_authoring`, deps `[]`, mutation_target `harness.orchestrator` (dotted),
  files `[tests/harness/test_wire_up_runtime_gate_enforce.py]`. Canonical
  priority `P1`. RED on HEAD (asserts new semantics the impl will deliver); lands
  via red-pair. Emit the ENTIRE existing file verbatim, preserving every other
  test function byte-for-byte, and change ONLY the wire-exempt assertions of
  `test_enforce_on_wire_exempt_symbol_proceeds_no_reject_row` and
  `test_enforce_on_wire_exempt_dataclass_constant_proceeds` to the new
  checked-exemption semantics (a verbatim `wire_exempt` function symbol that is
  NOT floor-reachable now rejects under enforce; suppression requires it to pass
  the pure_helper floor). vcmd:
  `python -m pytest tests/harness/test_wire_up_runtime_gate_enforce.py -q`

EXACTLY ONE implementation/harness_self_fix task (the impl); the other three are
test_authoring (so the paired oracle is not dropped). Slug
`wireup_gate_variant_report`.

PLANNER NOTE — integration-test excuse is MANDATORY on EVERY task (this is what
the plan validator checks, and it checks each TASK's `spec.non_goals`, NOT this
brief's `# Non-Goals` section): every task in this plan is a hermetic unit-level
change (a `_run_wire_up_gate` behavioral oracle, a harness symbol patch, or a
unit-test re-author) that NEVER drives the full pipeline. Therefore EVERY task's
`spec.non_goals` array MUST include at least one entry containing the literal
word `integration`, e.g. `"No integration test: unit-level wire-up-gate oracle /
harness symbol patch, never spawns an agent or drives the pipeline"`. A task that
omits an `integration`-bearing `spec.non_goals` entry AND declares zero
`test_spec.integration_tests` is rejected with `missing_integration_test`. Do not
add real integration_tests; use the excuse on all four tasks.

## Oracle assertions (6, all under `wire_up_runtime_gate` ON + enforce OFF)

1. A FLOOR-reachable new callable (built in a fixture where the symbol is
   statically reachable from a LIVE_ROOT) -> NO `orphan_symbol_unwired` report
   row (the FLOOR clause suppresses — the net-new behavior).
2. A NON-floor-reachable new callable with NO contract -> a `phase=='report'`,
   `event=='orphan_symbol_unwired'` row naming it; gate returns False; no
   rollback (staging tip sha unchanged).
3. A `wire_exempt` claim on a symbol that FAILS the floor -> STILL reported
   (proves `validate_exemption('pure_helper', ...)` is wired, not verbatim
   membership).
4. A `wire_exempt` claim on a symbol that PASSES the floor (floor-reachable
   fixture) -> suppressed (no report row).
5. PROPERTY: across the firing cases, under runtime-gate ON + enforce OFF the
   gate NEVER returns True and NEVER rolls back (tip unchanged, no rejected /
   task_blocked row).
6. BOTH knobs OFF -> strict no-op: no rows written for the task, returns False,
   tip unchanged.

(Detonation is asserted indirectly per Non-Goals: assert clause-2 is consulted
ONLY when a structurally valid contract names S — e.g. a no-contract or
self-cert case still reports — and that the hermetic detonation fail-closing to
False does not change the report-only outcome.)

## Impl patch scope

ONE `__JANUSMASK_PATCHES__` SYMBOL patch on `harness/orchestrator.py` replacing
the `_run_wire_up_gate` def: add `from harness.wire_up import
symbol_reachable_from_live_root, detonate_oracle, validate_exemption` (alongside
the existing imports), then replace the line-2323 `uncovered = sorted(...)`
predicate with the three-clause disjunction (FLOOR first; detonation only when a
valid contract names S, reading the oracle source defensively from
`staging_path/<runtime_oracle>` and fail-closing to False; exemption via
`validate_exemption('pure_helper', S, rel, staging_path).honored`). The
surrounding `try/except`, the report/enforce branch (2324-2339), `repo_root`,
`new_syms`, `_contract_valid`, and all knob gating are PRESERVED verbatim. No
config edit, no enforce flip.

Keep patches minimal and the predicate described in prose + the disjunction
sketch above — do not paste full primitive bodies.
