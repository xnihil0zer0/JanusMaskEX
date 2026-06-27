# Phase-III reachability cascade — dispatch sequencing

11 dispatched leaves + 1 hand-authored driver, built the NGv2 way (small,
rules-as-data, injected seams, live-path oracles). All reference impls + oracles
are validated in a scratch run BEFORE dispatch (see `VALIDATION.md`): **61 new
oracles green; 160 existing UNION oracles green against the edited modules; 0 new
regressions** in the full NGv2 suite (45 fail / 1434 pass / 14 collect-errors are
identical baseline vs edited — all pre-existing in-flight Phase-I/II work).

## Owner gate
**Epic B (CodeQL) requires the owner's CodeQL-license sign-off — GRANTED 2026-06-12.**
The `codeql_preflight` leaf (L0) encodes that condition as a FAIL-CLOSED runtime
gate (GitHub-hosted + OSI-licensed) and sequences FIRST. Epics A and C have no
license dependency.

## Dependency-ordered dispatch list

| # | task_id | leaf | kind | brief | oracle (commit to NGv2 master FIRST) | tests | brief-deps |
|---|---------|------|------|-------|--------------------------------------|-------|------------|
| 1 | `ngv2_codeql_preflight` | L0 license gate | NEW data_model | brief_L0_codeql_preflight.md | tests/ngv2/test_codeql_preflight_wired.py | 10 | [] |
| 2 | `ngv2_sink_classes_data` | A1 rules-as-data | NEW data_model | brief_A1_sink_classes_data.md | tests/ngv2/test_sink_classes_data_wired.py | 3 | [] |
| 3 | `ngv2_entrypoint_sigs_data` | A2 rules-as-data (G6) | NEW data_model | brief_A2_entrypoint_sigs_data.md | tests/ngv2/test_entrypoint_sigs_data_wired.py | 3 | [] |
| 4 | `ngv2_entrypoint_scan` | A3 entry-point scan (revives web_framework_detect) | NEW data_model | brief_A3_entrypoint_scan.md | tests/ngv2/test_entrypoint_scan_wired.py | 8 | [ngv2_entrypoint_sigs_data] |
| 5 | `ngv2_source_sink_prefilter` | A4 source×sink gate (revives deser_detect) | NEW data_model | brief_A4_source_sink_prefilter.md | tests/ngv2/test_source_sink_prefilter_wired.py | 7 | [ngv2_entrypoint_scan, ngv2_sink_classes_data] |
| 6 | `ngv2_codeql_runner_subprocess_factory` | B1 real runner factory | EDIT io_adapter | brief_B1_codeql_runner_subprocess_factory.md | tests/ngv2/test_codeql_runner_subprocess_factory_wired.py | 4 | [ngv2_codeql_preflight] |
| 7 | `ngv2_codeql_orchestrate` | B2 CodeQL Stage-2 glue | NEW data_model | brief_B2_codeql_orchestrate.md | tests/ngv2/test_codeql_orchestrate_wired.py | 3 | [ngv2_codeql_runner_subprocess_factory, ngv2_codeql_preflight] |
| 8 | `ngv2_taint_path_signal` | B3 finding→proof adapter | NEW data_model | brief_B3_taint_path_signal.md | tests/ngv2/test_taint_path_signal_wired.py | 5 | [] |
| 9 | `ngv2_confidence_signals_taint_merge` | B4 confidence merge | EDIT state_machine | brief_B4_confidence_signals_taint_merge.md | tests/ngv2/test_confidence_signals_taint_merge_wired.py | 5 | [ngv2_taint_path_signal] |
| 10 | `ngv2_reachability_triage` | C1 LLM scope/auth judge | NEW data_model | brief_C1_reachability_triage.md | tests/ngv2/test_reachability_triage_wired.py | 8 | [] |
| 11 | `ngv2_session_gate_reachability_triage` | C2 gate consult (live wiring) | EDIT state_machine | brief_C2_session_gate_reachability_triage.md | tests/ngv2/test_session_gate_reachability_triage_wired.py | 5 | [ngv2_reachability_triage] |
| — | `ngv2_drive_reachability` | D1 live driver | HAND-AUTHORED (smoke) | brief_D1_drive_reachability.md | (none — driver) | smoke | [5,7,8,11,6] |

Total dispatched-oracle tests: **61** (10+3+3+8+7+4+3+5+5+8+5).

## Topological dispatch order & parallelism
```
L0 codeql_preflight ──────────────┐ (owner license condition, encoded; FIRST)
Epic A:  A1 ─┐                     │
         A2 ─┤→ A3 ─→ A4           │  (A1/A2 parallel; A3 needs A2; A4 needs A3+A1)
Epic C:  C1 ─→ C2                  │  (parallel with A; no license dep)
Epic B:  B1 ─→ B2 ; B3 ─→ B4       │  (B1 needs L0; B2 needs B1; B4 needs B3)
                                   ▼
Epic D:  D1 driver  (after A4, B2, B3, B4(via gate), C2, B1)
```
- L0 + Epic A + Epic C are license-free → may dispatch immediately; A1/A2 in
  parallel, C1 in parallel with A.
- Epic B's B1 lists `ngv2_codeql_preflight` as a brief-dep purely to ORDER it
  after the license gate lands (no import edge); B2 then depends on B1 + L0.
- **AUTO-SERIALIZE:** every leaf resolves `working_dir` =
  `/home/xnihil0zer0/NobleGreedv2`, which is in `_ISOLATED_EXTERNAL_DIRS`
  (`harness/autowork_parallelism.py`, `4a80a0d`). `can_run_parallel` is False for
  two tasks in the same isolated external root, so the daemon serialises them at
  runtime regardless of queue order. The brief-level slug `dependencies:` (the
  daemon honors them) enforce the cross-leaf ordering above; do NOT try to force
  parallelism.

## Per-leaf procedure (do for EACH leaf, in order)
1. **Commit the RED oracle to NGv2 master FIRST.** Copy
   `_phase_prep/phase3/build/oracles/<oracle>.py` →
   `/home/xnihil0zer0/NobleGreedv2/tests/ngv2/<oracle>.py` and
   `git -C /home/xnihil0zer0/NobleGreedv2 add + commit` BEFORE dispatch. The blind
   worker runs the committed oracle from the working tree; an uncommitted oracle
   is invisible to the accept gate and an untracked test can poison the patches
   commit (memory `untracked-test-poisons-patches-commit`). The oracle is RED at
   commit time — expected; it goes GREEN when the leaf lands. **Also commit the
   two data files' consumers' fixtures? No** — the data leaves (A1/A2) land the
   JSON under `data/ngv2/reachability_rules/`; their oracles locate that dir via
   the `ngv2` package parent, so no path edit is needed.
2. **Dispatch** with the brief's `# Required plan shape` honored VERBATIM (exact
   task_id, working_dir, single `files_touched`, the full pinned source copied
   into `implementation_notes`).
3. **Verify GREEN** via the brief's `verification_command`. For EDIT leaves the
   command runs the UNION (new oracle + the existing oracles touching the edited
   module) — anti-seesaw.
4. **Confirm NGv2 master fast-forwarded** before the next leaf (runtime
   serialisation already enforces this; verify the integrate landed:
   `python3 -m pytest -q tests/ngv2`).

## Expected RED reasons at oracle-commit time
- L0/A3/A4/B2/B3/C1: `ModuleNotFoundError: No module named 'ngv2.<mod>'` (module absent).
- A1/A2: `FileNotFoundError` / `KeyError` on the JSON (data file absent).
- B1: `ImportError: cannot import name 'make_subprocess_runner'` (factory absent).
- B4: `TypeError: build_confidence_signals() got an unexpected keyword argument 'taint_proofs'`.
- C2: `AssertionError` on the new bands (no triage consult / helper absent), edge import error.

## Wiring / un-suppression leaves (what makes the cascade actually RUN live)
Per the standing "implementation ≠ wired" rule, these leaves carry live-path
oracles that un-orphan the revived modules and put the cascade on the hunt path:
- **A3 + A4** revive `web_framework_detect` (A3 imports `detect_frameworks`) and
  `deser_detect` (A4 imports `check_deserialization`) — their oracles assert the
  modules appear in `sys.modules` after the live call.
- **B1 + B2** revive `codeql_runner` (real factory) + `taint_spec_library`
  (loaded by orchestrate) onto the live CodeQL path.
- **B4** is the single production seam that lets a CodeQL taint proof reach the
  ADMIT band via `resolve_signals` (live FSM-gate path oracle).
- **C2** is the live FSM wiring: the `('triage','verify')` gate consults the
  triage band — oracle asserts the edge is registered and reachable via
  `gate_transition`.
- **D1** (hand-authored) is the corpus driver that runs all of the above on the
  live hunt path and hands ADMIT candidates (with source→sink path) to the
  existing PoC writer / bwrap detonator.

## After all leaves land (D2 regression sweep — OUT OF SCOPE for the leaves)
Full NGv2 suite green AND assert the four revived modules each have ≥1 non-test
importer (kills the orphan-revival regression): `deser_detect` (← prefilter),
`web_framework_detect` (← entrypoint_scan), `codeql_runner` (← orchestrate/driver),
`taint_spec_library` (← orchestrate). This is the BUILD_PLAN D2 acceptance check.

## Note on the two pending Phase-II detectors
`ngv2.ssrf_detect` / `ngv2.pathtrav_detect` (Phase-II briefs, not yet landed) are
NOT prerequisites here: `source_sink_prefilter` sources its sink view from the
already-shipped `deser_detect` + `pattern_scanner`. If those detectors land
later, the prefilter's `collect_sinks` can be extended in a follow-up — out of
scope for this build.
