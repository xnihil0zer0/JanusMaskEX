---
interfaces: "exposes `build_submission_package(finding: dict, poc: dict, live_report: dict) -> str` returning a deterministic platform-shaped markdown report with sections IN ORDER: Title, CWE, Severity, Description, Vulnerable Code (file:line refs from finding evidence), Attack Scenario, Proof of Concept (poc.entrypoint + fenced code), Live Test Results (verdict + exit_code + stdout evidence), Impact, Suggested Fix. Pure string assembly, no I/O."
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

Submission package builder (novelty -> report): pure build_submission_package() assembling a deterministic platform-shaped markdown report, mirroring the legacy submission_report_template.

# Scope

Build a pure, stdlib+ngv2-only, deterministic module ngv2/submission_package_builder.py exposing `build_submission_package(finding: dict, poc: dict, live_report: dict) -> str`. It performs pure string assembly (NO file/network/clock I/O) of a platform-shaped markdown report mirroring the legacy submission_report_template.md (now migrated into NobleGreedv2 at templates/submission_report_template.md). The returned markdown MUST contain these sections IN THIS ORDER, each populated from the inputs:
1. Title — from finding["title"].
2. CWE — from finding["cwe"].
3. Severity — from finding["severity"].
4. Description — from finding["description"].
5. Vulnerable Code — file:line references rendered from finding evidence (e.g. finding["evidence"] entries as `<file>:<line>` plus the snippet).
6. Attack Scenario — from finding["attack_scenario"] (or assembled from evidence).
7. Proof of Concept — poc["entrypoint"] followed by the PoC body in a fenced code block (```), from poc["code"].
8. Live Test Results — live_report["verdict"], live_report["exit_code"], and stdout evidence from live_report["stdout"].
9. Impact — from finding["impact"].
10. Suggested Fix — from finding["suggested_fix"].
Determinism: identical (finding, poc, live_report) always yields byte-identical markdown (stable section order, no timestamps, no randomness, no dict-iteration nondeterminism — sort or index any collections). Missing optional fields render a stable placeholder rather than raising.

# Non-Goals

Do NOT automate the actual submission/turn-in to huntr or any bounty platform. Do NOT compute readiness/completeness scoring or confidence/novelty (those are sibling gates). Do NOT perform file, network, subprocess, LLM, wall-clock, or randomness I/O — this is pure string assembly. Do NOT wire the FSM transition (that is ngv2_lifecycle_fsm_wiring). The literal word integration appears here to flag that wiring/integration of this builder into the FSM is out of scope; it is a pure formatter consumed by the readiness and wiring briefs.

# Inputs

Consumes ngv2.contracts (Finding/PoC/LiveTestReport) and the section layout of the migrated template at NobleGreedv2 templates/submission_report_template.md (legacy origin /home/xnihil0zer0/AI-Data/NobleGreed-legacy/orchestrator/templates/submission_report_template.md). `finding: dict` (title, cwe, severity, description, evidence with file:line, attack_scenario, impact, suggested_fix); `poc: dict` (entrypoint, code); `live_report: dict` (verdict, exit_code, stdout).

# Deliverables

ngv2/submission_package_builder.py exposing `build_submission_package(finding: dict, poc: dict, live_report: dict) -> str` returning the ordered markdown report described above (Title, CWE, Severity, Description, Vulnerable Code, Attack Scenario, Proof of Concept, Live Test Results, Impact, Suggested Fix). Plus a committed, non-vacuous hand-authored RED oracle (test_submission_package_builder.py, importing ngv2.submission_package_builder.build_submission_package) asserting: all ten section headers present in order, file:line refs rendered from evidence, the PoC fenced code block contains poc entrypoint+code, the Live Test Results section contains verdict/exit_code/stdout, and that calling twice on identical inputs returns byte-identical output.
