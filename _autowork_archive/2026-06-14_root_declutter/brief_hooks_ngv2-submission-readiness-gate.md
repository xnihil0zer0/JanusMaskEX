---
dependencies:
  - "ngv2_source_qualify_gate"
  - "ngv2_grounding_confidence_gate"
  - "ngv2_novelty_gate"
  - "ngv2_submission_package_builder"
interfaces: "exposes `readiness(finding, poc, live_report, novelty: str, bounty: dict, package: dict, confidence: str) -> dict` returning {\"ready\": bool, \"missing\": str|None}; ready iff confidence in {CONFIRMED,HIGH} AND live verdict 'confirmed' AND novelty=='NOVEL' AND bounty-eligible AND readiness_score==3."
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

Submission-readiness gate (report -> awaiting_submission): pure readiness() admitting only fully-grounded packages

# Scope

Build a pure, stdlib+ngv2-only module ngv2/submission_readiness_gate.py realizing the report -> awaiting_submission SUBMISSION-READINESS gate. Port the BEHAVIOR of the legacy services/mcp_server.py submit_finding gates (dedup, bounty-eligibility, live-tested, readiness). A pure readiness(finding, poc, live_report, novelty, bounty, package) admits a package to the human ONLY when ALL hold: confidence in {CONFIRMED, HIGH}; a live_tested PoC with verdict 'confirmed'; novelty == NOVEL; bounty-eligible target; report package complete (readiness_score == 3). Anything short HALTS in a not-ready state naming EXACTLY the missing artifact (no generic failure). Deterministic and total. Ship a hand-authored RED oracle: one all-pass case plus one case per failing precondition, each asserting the named missing artifact.

# Non-Goals

Do NOT build the submission package or its completeness score (consume ngv2_submission_package_builder). Do NOT compute confidence or novelty (consume the upstream gates). Do NOT perform the human approval or any submission (that is ngv2_human_approval_gate). No network, subprocess, LLM, wall-clock, or randomness. Do not wire the FSM transition (that is ngv2_lifecycle_fsm_wiring). Do not weaken any precondition.

# Inputs

Consumes ngv2.contracts (Finding/PoC/LiveTestReport, VERDICTS) and legacy services/mcp_server.py submit_finding gate behavior. Consumes the confidence tier from ngv2_grounding_confidence_gate `compute_confidence(finding, signals: dict) -> str` returning "CONFIRMED"|"HIGH"|"MEDIUM"|"LOW"; the novelty verdict from ngv2_novelty_gate `classify_novelty(finding, known_corpus: list) -> str` returning "NOVEL"|"POSSIBLE_DUP"|"CONFIRMED_DUP"; the bounty-eligibility/qualified target_spec from ngv2_source_qualify_gate `qualify(...) -> dict` ({"decision":"GO"|"SKIP"|"UNKNOWN",...,"target_spec":dict|None}); and the package + score from ngv2_submission_package_builder `build_submission_package(...) -> dict` and `readiness_score(package: dict) -> int` in 0..3.

# Deliverables

ngv2/submission_readiness_gate.py exposing `readiness(finding, poc, live_report, novelty: str, bounty: dict, package: dict, confidence: str) -> dict` returning {"ready": bool, "missing": str|None} where ready==True iff confidence in {CONFIRMED,HIGH} AND live_report verdict=='confirmed' AND novelty=='NOVEL' AND bounty-eligible AND readiness_score(package)==3; otherwise ready==False and missing names exactly the failing artifact. Plus a committed RED oracle test.
