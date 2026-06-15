---
interfaces: "exposes `qualify(target: dict, oracle_result: dict, *, saturation_cap: int = 50, freshness_min: int = 7) -> dict` returning {\"decision\": \"GO\"|\"SKIP\"|\"UNKNOWN\", \"reason\": str, \"target_spec\": dict|None}; UNKNOWN if oracle_result lacks any required key; GO iff expected_payout > 0 AND open_submissions < saturation_cap AND days_since_audit >= freshness_min AND fp_risk is False; else SKIP with the first failing gate named in reason."
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

Bounty sourcing and qualification gate (source -> hunt): pure qualify() returning GO/SKIP/UNKNOWN with the failing gate named, porting legacy bounty_gate.py + qualify_target.py.

# Scope

Build a pure, stdlib+ngv2-only, deterministic, total module ngv2/source_qualify_gate.py exposing `qualify(target: dict, oracle_result: dict, *, saturation_cap: int = 50, freshness_min: int = 7) -> dict`. It ports the BEHAVIOR of the legacy bounty_gate.py + qualify_target.py GO/SKIP/UNKNOWN decision. `target` is the candidate repo descriptor with keys {repo: str, package: str, ...}. `oracle_result` is the bounty-oracle seam's already-computed verdict with REQUIRED keys {expected_payout: float, open_submissions: int, days_since_audit: int, fp_risk: bool}. Decision rule (evaluate in order, deterministic, no side effects):
- Return {"decision": "UNKNOWN", "reason": "missing key: <name>", "target_spec": None} if `oracle_result` lacks ANY of the four required keys (name the first missing key).
- Otherwise return {"decision": "GO", "reason": "qualified", "target_spec": {...}} iff ALL hold: expected_payout > 0 AND open_submissions < saturation_cap AND days_since_audit >= freshness_min AND fp_risk is False. `target_spec` echoes the qualified target (e.g. {"repo": target["repo"], "package": target["package"], "expected_payout": ...}).
- Otherwise return {"decision": "SKIP", "reason": "<failing gate>", "target_spec": None} naming the FIRST failing gate, one of: "expected_payout <= 0", "open_submissions >= saturation_cap (<cap>)", "days_since_audit < freshness_min (<min>)", "fp_risk match". `saturation_cap` and `freshness_min` are tunable args defaulting to 50 and 7. No silent SKIP — reason always names the cause.

# Non-Goals

Integration tests are out of scope and NOT required: this is a pure, total, side-effect-free function tested in isolation, so every task this brief produces MUST declare integration out of scope in its own non_goals (no integration_test is expected — the FSM integration of this verdict is delivered separately by ngv2_lifecycle_fsm_wiring). Do NOT implement the real side-effecting bounty-platform client, network, subprocess, LLM, wall-clock, or randomness — the bounty_oracle that produces `oracle_result` is an injected seam, not built here. Do NOT perform any FSM transition or wiring (that is ngv2_lifecycle_fsm_wiring). Do NOT weaken any admitting criterion.

# Inputs

Consumes ngv2.contracts and the GO/SKIP/UNKNOWN decision behavior of legacy /home/xnihil0zer0/AI-Data/NobleGreed-legacy/services/bounty_gate.py and qualify_target.py. `target: dict` with keys {repo, package, ...}; `oracle_result: dict` with required keys {expected_payout: float, open_submissions: int, days_since_audit: int, fp_risk: bool} produced by the injected bounty_oracle seam. Module constants / default args: saturation_cap = 50, freshness_min = 7.

# Deliverables

ngv2/source_qualify_gate.py exposing `qualify(target: dict, oracle_result: dict, *, saturation_cap: int = 50, freshness_min: int = 7) -> dict` returning {"decision": "GO"|"SKIP"|"UNKNOWN", "reason": str, "target_spec": dict|None} per the decision rule above. Plus a committed, non-vacuous hand-authored RED oracle (test_source_qualify_gate.py, importing ngv2.source_qualify_gate.qualify) covering: one GO all-pass case asserting target_spec; one UNKNOWN case per missing required key; and one SKIP case per failing gate, each asserting the exact reason string.
