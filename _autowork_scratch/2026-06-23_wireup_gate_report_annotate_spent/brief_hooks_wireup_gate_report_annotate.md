---
working_dir: "/home/xnihil0zer0/JanusMaskJR"
priority: high
operator_decision_required: true
auto_approve_requested: true
required_task_ids:
  - wireup-gate-annotate-oracle
  - wireup-gate-annotate-impl
interfaces: >
  REPORT-ONLY, ADDITIVE wiring of the three landed harness/wire_up.py detonation
  primitives into the live wire-up gate (`_run_wire_up_gate`,
  harness/orchestrator.py:2241). This is brief #7 of an owner-confirmed
  REPORT-ONLY program: it gathers the false-positive soak data the program needs
  WITHOUT changing any suppress decision. The actual suppress-swap and the
  enforce flip are deferred to the later owner-gated enforce-flip brief; the
  `wire_up_runtime_gate_enforce` knob is NOT touched here.

  DESIGN (additive, never a behavior change). KEEP the existing
  `_run_wire_up_gate` `uncovered`/suppress predicate (`:2300-2323`), the existing
  `orphan_symbol_unwired` report/enforce branch (`:2324-2339`), the rollback
  path, and the gate's return value EXACTLY as-is -- the verbatim `wire_exempt`
  membership and the `_contract_valid` logic are UNCHANGED, so NO existing test
  is touched or re-authored. ALONGSIDE that, ADD a NEW per-symbol VERDICT
  computation that runs the three primitives for each new top-level callable in
  the already-computed `new_syms` set (`:2300`/`:2323`) and LOGS the verdict as a
  NEW, separate report event (`event=='wireup_symbol_verdict'`). The block runs
  ONLY when `wire_up_runtime_gate` is ON, is wrapped defensively so it can never
  raise out of the gate, and NEVER reads or writes the `uncovered` set, the
  `orphan_symbol_unwired` row, the rollback, or the return value.

  PRIMITIVES (all confirmed in harness/wire_up.py; NOT yet imported in
  orchestrator.py -- the impl adds exactly these 3 imports): FLOOR
  `symbol_reachable_from_live_root(repo_root, module_rel, symbol, *,
  roots=LIVE_ROOTS) -> bool` (:689); RUNNER
  `detonate_oracle(oracle_source, symbols, live_root_files, *, repo_root,
  jailed=True) -> dict[str,bool]` (:572 -- builds its own jail, fail-closed,
  never raises); EXEMPT
  `validate_exemption(category, symbol, module_rel, repo_root, *,
  roots=LIVE_ROOTS) -> ExemptionVerdict(honored, requires_recheck, reason)`
  (:667). `LIVE_ROOTS` and `new_top_level_callables` are ALREADY imported at
  orchestrator.py:2175.

  TRUST-CORE: `harness/orchestrator.py` IS in `_NEVER_AUTO_APPROVE`
  (orchestrator.py:2545), so the IMPL task REQUIRES an operator decision file
  `state/control/decisions/wireup-gate-annotate-impl.json` even under
  auto-approve; `operator_decision_required: true` and
  `auto_approve_requested: true` are set in this frontmatter. The ORACLE task
  edits only `tests/**`, needs no decision file.
---

# Title

`_run_wire_up_gate` (harness/orchestrator.py:2241): ADDITIVELY emit a report-only `wireup_symbol_verdict` event per new top-level callable -- running the three landed wire_up primitives (floor / detonation / exemption) -- WITHOUT changing the existing `uncovered`/suppress logic, the `orphan_symbol_unwired` row, the rollback path, or the gate's return value

# Scope

EDIT the SINGLE EXISTING production file `harness/orchestrator.py` (READ it
first). Replace EXACTLY ONE top-level symbol: `_run_wire_up_gate`
(`harness/orchestrator.py:2241`) via a `__JANUSMASK_PATCHES__` payload with a
SINGLE `kind:'symbol'` patch keyed on `_run_wire_up_gate` (the function is
TOP-LEVEL -> a direct symbol patch is fine, NOT nested, no R-anchor needed). The
patch ADDS three imports (`symbol_reachable_from_live_root`, `detonate_oracle`,
`validate_exemption` from `harness.wire_up`) and ADDS one new report-only verdict
block inside the existing `if _wire_up_runtime_gate_enabled(state_dir):` branch.
It LEAVES the existing `uncovered`/suppress criterion (`:2300-2323`), the
`orphan_symbol_unwired` report/enforce branch (`:2324-2339`), the module-level
`orphan_unwired` gate (`:2343-2354`), the rollback path, and the return value
BYTE-IDENTICAL in behavior. Touch NO other production file and NO other symbol.
This is a sensitive `harness/**` trust-core write (`harness/orchestrator.py` is
in `_NEVER_AUTO_APPROVE`, orchestrator.py:2545), so the IMPL task is
`harness_self_fix` and REQUIRES an operator decision file; `config/config.yaml`
is NOT edited.

# Inputs

READ `harness/orchestrator.py`. VERIFIED current behavior of `_run_wire_up_gate`
(`:2241-2355`):

- It iterates `files_touched`; skips non-`.py`, anything under a `tests/` dir,
  and `test_`/`_test.py` basenames. For an ALREADY-TRACKED `.py` module
  (`_tracked_in_parent(rel)` is True), when `_wire_up_runtime_gate_enabled(...)`
  is on, it runs a contained `try/except` block (`:2290-2341`):
  - reads `parent_src` (`git show HEAD:<rel>` in `worktree_root`) and
    `child_src` (`staging_path/<rel>` on disk),
  - computes `new_syms = new_top_level_callables(parent_src, child_src)`
    (`:2300`),
  - reads `task['constraints']['integration_contract']` (`_entrypoints`,
    `_csymbols`, `_oracle`) and computes
    `_contract_valid = bool(_entrypoints) and all(ep in _live for ep in
    _entrypoints) and bool(_oracle)` (`:2305-2317`),
  - reads `_exempt` from `task['wire_exempt']` or
    `task['constraints']['wire_exempt']` (a flat list of bare names,
    `:2318-2322`),
  - computes `uncovered = sorted(s for s in new_syms if s not in _exempt and
    not (_contract_valid and s in _csymbols))` (`:2323`),
  - and if `uncovered`: when `_wire_up_runtime_gate_enforce_enabled(...)` is on,
    rolls back + writes a `phase=='rejected'`, `event=='orphan_symbol_unwired'`
    row + blocks + returns True (`:2325-2334`); otherwise writes ONE
    `phase=='report'`, `event=='orphan_symbol_unwired'` row and continues
    (`:2335-2339`).
- The module-level `orphan_unwired` gate (`:2343-2354`) is on the NEW-module
  branch (`_tracked_in_parent` False) and is OUT OF SCOPE here. The gate returns
  False at `:2355` for the accept path.

VERIFIED the three primitives in `harness/wire_up.py` (their signatures /
fail-closed contracts are quoted in `interfaces` above and MUST NOT be
re-implemented): `symbol_reachable_from_live_root` (`:689`, pure, returns bool,
fail-soft, sound in the no-false-orphan direction);
`detonate_oracle` (`:572`, jailed by default, returns `dict[str,bool]`,
FAIL-CLOSED to all-False on any non-zero exit / timeout / parse error and NEVER
raises); `validate_exemption` (`:667`, pure, composes the floor, returns
`ExemptionVerdict(honored, requires_recheck, reason)` -- a flat `wire_exempt`
entry maps to category `'pure_helper'`, and `pure_helper`/`config_reader`/
`data_only` are `honored` ONLY when the symbol passes the floor;
`staged_sibling` only DEFERS; unknown categories are rejected).

VERIFIED `LIVE_ROOTS` and `new_top_level_callables` are ALREADY imported at
`orchestrator.py:2175` (`from harness.wire_up import new_top_level_callables,
LIVE_ROOTS`) -- so the impl ADDS only the three new names; it does NOT re-import
the existing two.

VERIFIED the ledger row schema (the existing `orphan_symbol_unwired` report row,
`:2337`) is written via `write_jsonl_row(state_dir / 'impl_progress.jsonl',
{...})` with `ts`, `phase`, `task_id`, `event`, `commit_sha`, `file`, `symbols`,
`reason` fields. The new verdict event MUST reuse that same writer + state-dir
path and a `phase=='report'` row, with a DISTINCT `event=='wireup_symbol_verdict'`
so it never collides with `orphan_symbol_unwired` rows.

VERIFIED the test idiom to REUSE: `tests/harness/test_wire_up_runtime_gate_accept.py`
provides hermetic synthetic-git-tree helpers `_build_tree(root, parent_src,
child_src, rel=...)` (parent repo + sibling staging worktree, returns
`(state_dir, repo, staging, sha)`), `_arm(monkeypatch, on)` (monkeypatches
`orchestrator._wire_up_runtime_gate_enabled`, `raising=False`), `_task(task_id,
*, integration_contract=, wire_exempt=, top_wire_exempt=)`, `_drive(task,
state_dir, repo, staging, sha, task_id)` (calls the REAL `_run_wire_up_gate` and
reads back `(returned, rows, head)`), and `_read_rows(state_dir)`.

VERIFIED the validator gates the synthesized plan must satisfy (`harness/planner/
plan_validator.py`): `missing_integration_test` (`:250-256`) excuses an empty
`integration_tests` list ONLY when some `spec.non_goals` entry lowercased
contains the substring `integration`; `missing_edge_case_tests` (`:257-263`,
`needed = min(2, len(edge_cases))`) fires only on NON-`test_authoring` tasks
(under `if not is_test:`) and requires
`len(property_tests) + len(regression_tests) >= needed`.

VERIFIED trust-core gating: `harness/orchestrator.py` IS in `_NEVER_AUTO_APPROVE`
(`orchestrator.py:2545`). The IMPL task REQUIRES an operator decision file
`state/control/decisions/wireup-gate-annotate-impl.json` EVEN under auto-approve;
`operator_decision_required: true` and `auto_approve_requested: true` are set in
this brief's frontmatter.

# Non-Goals

Integration testing is out of scope for BOTH tasks in this plan. This is a
unit-level wire-up-gate annotation: the oracle drives the REAL `_run_wire_up_gate`
over a hermetic synthetic git tree (it never drives the full pipeline, spawns an
agent, or hits a real LIVE_ROOT inline), and the impl is a single in-place harness
symbol patch with NO new runtime/integration surface -- so an integration test is
not meaningful and the integration-test requirement is EXCUSED. For BOTH tasks in
this plan, the synthesized `spec.non_goals` array MUST contain at least one
verbatim entry that includes the literal word `integration` (e.g. "No integration
test: unit-level wire-up-gate oracle / harness symbol patch, never drives the
pipeline -- no new integration surface"); this is the exact token the
`missing_integration_test` validator gate scans for to excuse the empty
`integration_tests` list. Do NOT add real `integration_tests`.

HARD NEGATIVES (the new block is STRICTLY ADDITIVE, report-only): do NOT change,
weaken, reorder, or read-into the existing `uncovered` set, the `_contract_valid`
computation, the `_exempt` membership, the `orphan_symbol_unwired` report/enforce
branch (`:2324-2339`), the rollback path (`_rollback_rejected_commit`), the
`_mark_blocked` call, the module-level `orphan_unwired` gate (`:2343-2354`), or
the gate's return value. Do NOT touch `_wire_up_runtime_gate_enforce_enabled` or
the `wire_up_runtime_gate_enforce` knob. Do NOT edit `config/config.yaml`. Do NOT
re-implement reachability, detonation, or exemption -- COMPOSE the three named
primitives verbatim. Do NOT run a live detonation in the hermetic oracle (per the
program Non-Goal, `detonate_oracle` fail-closes to False there). Do NOT use
`exec`/`eval`/`compile`/`__import__` anywhere (AST-banned,
`harness/ast_enforcer.py`). Do NOT edit any other file, create a new module, or
author tests beyond the one paired oracle. The new block must run ONLY when
`wire_up_runtime_gate` is ON; with both knobs OFF the gate stays byte-identical to
today.

# Deliverables

`harness/orchestrator.py` such that `_run_wire_up_gate`, inside the EXISTING
`if _wire_up_runtime_gate_enabled(state_dir):` branch (after `new_syms` /
`_constraints` / `_contract` / `_exempt` are computed, and AFTER the existing
`orphan_symbol_unwired` report/enforce handling so the existing path is
untouched), ADDITIVELY:

- For EACH `S` in `new_syms`, computes a per-symbol verdict (all reads DEFENSIVE,
  wrapped so a failure on one symbol never aborts the loop or the gate):
  - `floor_reachable` = `symbol_reachable_from_live_root(staging_path, rel, S)`
    (bool).
  - `contract_detonated` = True ONLY when a structurally valid contract names `S`
    (`_contract_valid and S in _csymbols`) AND `detonate_oracle(...)[S]` is True.
    Detonation is CONSULTED ONLY when a valid contract names `S`; the oracle
    source is read DEFENSIVELY from `staging_path / <_contract['runtime_oracle']>`
    and ANY read/parse/run error (or no valid contract) fail-closes
    `contract_detonated` to False. `live_root_files` passed to `detonate_oracle`
    is the contract `_entrypoints` (already verified ⊆ `LIVE_ROOTS`).
  - `exempt_honored` = `validate_exemption('pure_helper', S, rel,
    staging_path).honored` (a flat `wire_exempt` entry defaults to category
    `pure_helper`; `honored` is True only if `S` passes the floor). Compute it
    for any `S` (the verdict records the would-be exemption status; it does NOT
    gate on `S in _exempt`).
  - `would_be_orphan` = `not floor_reachable and not contract_detonated and not
    exempt_honored` (the NEW-criterion false-positive signal).
- LOGS each symbol's verdict as a SEPARATE `phase=='report'`,
  `event=='wireup_symbol_verdict'` ledger row via the SAME
  `write_jsonl_row(state_dir / 'impl_progress.jsonl', {...})` writer, carrying at
  minimum: `ts`, `phase:'report'`, `task_id`, `event:'wireup_symbol_verdict'`,
  `commit_sha` (`result.get('sha')`), `file` (`rel`), `symbol` (`S`),
  `floor_reachable`, `contract_detonated`, `exempt_honored`, `would_be_orphan`.
  (`symbols`/`reason` may also be carried for parity, but the verdict event MUST
  be distinguishable from `orphan_symbol_unwired` by its `event` value.)
- Runs the whole verdict block ONLY when `wire_up_runtime_gate` is ON, inside the
  existing contained `try/except` so it can NEVER raise out of the gate, and
  NEVER mutates `uncovered`, the `orphan_symbol_unwired` row, the rollback path,
  or the return value. With both knobs OFF the block does not run.

The three new imports (`symbol_reachable_from_live_root`, `detonate_oracle`,
`validate_exemption` from `harness.wire_up`) are added; the existing
`new_top_level_callables` / `LIVE_ROOTS` import (`:2175`) is reused as-is.

Illustrative verdict sketch (adapt to the real surrounding block; do NOT paste
full bodies):

    # ADDITIVE report-only verdict -- runs alongside the UNCHANGED uncovered logic
    for _s in new_syms:
        try:
            _floor = bool(symbol_reachable_from_live_root(staging_path, rel, _s))
            _deto = False
            if _contract_valid and _s in _csymbols:
                try:
                    _osrc = (Path(staging_path) / _oracle).read_text(
                        encoding='utf-8', errors='ignore')
                    _deto = bool(detonate_oracle(
                        _osrc, [_s], list(_entrypoints),
                        repo_root=staging_path).get(_s, False))
                except Exception:
                    _deto = False
            _ex = bool(validate_exemption(
                'pure_helper', _s, rel, staging_path).honored)
            _orphan = (not _floor) and (not _deto) and (not _ex)
            write_jsonl_row(state_dir / 'impl_progress.jsonl', {
                'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                'phase': 'report', 'task_id': task_id,
                'event': 'wireup_symbol_verdict',
                'commit_sha': result.get('sha'), 'file': rel, 'symbol': _s,
                'floor_reachable': _floor, 'contract_detonated': _deto,
                'exempt_honored': _ex, 'would_be_orphan': _orphan})
        except Exception:
            pass  # report-only: a per-symbol verdict failure never breaks the gate

# Required plan shape

A clean 2-task RED-PAIR (the proven shape). Slug: `wireup_gate_report_annotate`.
EXACTLY ONE implementation task (the `harness_self_fix` impl).

★CRITICAL (this is what broke the prior attempt): the plan validator checks EACH
TASK's `spec.non_goals` for the literal word `integration`, NOT the brief
section. Therefore BOTH tasks' synthesized `spec.non_goals` arrays MUST EACH
include at least one entry containing the literal word `integration` (e.g. "No
integration test: unit-level wire-up-gate oracle / harness symbol patch, never
drives the pipeline -- no new integration surface"). Omitting this on EITHER task
trips `missing_integration_test` and FAILS validation. Do NOT add real
`integration_tests`.

## TASK 1 -- ORACLE (test_authoring), id: wireup-gate-annotate-oracle

- meta_task_type: test_authoring
- mutation_target: harness.orchestrator  (bare dotted MODULE only)
- files_touched: [tests/harness/test_wire_up_gate_verdict_annotation.py]
- dependencies: []
- priority: P1
- verification_command: python -m pytest tests/harness/test_wire_up_gate_verdict_annotation.py -q
- spec.non_goals MUST include a verbatim entry containing the literal word
  `integration` (see ★CRITICAL above).

Author `tests/harness/test_wire_up_gate_verdict_annotation.py` (new file, beside
`tests/harness/test_wire_up_runtime_gate_accept.py`). Import the REAL
`_run_wire_up_gate` (`from harness.orchestrator import _run_wire_up_gate`; normal
import / importlib -- NEVER `exec`/`eval`/`__import__`, AST-banned). REUSE the
helper idiom from `test_wire_up_runtime_gate_accept.py` (`_build_tree`, `_arm`,
`_task`, `_drive`, `_read_rows`); arm `wire_up_runtime_gate` ON + enforce OFF via
monkeypatch (`_arm(monkeypatch, True)` plus a separate
`monkeypatch.setattr(orchestrator, '_wire_up_runtime_gate_enforce_enabled',
lambda *a, **k: False, raising=False)`). Build hermetic synthetic git trees whose
child adds the relevant new top-level callable(s) and assert on
`impl_progress.jsonl` rows. RED on HEAD (the `wireup_symbol_verdict` event does
not exist yet). Add a helper to select verdict rows by `event ==
'wireup_symbol_verdict'` and `symbol == S`. The six assertions (all under
runtime-gate ON + enforce OFF unless noted):

1. A floor-reachable new callable (fixture where `S` IS statically reachable from
   a LIVE_ROOT) -> a `wireup_symbol_verdict` event with `floor_reachable: true`.
   (Forces `symbol_reachable_from_live_root` to be wired.)
2. A non-floor-reachable orphan, no contract, not exempt -> a verdict event with
   `would_be_orphan: true` (`floor_reachable` False, `contract_detonated` False,
   `exempt_honored` False).
3. A `wire_exempt` symbol that FAILS the floor -> a verdict event with
   `exempt_honored: false` (forces `validate_exemption` to be wired); AND the
   EXISTING `orphan_symbol_unwired` behavior for that SAME input is UNCHANGED vs
   current code -- the verbatim `wire_exempt` still suppresses the existing
   orphan row (no `orphan_symbol_unwired` row for that symbol). This is the key
   assertion proving the new logic is ADDITIVE, not a behavior change.
4. A `wire_exempt` symbol that PASSES the floor -> a verdict event with
   `exempt_honored: true`.
5. PROPERTY: under runtime-gate ON + enforce OFF, the gate NEVER returns True and
   NEVER rolls back (staging tip unchanged, no `rejected`/`blocked` row) for ANY
   of the above verdict fixtures.
6. BOTH knobs OFF -> strict no-op: NO `wireup_symbol_verdict` events, NO
   `orphan_symbol_unwired` rows, returns False, staging tip unchanged
   (byte-identical to today).

DETONATION (per the program's accepted Non-Goal): the hermetic test cannot run a
live detonation, so `detonate_oracle` fail-closes to False. Assert only that
`contract_detonated` is False when there is NO valid contract naming `S`, and (in
a valid-contract fixture) that the verdict CONSULTS detonation (i.e. the verdict
event is still emitted and `contract_detonated` is a bool, fail-closed to False);
do NOT depend on a live detonation succeeding. Keep the oracle hermetic and
offline. Do NOT import or run the broad adversarial suite.

## TASK 2 -- IMPL (harness_self_fix), id: wireup-gate-annotate-impl

- meta_task_type: harness_self_fix
- mutation_target: harness.orchestrator  (bare dotted MODULE only)
- files_touched: [harness/orchestrator.py]
- dependencies: [wireup-gate-annotate-oracle]
- priority: P1
- verification_command: python -m pytest tests/harness/test_wire_up_gate_verdict_annotation.py -q
- REQUIRES an operator decision file
  `state/control/decisions/wireup-gate-annotate-impl.json` even under
  auto-approve, because `harness/orchestrator.py` is in `_NEVER_AUTO_APPROVE`
  (orchestrator.py:2545); `operator_decision_required: true` and
  `auto_approve_requested: true` are set in this brief's frontmatter.
- spec.non_goals MUST include a verbatim entry containing the literal word
  `integration` (see ★CRITICAL above). This is REQUIRED: `integration_tests` is
  empty for this in-place harness edit, and `missing_integration_test`
  (plan_validator.py:250-256) only excuses the empty list when some
  `spec.non_goals` entry lowercased contains the substring `integration`.
- spec.test_spec MUST cover the declared edge cases with concrete regression
  tests. `missing_edge_case_tests` (plan_validator.py:257-263,
  `needed = min(2, len(edge_cases))`) fires on this NON-`test_authoring` task and
  FAILS the plan unless `len(property_tests) + len(regression_tests) >= needed`.
  The verdict block branches on real edge cases -- (a) a new callable that PASSES
  the floor vs (b) a non-reachable orphan with no contract/exemption -- so the
  synthesized `test_spec.regression_tests` MUST carry at least one concrete
  regression test per declared edge case (at minimum `min(2, len(edge_cases))`
  total across `regression_tests` + `property_tests`), e.g.:
  - `test_floor_reachable_symbol_emits_verdict` -- a floor-reachable new callable
    yields a `wireup_symbol_verdict` row with `floor_reachable: true`.
  - `test_orphan_symbol_verdict_would_be_orphan` -- a non-reachable, no-contract,
    non-exempt new callable yields `would_be_orphan: true`, the existing
    `orphan_symbol_unwired` path is UNCHANGED, and the gate still returns False
    with no rollback.
  These are genuine coverage of the verdict block's real branches, NOT a
  validation workaround.

Implement the additive report-only verdict block in `_run_wire_up_gate` exactly
as the Deliverables / Inputs specify, via a single `__JANUSMASK_PATCHES__`
`kind:'symbol'` patch keyed on `_run_wire_up_gate` (top-level symbol -> direct
symbol patch, no R-anchor / no nesting), ADDING the three `harness.wire_up`
imports and the verdict block. The existing `uncovered`/suppress criterion, the
`orphan_symbol_unwired` report/enforce branch, the rollback path, and the return
value MUST stay byte-identical in behavior. The `verification_command`
substring-contains the oracle test path, so this is a fix-forward redpair and the
impl is verified by the oracle's OWN authored file. Do NOT use the broad
adversarial suite (it is non-hermetic and flakes in the staging worktree, which
would wrongly block the `harness_self_fix` jail gate).
