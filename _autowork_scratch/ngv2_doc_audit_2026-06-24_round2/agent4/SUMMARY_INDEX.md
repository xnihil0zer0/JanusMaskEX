# Agent4 Round-2 — ENV-FSM (P2.1) buildability re-derivation at HEAD
NGv2 HEAD 203d007 (p21-c1-fsm-detect-impl landed) · JM HEAD 5ee8fa3 · 2026-06-24

## Scripts & outputs (all under this dir)
- inventory_handlers.out          — symbols/signatures of fsm_evidence/detect/provision/jail_build
- jm_ledger_p21.out               — JM ledger: only c0,c1,c2,c3 oracle+impl pairs ever ran
- g_callvsimport_ast.py/.out      — AST: ZERO call sites AND ZERO production imports of c1/c2/c3 handlers
- g1_producers_and_callrefs.out   — ZERO producer assignments; ZERO live-conductor refs
- g2_phase_literals_initialphase.out — _INITIAL_PHASE='hunt' (run_hunt:61, session_api:46); ENV_PHASE_ORDER used only by handlers
- g2b_phase_dup_sites.out         — phase literals; neither session_api nor state_machine derive from fsm_evidence
- g2c_phase_literal_diff.py/.out  — 6 independent phase tuples across 3 modules; none from c0; no env phase in any live order
- g3g5_touchpoints_and_contenthash.out — worker_phases/_TRANSITION_GATES/AGENT_PHASES carry NO env phase; no workers/<env>.py; advance_gate has 0 live consumers
- g3g4_p02_ngv2_installer.out     — _default_pip_installer host-side, net-ON, single attacker-named pkg, no lockfile/unshare-net
- g3g4_dep_loop.out               — stderr-driven reactive install loop feeds _missing_modules_from_stderr -> pip_installer
- g3g4_jm_p02_oracle.out          — JM has only PYTHON-host P0.2 (2049f78/6f08eeb); sha 0795605 NOT in JM log; NO NGv2-installer oracle
- g_staged_briefs.out             — only brief_hooks_p21_c1 authored; no c4/c5/c6/c7/cP briefs anywhere
- g6_language_coverage.out        — JS flag ON (autocompiler.yaml:21); js_inputs has consumer but NO producer
- g_c1_brief_worksbar.out         — c1 brief wire-up is IMPORT-chain, not CALL-path; integration DEFERRED to unwritten leaf
