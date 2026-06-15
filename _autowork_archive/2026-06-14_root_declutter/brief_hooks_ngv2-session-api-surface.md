---
dependencies:
  - "ngv2_lifecycle_fsm_wiring"
interfaces: "SessionApi reports and drives the full ordered phase set source->...->done (plus manual_review holding state); awaiting_submission->submitted is exposed as the single human-approval-gated transition; reads expose the parked package and the not-ready missing-artifact reason."
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

SessionApi / MCP surface extension exposing the new lifecycle phases and transitions

# Scope

Additively extend ngv2.session_api.SessionApi (and its MCP surface) to expose the new lifecycle phases and transitions wired by ngv2_lifecycle_fsm_wiring: the full ordered phase set source -> hunt -> triage -> verify -> poc -> detonate -> novelty -> report -> awaiting_submission -> submitted -> done, including the manual-review holding state for MEDIUM-tier findings and the awaiting_submission parked state. Expose read/advance operations so an operator/agent can observe the current phase, the parked turn-in-ready package, and the not-ready 'missing artifact' reason, and can drive autonomous transitions while the awaiting_submission -> submitted step remains gated behind the injected human-approval seam. Pure/deterministic over injected seams (SessionApi._classify after the ngv2_fix_classify_phase fix). Ship a hand-authored RED oracle asserting the surface reports the new phases and exposes the awaiting_submission halt + approval transition without performing any side effect.

# Non-Goals

Do NOT define the FSM transitions or evidence gates (consume ngv2_lifecycle_fsm_wiring). Do NOT implement any seam adapter or auto-approve submissions. Do NOT automate the live turn-in. No network, wall-clock, randomness, real subprocess, or live platform action. Do not rewrite SessionApi — extend it additively and do not weaken any existing gate.

# Inputs

Reuse ngv2.session_api.SessionApi and its _classify (AFTER prerequisite brief ngv2_fix_classify_phase lands), ngv2.session_db.SessionDB, ngv2.contracts. Consumes the extended FSM from ngv2_lifecycle_fsm_wiring: ngv2.state_machine PHASES = ('source','hunt','triage','verify','poc','detonate','novelty','report','awaiting_submission','submitted','done') with ALLOWED_TRANSITIONS one-step ordered, and ngv2.session_gate.gate_transition(phase_from, phase_to, evidence) admitting each transition only on its gate's verdict. NOTE: ngv2_fix_classify_phase is an external prerequisite, not a sibling.

# Deliverables

Additive extension to ngv2.session_api.SessionApi / MCP surface exposing the new phases (including manual_review holding and awaiting_submission parked states) with operations to read current phase, inspect the parked submission package, read the readiness 'missing artifact' reason, and request autonomous transitions — with awaiting_submission->submitted surfaced as the single human-gated step. Plus a committed RED oracle test.
