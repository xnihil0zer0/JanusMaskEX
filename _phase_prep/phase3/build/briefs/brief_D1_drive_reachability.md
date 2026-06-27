---
interfaces: "HAND-AUTHORED live driver _e2e_run/drive_reachability.py — corpus -> preflight -> prefilter -> CodeQL -> taint proofs -> session_gate triage -> ADMIT candidates handed to the existing PoC writer/detonator. This is the integration seam that makes the revived cascade actually run on the live hunt path."
dependencies: ["ngv2_source_sink_prefilter", "ngv2_codeql_orchestrate", "ngv2_taint_path_signal", "ngv2_session_gate_reachability_triage", "ngv2_codeql_runner_subprocess_factory"]
meta_task_type: orchestration
spec_author: "Phase-III BUILD-PREP agent (JanusMask)"
spec_reviewed_by: "owner (CodeQL CLI use APPROVED 2026-06-12)"
---

# Title

_e2e_run/drive_reachability.py — HAND-AUTHORED live cascade driver (NOT a blind-dispatch leaf): wire preflight -> prefilter -> CodeQL -> proofs -> triage and hand ADMIT candidates to the existing PoC writer.

# Scope

This is the ONLY hand-authored leaf (lives under `_e2e_run/`, hand-authorable per the established convention — not `ngv2/**`, so it does NOT route through the blind planner/worker). Author/adapt it AFTER Epics A, B, and C land. A byte-exact reference skeleton is provided at `_phase_prep/phase3/build/_reference/_e2e_run/drive_reachability.py` (imports validated). It injects the REAL seams the unit oracles stub: the live GitHub-license fetcher (`gh api`), `make_subprocess_runner(codeql_bin)`, and the live `llm_complete` from `_e2e_run/claude_cli_client.py`. It is verified by a SMOKE RUN on one already-cloned eligible repo (e.g. `tmp/recon_clones/zilliztech-gptcache`), NOT by a unit oracle — it is wiring, and a CodeQL path is evidence, not confirmation (only the existing bwrap `semantic_verdict` confirms).

# Non-Goals

Do NOT add a unit oracle (this is a driver; correctness is the cascade's, proven by the leaf oracles). Do NOT import this driver from any `ngv2/**` production module. Do NOT build a CodeQL DB during BUILD-PREP — the smoke run is the first real DB build and belongs to RUN time. Do NOT manufacture a `confirmed` verdict — hand ADMIT candidates with their source->sink path to the unchanged PoC writer / detonator.

# Inputs

The five landed leaves it composes (see `dependencies`), the provided reference skeleton, and one cloned repo for the smoke run.

# Deliverables

`_e2e_run/drive_reachability.py` adapted from the reference skeleton, plus a recorded smoke run on one cloned repo showing the cascade producing a trace (refused / skipped / ADMIT-candidate). D2 regression sweep (separate): full NGv2 suite green AND the four revived modules (deser_detect, web_framework_detect, codeql_runner, taint_spec_library) each have ≥1 non-test importer.

# Required plan shape

NOT blindly dispatched. If routed at all, task_id VERBATIM `ngv2_drive_reachability`, meta_task_type=`orchestration`, working_dir "/home/xnihil0zer0/NobleGreedv2", files_touched `["_e2e_run/drive_reachability.py"]`, verification_command a smoke invocation (no `cd`). Prefer hand-authoring + owner-reviewed smoke run over blind dispatch (drivers under `_e2e_run/` are hand-authorable per the standing rule).
