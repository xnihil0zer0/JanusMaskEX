# Phase-III BUILD package — reachability cascade (dispatch-ready)

Turns the approved `_phase_prep/phase3/{DECISION.md,BUILD_PLAN.md}` design into a
dispatch-ready build package, mirroring the Phase-II output shape. Closes the
"37 param-derived sinks, 0 claimable" structural gap with a three-stage cascade:
**source×sink prefilter (c) → CodeQL interprocedural taint prover (a) → LLM
scope/auth triage (b)**, gated by a FAIL-CLOSED CodeQL license preflight, and
folding in Phase-IV Gap **G6** (MFF model-file loaders as attacker boundaries).

## Layout
```
build/
├── README.md            ← this file
├── SEQUENCING.md        ← dependency-ordered dispatch list, oracle-commit timing,
│                          expected RED reasons, the live-wiring/un-suppression leaves
├── VALIDATION.md        ← 61 new + 160 UNION oracles green; 0 regressions; how to reproduce
├── research/
│   ├── codeql_host_capability.md   ← codeql 2.25.1 verified (read-only, no DB built)
│   └── cascade_design_and_g6.md    ← design + audited NGv2 seams + G6 folding
├── _reference/          ← byte-exact validated impls (embedded into the briefs)
│   ├── ngv2/  codeql_preflight.py · entrypoint_scan.py · source_sink_prefilter.py
│   │          taint_path_signal.py · codeql_orchestrate.py · reachability_triage.py
│   │          codeql_runner.EDITED.py · confidence_signals.EDITED.py · session_gate.EDITED.py
│   ├── data/ngv2/reachability_rules/  sink_classes.json · entrypoint_sigs.json
│   └── _e2e_run/  drive_reachability.py   (hand-authored driver skeleton)
├── oracles/             ← 11 committed-RED oracle files (commit to NGv2 master FIRST)
└── briefs/              ← 12 dispatch-ready briefs (11 leaves + D1 driver)
```

## The leaves (dispatch order — full table in SEQUENCING.md)
1. `ngv2_codeql_preflight` — FAIL-CLOSED license/host gate (owner condition, FIRST)
2. `ngv2_sink_classes_data` — rules-as-data sink catalog (CWE-22/78/94/502/918)
3. `ngv2_entrypoint_sigs_data` — rules-as-data entry-point catalog (+ G6 MFF boundary)
4. `ngv2_entrypoint_scan` — Stage-1 entry-point scan (revives web_framework_detect)
5. `ngv2_source_sink_prefilter` — Stage-1 source×sink gate (revives deser_detect; G6 mode)
6. `ngv2_codeql_runner_subprocess_factory` — EDIT: real subprocess runner factory
7. `ngv2_codeql_orchestrate` — Stage-2 CodeQL glue (token-gated, DB-cached, dedup)
8. `ngv2_taint_path_signal` — CodeQL finding → taint_flow proof
9. `ngv2_confidence_signals_taint_merge` — EDIT: fold taint proofs into ADMIT band
10. `ngv2_reachability_triage` — Stage-3 LLM scope/auth judge (ADMIT/MANUAL/DROP)
11. `ngv2_session_gate_reachability_triage` — EDIT: live (triage→verify) gate consult
- `ngv2_drive_reachability` — HAND-AUTHORED live driver (smoke-only; not blind-dispatched)

## Mandatory design elements — where each lives
- **License preflight (owner condition), FIRST:** leaf L0 `codeql_preflight`;
  every CodeQL path requires its `verify_pass_token` (enforced in `codeql_orchestrate`).
- **Orphan-revival wiring as EDIT/live-path leaves:** B1 (codeql_runner) and B4/C2
  carry the literal word "integration" in `# Non-Goals` and live-path oracles;
  web_framework_detect/deser_detect revived via A3/A4 live-path oracles; every
  EDIT brief pins the anti-seesaw UNION it must keep green.
- **Small, rules-as-data, byte-exact, pre-validated:** all NEW modules are single
  files; sink/entry-point/sink-class tables are JSON; each impl was run against
  its oracle before the brief was written (VALIDATION.md).
- **Brief shape:** frontmatter `interfaces:` + slug `dependencies:` + `meta_task_type`
  + `spec_author`/`spec_reviewed_by`; five sections (Title/Scope/Non-Goals/Inputs/
  Deliverables) + a `# Required plan shape` pinning task_id VERBATIM, working_dir,
  single `files_touched`, CWD-relative verification_command (no `cd`), ≥2 named
  regression cases, ≥2 edge cases, and an integration-style case (NEW modules) /
  "integration" Non-Goal excuse (EDIT modules).
- **G6:** folded into the Stage-1 (c) design — see research/cascade_design_and_g6.md §G6.

## Before dispatch
Commit each oracle in `oracles/` to NGv2 master (`tests/ngv2/`) FIRST (RED),
THEN dispatch its leaf — per-leaf procedure in SEQUENCING.md. Epic B is unblocked
by the owner's CodeQL-license sign-off (granted 2026-06-12), encoded as the L0
runtime gate.
