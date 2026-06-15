---
dependencies:
  - "ngv2_source_qualify_gate"
  - "ngv2_grounding_confidence_gate"
  - "ngv2_novelty_gate"
  - "ngv2_submission_package_builder"
  - "ngv2_submission_readiness_gate"
  - "ngv2_human_approval_gate"
interfaces: "extends ngv2.state_machine PHASES to ('source','hunt','triage','verify','poc','detonate','novelty','report','awaiting_submission','submitted','done') with ALLOWED_TRANSITIONS one-step ordered, and ngv2.session_gate.gate_transition(phase_from, phase_to, evidence) admitting each transition only on its sibling gate's verdict."
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

Extended PHASES / ALLOWED_TRANSITIONS + session_gate evidence gates wiring the full autonomous lifecycle

# Scope

Additively extend the existing HuntStateMachine spine to expose the full ordered phase set source -> hunt -> triage -> verify -> poc -> detonate -> novelty -> report -> awaiting_submission -> submitted -> done, with a deterministic EVIDENCE gate on every transition. Extend PHASES and ALLOWED_TRANSITIONS and wire ngv2.session_gate.gate_transition so each transition invokes the corresponding pure gate: source->hunt uses qualify(); triage->verify uses compute_confidence()+route_confidence() (admit CONFIRMED/HIGH, MEDIUM->manual-review holding state, LOW->FP-evidence drop); verify->poc->detonate uses existing PoC build + ngv2.detonation.semantic_verdict (require 'confirmed' = exit 0 AND success marker AND expected filesystem-signature in the live fs diff; marker-spoofing alone must NOT confirm); detonate->novelty uses classify_novelty()+route_novelty(); novelty->report uses build_submission_package(); report->awaiting_submission uses readiness(); awaiting_submission->submitted uses approve_submission(); submitted->done uses record_submission(). Pure/deterministic — all non-determinism stays in the injected gate seams. Ship a hand-authored RED oracle that, over mock/scripted seams, deterministically carries one qualified target all the way to a turn-in-ready package, HALTS at awaiting_submission pending the injected human approval, then records the submission on approval — and asserts no built code touches network/clock/randomness/subprocess/live-platform.

# Non-Goals

Do NOT rewrite or replace the existing HuntStateMachine — extend it additively. Do NOT re-implement the pure gates (import and call the sibling modules). Do NOT weaken any existing acceptance gate, especially the strengthened detonation semantic verdict. Do NOT implement any seam adapter (bounty oracle, scanners, LLM hunt worker, live runner, approval seam) — all injected. No network, wall-clock, randomness, real subprocess, or live platform action in any built code. Do not author full integration/e2e harnesses beyond the wiring's own RED oracle. Do not build the SessionApi/MCP surface (that is ngv2_session_api_surface).

# Inputs

Reuse ngv2.state_machine.HuntStateMachine + PHASES, ngv2.session_gate.gate_transition, ngv2.session_db.SessionDB, ngv2.contracts, ngv2.fp_filter.filter_findings, ngv2.dedup.filter_new, ngv2.pattern_scanner, ngv2.detonation.semantic_verdict + DetonationChamber (AFTER prerequisite brief ngv2_fix_detonation_semantic_gate lands), and the existing hunt finders/poc_builder/live-runner injected seams. Consumes the sibling gate functions: ngv2_source_qualify_gate `qualify(target, oracle_result, *, saturation_cap, freshness_min, fp_risk_filter) -> dict`; ngv2_grounding_confidence_gate `compute_confidence(finding, signals: dict) -> str` and `route_confidence(tier: str) -> dict`; ngv2_novelty_gate `classify_novelty(finding, known_corpus: list) -> str` and `route_novelty(verdict, operator_override=False) -> dict`; ngv2_submission_package_builder `build_submission_package(...) -> dict` and `readiness_score(package: dict) -> int`; ngv2_submission_readiness_gate `readiness(...) -> dict` ({"ready": bool, "missing": str|None}); ngv2_human_approval_gate `approve_submission(package, approval_seam) -> dict` and `record_submission(package, decision, *, now_fn) -> dict`. NOTE: prerequisite fix briefs ngv2_fix_classify_phase and ngv2_fix_detonation_semantic_gate must already be landed (external prerequisites, not siblings).

# Deliverables

Additive extension to ngv2.state_machine PHASES and ALLOWED_TRANSITIONS covering source->hunt->triage->verify->poc->detonate->novelty->report->awaiting_submission->submitted->done, and ngv2.session_gate.gate_transition evidence-gate dispatch invoking each pure sibling gate with the stated routing (CONFIRMED/HIGH advance, MEDIUM->manual_review, LOW->drop; detonate requires semantic_verdict 'confirmed'; only NOVEL advances; readiness must be ready; submitted only via approval seam). Plus a committed RED oracle driving the full happy path to the awaiting_submission halt and through approval.
