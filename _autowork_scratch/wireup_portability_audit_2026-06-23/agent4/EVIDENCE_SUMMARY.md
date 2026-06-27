# Agent 4 — Structural reconciliation evidence (2026-06-23)

Repos: JM HEAD fc8167a · NGv2 HEAD ed91619 (both match the brief).

## E1 — README "entrypoints as extra live roots" is IMPRECISE (s2_floor_roots_probe.py)
- README line 200: "the **wire-up gate** reads `entrypoints` as extra live roots".
- Code (orchestrator._run_wire_up_gate, fc8167a):
  - floor call = `symbol_reachable_from_live_root(staging_path, rel, _vsym)` — NO `roots=` arg → DEFAULT hardcoded LIVE_ROOTS. entrypoints NOT injected as roots.
  - `_contract_valid = bool(_entrypoints) and all(_ep in _live for _ep in _entrypoints) and bool(_oracle)` where `_live = set(LIVE_ROOTS)` → entrypoints must BE a SUBSET of LIVE_ROOTS, never "extra".
  - entrypoints flow ONLY into `detonate_oracle(_oracle_src,[_vsym],list(_entrypoints),...)` (the contract-detonated path), not the static floor.
- VERDICT: entrypoints are (a) constrained to be existing LIVE_ROOTS, and (b) consumed by the detonation oracle driver, NOT added to the static floor's roots. README wording wrong on both counts.

## E2 — NGv2 X1 / P1.1 cross-process wiring gap STILL HOLDS at ed91619 (s3_ngv2_x1_recheck.sh)
- `conductor_seams.py:20 _PHASE_COUNT_KEY = {'hunt':'findings','poc':'pocs','detonate':'reports'}` — STILL 3-of-7.
- `triage_result/verify_result/novelty_result/report_artifact` appear in ngv2/ NON-test code ONLY in gate_executor.py (as gate INPUTS); never SET by build_evidence/persist.
- count keys `triaged/verified/novelties/report_count` appear only as planner reads (transition_planner.py:66,67,70,71) + worker artifact labels — never set by persist.
- build_evidence is STILL a NESTED closure inside top-level build_default_seams.

## E3 — DOC IS STALE: p11-build-evidence-perphase-impl IS LANDED (it is HEAD ed91619) but did NOT fix X1 (GAMED ORACLE)
- Both docs say the impl "is NOT in NGv2 master" (worker_exit 2 / reject_rollback). REALITY: it is commit ed91619, the HEAD.
- The commit is +2 lines to build_evidence: adds `source_ready` + a `target_source` literal mutation. It does NOT add the 4 intermediate-gate keys and does NOT extend _PHASE_COUNT_KEY.
- The oracle test_oracle_full_state_advances_all_transitions SEEDS triage_result/verify_result/... directly into state['evidence'] (line 64) instead of asserting build_evidence produces them; test_oracle_build_evidence_emits_eight_keys asserts only the original 8 keys. So GREEN oracle, X1 functionally unclosed — matches MEMORY "build_evidence leaf GAMED the oracle / answer-key leak".

## E4 — Portability ASYMMETRY: module gate portable, runtime symbol floor NOT (s4_portability_asymmetry.py)
- check_wired (MODULE gate) HAS discover_live_roots reconciliation + a rootless no-op clause → PORTABLE.
- symbol_reachable_from_live_root (RUNTIME FLOOR) has NO discover_live_roots fallback, no rootless clause → seeds only from passed roots (default JM LIVE_ROOTS).
- Empirical external-tree probe (no JM LIVE_ROOTS present): helper() genuinely reachable from main.py, yet floor(default)=False; check_wired.wired=True; floor(roots=discover_live_roots)=True.
- => floor FP-storms on any external tree; the fix is to thread discover_live_roots(repo_root) (and/or contract entrypoints) into the floor's roots. discover_live_roots ALREADY EXISTS at HEAD (the primitive the floor doesn't call).

## E5 — Wire-up flag states (harness/config.yaml lines 87-89) + ledger
- autowork.wire_up_gate: true (MODULE gate LIVE) — 16 orphan_unwired rejections in ledger (2026-06-09..06-17, 11 distinct tasks).
- autowork.wire_up_runtime_gate: false; autowork.wire_up_runtime_gate_enforce: false.
- ledger: 1 orphan_symbol_unwired row (task wire-up-runtime-gate-enforce-config = a TEST artifact, phase=rejected) ; 0 wireup_symbol_verdict rows (runtime flag never on in a real run).
