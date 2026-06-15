---
interfaces: "creates the new pure module ngv2/detonation_evidence_gate.py in the external NobleGreedv2 repo, exposing classify_detonation_evidence(report: dict) -> dict — a deterministic gate that classifies the EVIDENCE KIND behind a detonation report (live_execution | static_assertion | mock_execution) and forbids a 'confirmed' verdict unless the target was actually executed at runtime; wired into the NobleGreed verdict path so a report whose 'detonation' is only a regex/AST source-pattern assertion (or a self-hosted mock run) can never be labeled 'confirmed'"
working_dir: "/home/xnihil0zer0/NobleGreedv2"
meta_task_type: validation
---

# Title

ngv2/detonation_evidence_gate.py — a deterministic detonation-evidence-kind gate that classifies a detonation report as live_execution, static_assertion, or mock_execution and downgrades any non-live verdict from "confirmed" to "unproven"

# Scope

CREATE the new pure module `ngv2/detonation_evidence_gate.py` in the external NobleGreedv2 repo (working_dir /home/xnihil0zer0/NobleGreedv2). This is a brand-new free-tier file under `ngv2/**`; emit it WHOLE-FILE.

MOTIVATING DEFECT (verified live): a NobleGreed finding (h2oai/h2ogpt file-read) shipped a PoC that only REGEX/AST-ASSERTS that certain source-code patterns exist — pure static analysis — yet the detonation report labeled it a "live detonation" and claimed it "deterministically proves" exploitability. Static pattern-matching and self-mock executions were not distinguished from real runtime exploitation, so an unexploited finding was reported as "confirmed". This module is the deterministic gate that closes that gap.

The module exposes ONE primary pure function with NO I/O, NO network, NO wall-clock, NO randomness, NO module-level side effects (it operates only on the dict passed in, so it is differential-fuzzable):

    def classify_detonation_evidence(report: dict) -> dict

Input `report` is a plain dict that may contain the keys: `method` (one of "regex_assert" | "ast_assert" | "http_request" | "subprocess" | "import_call"), `ran_target` (bool), `target_endpoint` (str | None), `observed_runtime_effect` (bool), `fs_effect` (str | None), `self_hosted_mock` (bool). Any key may be absent.

Return a dict with EXACTLY three keys:
- `evidence_kind`: "live_execution" | "static_assertion" | "mock_execution"
- `may_confirm`: bool
- `downgraded_verdict`: "confirmed" | "unproven"

CLASSIFICATION LOGIC (deterministic, fail-closed):
- `static_assertion` if `method` is in {"regex_assert", "ast_assert"}, OR if `ran_target` is falsy AND there is no observed runtime effect.
- `mock_execution` if `self_hosted_mock` is truthy (the PoC ran against its OWN mock, not the real target) — this takes precedence over a live classification so a mock run can never be called live.
- `live_execution` ONLY if `ran_target` is truthy AND `observed_runtime_effect` is truthy AND `self_hosted_mock` is NOT truthy.
- Precedence so the gate is total and fail-closed for the empty/partial dict: a `regex_assert`/`ast_assert` method is static regardless of other keys; otherwise a self_hosted_mock is mock_execution; otherwise live_execution requires both ran_target and observed_runtime_effect truthy; everything else (including the empty dict) is static_assertion.
- `may_confirm` = (evidence_kind == "live_execution").
- `downgraded_verdict` = "confirmed" iff `may_confirm` else "unproven".

The module is reachable/WIRED into the NobleGreed verdict path (the detonation→verdict chokepoint) so no report can be promoted to "confirmed" unless this gate returns `may_confirm == True`. A committed wiring oracle `tests/ngv2/test_detonation_evidence_gate_wired.py` proves both the classification table and the wiring (it imports `classify_detonation_evidence` from the live `ngv2.detonation_evidence_gate` module and asserts it is referenced on the verdict path).

# Non-Goals

INTEGRATION is out of scope for this leaf: the task's non_goals MUST declare integration testing out of scope — do NOT author or modify integration/e2e tests; this pure gate is verified solely by its committed unit oracle `tests/ngv2/test_detonation_evidence_gate_wired.py`, which is pre-committed and authoritative — author NO new test. This module does NOT run, fuzz, or detonate any PoC; it does NOT make network calls, spawn subprocesses, read the filesystem, parse source code, or import the target — it is a PURE classifier over a dict that some OTHER component already produced. It does NOT decide severity, dedupe findings, or format submissions. Do NOT add a second public function or change the three-key return shape. No new third-party dependency, no wall-clock, no randomness, no module-level side effects.

# Inputs

REUSE — do NOT rebuild these:
- The pre-committed authoritative RED oracle `tests/ngv2/test_detonation_evidence_gate_wired.py` is the acceptance contract. It imports `classify_detonation_evidence` from the live `ngv2.detonation_evidence_gate` module, pins the full classification table one case per branch, and asserts the module is wired onto the NobleGreed verdict path. READ it as the source of truth and make it GREEN; do NOT author or alter any test.
- The existing NobleGreed verdict path in the NGv2 repo (the detonation→report→verdict chokepoint) that this gate is wired into; do NOT reshape it beyond the one reference that makes `check_wired` pass.
- Standard library only (`typing` if useful). No new dependency.

# Deliverables

A new pure module `ngv2/detonation_evidence_gate.py` in the NobleGreedv2 repo, emitted WHOLE-FILE, exposing exactly:

    def classify_detonation_evidence(report: dict) -> dict:
        # returns {"evidence_kind": <str>, "may_confirm": <bool>, "downgraded_verdict": <str>}

with the deterministic, fail-closed classification specified in Scope, wired into the NobleGreed verdict path so a "confirmed" verdict is impossible unless `may_confirm` is True. The committed oracle `tests/ngv2/test_detonation_evidence_gate_wired.py` (a `*_wired` oracle named in the task's `verification_command`) proves both the classification table and the wiring.

EDGE CASES the behavior MUST satisfy (each mirrored as a committed-oracle case the plan's edge_cases/unit_tests/regression_tests enumerate — these are descriptors NAMING committed-oracle cases, NOT authorization to write new tests):
(a) `method="regex_assert"` (any other keys) → `evidence_kind="static_assertion"`, `may_confirm=False`, `downgraded_verdict="unproven"`. (A pure source-pattern regex assertion is NOT a detonation.)
(b) `self_hosted_mock=True` together with a subprocess effect (e.g. `method="subprocess"`, `ran_target=True`, `observed_runtime_effect=True`) → `evidence_kind="mock_execution"`, `may_confirm=False`, `downgraded_verdict="unproven"`. (Running against your own mock is not running against the real target.)
(c) `method="http_request"`, `ran_target=True`, `observed_runtime_effect=True`, `self_hosted_mock=False` → `evidence_kind="live_execution"`, `may_confirm=True`, `downgraded_verdict="confirmed"`. (The only path to "confirmed".)
(d) empty / missing-keys dict `{}` → defaults to `evidence_kind="static_assertion"`, `may_confirm=False`, `downgraded_verdict="unproven"` (FAIL-CLOSED: absent evidence is never live).

The task: EXACTLY ONE impl task. meta_task_type=`validation` (a pure deterministic gate function — the diff-fuzzer exercises `classify_detonation_evidence` over generated dicts and the committed oracle pins the table). priority: high. dependencies: []. working_dir: `/home/xnihil0zer0/NobleGreedv2`. files_touched: `["ngv2/detonation_evidence_gate.py"]` ONLY (whole-file emission — the patches path cannot create files, so emit the new module whole; do NOT list the verdict-path file you only reference). verification_command: `python -m pytest tests/ngv2/test_detonation_evidence_gate_wired.py -q`. `spec.functional_requirements` CONSOLIDATED to at most 5 entries; `test_spec.unit_tests` MUST enumerate AT LEAST as many entries as `spec.functional_requirements` (validator floor) and `test_spec.regression_tests` MUST list at least two entries — all NAMING committed-oracle cases so every `spec.edge_cases` entry above is reflected (e.g. `test_regex_assert_is_static_assertion`, `test_self_hosted_mock_subprocess_is_mock_execution`, `test_http_request_with_runtime_effect_is_live_execution_confirmed`, `test_empty_report_fails_closed_to_static_assertion`).
