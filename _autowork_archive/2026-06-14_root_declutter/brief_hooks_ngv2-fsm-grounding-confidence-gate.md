---
interfaces: "exposes `compute_confidence(finding: dict, signals: list) -> str` returning exactly one of \"CONFIRMED\"|\"HIGH\"|\"MEDIUM\"|\"LOW\"; highest tier wins: LOW if any signal is a known-FP match; CONFIRMED if any signal is a taint_flow/formal_path proof or confirmed live_poc; HIGH if >=2 independent tool matches agree with no known-FP; MEDIUM if exactly one tool match with no contradiction; else LOW."
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

Grounding and confidence gate (triage -> verify): pure compute_confidence() returning CONFIRMED/HIGH/MEDIUM/LOW from the signal set, porting legacy grounding.py.

# Scope

Build a pure, stdlib+ngv2-only, deterministic, total module ngv2/grounding_confidence_gate.py exposing `compute_confidence(finding: dict, signals: list) -> str` that ports the legacy grounding.py confidence algorithm. `signals` is a list of dicts, each shaped {"tool": str, "result": "match"|"clean"|"proof"|"known_fp", "kind": "pattern"|"semgrep"|"fp_filter"|"taint_flow"|"formal_path"|"live_poc"}. The function returns exactly one of "CONFIRMED" | "HIGH" | "MEDIUM" | "LOW". Decision rule (highest applicable tier wins — evaluate the strongest evidence; known-FP overrides to LOW):
- LOW if ANY signal is a known-FP match (result == "known_fp", or kind == "fp_filter" with result == "match"). Known-FP contamination dominates and forces LOW regardless of other matches.
- Else CONFIRMED if ANY signal is a structural proof — kind == "taint_flow" with result == "proof", OR kind == "formal_path" with result == "proof", OR kind == "live_poc" with result == "proof" (a confirmed live PoC).
- Else HIGH if there are >= 2 independent tool matches that agree (>= 2 signals with result == "match" from distinct `tool` values) AND no known-FP (cross-validated agreement).
- Else MEDIUM if there is exactly one tool match (one signal result == "match") and no contradicting known-FP.
- Else default LOW.
No silent drops: the returned tier is total over any signal list (including empty -> LOW). Determinism: identical inputs always yield identical tier.

# Non-Goals

Do NOT implement real static analysis, semgrep/joern/codeql runners, symbolic execution, taint engines, or live PoC runners — those produce the `signals` and are injected upstream, not built here. Do NOT perform the FSM transition or route the tier (CONFIRMED/HIGH advance, MEDIUM->manual-review, LOW->drop is ngv2_lifecycle_fsm_wiring). No network, subprocess, LLM, wall-clock, or randomness. The literal word integration appears here to flag that tier routing/integration into the FSM is out of scope; this is a pure classifier consumed by the wiring brief.

# Inputs

Consumes ngv2.contracts (Finding) and the confidence algorithm of legacy /home/xnihil0zer0/AI-Data/NobleGreed-legacy/services/code_audit/grounding.py. `finding: dict` is the candidate finding record. `signals: list` is a list of signal dicts each shaped {"tool": str, "result": "match"|"clean"|"proof"|"known_fp", "kind": "pattern"|"semgrep"|"fp_filter"|"taint_flow"|"formal_path"|"live_poc"}.

# Deliverables

ngv2/grounding_confidence_gate.py exposing `compute_confidence(finding: dict, signals: list) -> str` returning exactly one of "CONFIRMED"|"HIGH"|"MEDIUM"|"LOW" per the highest-tier-wins rule above. Plus a committed, non-vacuous hand-authored RED oracle (test_grounding_confidence_gate.py, importing ngv2.grounding_confidence_gate.compute_confidence) with one case per tier: a known-FP-forces-LOW case (even alongside matches), a taint_flow/formal_path/live_poc CONFIRMED case, a >=2-independent-match HIGH case, a single-match MEDIUM case, and an empty/contradicted LOW case.
