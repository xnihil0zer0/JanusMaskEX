---
interfaces: "creates the new pure module ngv2/gate_executor.py in the external NobleGreedv2 repo, exposing run_gates(from_phase: str, to_phase: str, evidence: dict) -> dict — a deterministic GATE EXECUTOR that maps a phase transition to its applicable may_confirm gates (classify_poc_authenticity, classify_detonation_evidence, verify_sink_present, assess_sink_reachability), calls each over the evidence dict, reads each gate's boolean may_confirm, and decides advance/block fail-closed; wired into the NobleGreed conductor transition path so the four otherwise-orphaned may_confirm gates are actually enforced between stages"
working_dir: "/home/xnihil0zer0/NobleGreedv2"
meta_task_type: validation
---

# Title

ngv2/gate_executor.py — a deterministic gate executor that applies the right may_confirm gates per phase transition and returns advance/block, so the four orphaned NobleGreed confirmation gates are enforced automatically between stages

# Scope

CREATE the new pure module `ngv2/gate_executor.py` in the external NobleGreedv2 repo (working_dir /home/xnihil0zer0/NobleGreedv2). This is a brand-new free-tier file under `ngv2/**`; emit it WHOLE-FILE.

MOTIVATING DEFECT (verified by audit): the four `may_confirm` gates — `classify_poc_authenticity` (ngv2/poc_authenticity_gate.py), `classify_detonation_evidence` (ngv2/detonation_evidence_gate.py), `verify_sink_present` (ngv2/sink_presence_gate.py), and `assess_sink_reachability` (ngv2/sink_reachability_gate.py) — are defined but ORPHANED: they are wired into NO transition in `ngv2/session_gate.py`'s `_HANDLERS`. So false-positive findings (mock PoCs, patched sinks, constant-only/unreachable sinks, static-assert "detonations") were never blocked between stages. This module is the deterministic GATE EXECUTOR: given a phase transition, it selects the applicable may_confirm gates, calls them over the evidence dict, and decides advance/block. It is the script that enforces those gates automatically between stages.

This module exposes ONE primary pure function with NO I/O, NO network, NO wall-clock, NO randomness, NO module-level side effects — it imports the four gate functions and calls them over the `evidence` dict it is handed, so it is deterministic and differential-fuzzable:

    def run_gates(from_phase: str, to_phase: str, evidence: dict) -> dict

TRANSITION → APPLICABLE may_confirm GATE MAP (a transition is the ordered pair `(from_phase, to_phase)`):
- `("verify","poc")` → poc_authenticity: `classify_poc_authenticity(evidence["poc_source"], evidence["target_import_names"])`.
- `("poc","detonate")` → poc_authenticity (`classify_poc_authenticity(evidence["poc_source"], evidence["target_import_names"])`) AND detonation_evidence (`classify_detonation_evidence(evidence["detonation_report"])`).
- `("detonate","novelty")` → detonation_evidence (`classify_detonation_evidence(evidence["detonation_report"])`) AND sink_presence (`verify_sink_present(evidence["target_source"], evidence["expected_signature"])`) AND sink_reachability (`assess_sink_reachability(evidence["sink_name"], evidence["call_sites"])`).
- ANY OTHER transition (e.g. `("source","hunt")`, `("hunt","verify")`, `("novelty","report")`) → NO applicable may_confirm gate.

For each applicable gate the executor calls it and reads its boolean `may_confirm` field (every one of the four gates exposes a top-level `may_confirm` boolean in its return dict, including detonation_evidence). The executor returns a fixed-shape dict:

    {"advance": bool, "blocked_by": list[str], "results": dict[str, dict]}

- `results` maps each applicable gate's stable name → the gate's full return dict (only for gates that were actually CALLED — i.e. their required evidence key was present).
- `advance` is True if and only if EVERY applicable gate that was called returned `may_confirm == True` AND no applicable gate was skipped for missing evidence.
- `blocked_by` is the ordered, de-duplicated list of stable gate names that blocked (either `may_confirm == False`, recorded as the bare gate name e.g. `"poc_authenticity"`, or required-evidence-missing, recorded as `"<gate_name>:missing_evidence"`).
- FAIL-CLOSED RULE: if an applicable gate's required evidence key is MISSING from `evidence`, do NOT call the gate; record `"<gate_name>:missing_evidence"` in `blocked_by` and set `advance` False. (A KeyError must never escape; a missing key is a block, not a crash.)
- A transition with NO applicable may_confirm gate → `advance` True, `blocked_by` empty, `results` empty.

STABLE GATE NAMES (used in both `results` keys and `blocked_by`): `poc_authenticity`, `detonation_evidence`, `sink_presence`, `sink_reachability`.

The module is reachable/WIRED into the NobleGreed conductor's transition path (the place that drives phase transitions, conceptually the consumer of `ngv2/session_gate.py`'s `_HANDLERS`) so the four may_confirm gates are now enforced between stages instead of orphaned. A committed wiring oracle `tests/ngv2/test_gate_executor_wired.py` proves both the advance/block behavior and the wiring (it imports `run_gates` from the live `ngv2.gate_executor` module — importing the live module IS the reachability contract this oracle pins).

# Non-Goals

INTEGRATION is out of scope for this leaf: the task's non_goals MUST declare integration testing out of scope — do NOT author or modify any integration or e2e test; this pure executor is verified solely by its pre-committed, authoritative unit oracle `tests/ngv2/test_gate_executor_wired.py`. Author NO new test and alter NO existing test.

This module does NOT EDIT `ngv2/session_gate.py` (build it as a NEW module; do not reshape `_HANDLERS`). It does NOT run, fuzz, or detonate any PoC; it does NOT make network calls, spawn subprocesses, read the filesystem, parse target source itself, import the target, use the wall-clock, or use randomness. It does NOT re-implement the four gates' internal logic — it only calls them and reads `may_confirm`. It does NOT decide severity, dedupe findings, persist sessions, or format submissions. Do NOT add a second public function or change the three-key return shape. No new third-party dependency, no module-level side effects.

# Inputs

REUSE — do NOT rebuild these:
- The four existing gate functions, imported and called as-is (do NOT re-implement their logic):
  - `from ngv2.poc_authenticity_gate import classify_poc_authenticity` — returns a dict with a `may_confirm` bool (False iff the PoC is a `self_contained_mock`).
  - `from ngv2.detonation_evidence_gate import classify_detonation_evidence` — returns a dict with a `may_confirm` bool (True iff `evidence_kind == "live_execution"`).
  - `from ngv2.sink_presence_gate import verify_sink_present` — returns a dict with a `may_confirm` bool (True iff the signature is present as live code).
  - `from ngv2.sink_reachability_gate import assess_sink_reachability` — returns a dict with a `may_confirm` bool (True iff a non-constant arg reaches the sink at some call site).
- The pre-committed authoritative RED oracle `tests/ngv2/test_gate_executor_wired.py` is the acceptance contract. It imports `run_gates` from the live `ngv2.gate_executor` module and pins the transition→gate map, the advance/block decision, and the fail-closed missing-evidence rule. READ it as the source of truth and make it GREEN; do NOT author or alter any test.
- The existing NobleGreed conductor / `ngv2/session_gate.py` transition path that this executor is wired into; do NOT reshape it.
- Standard library only (`typing` if useful) plus the four sibling ngv2 gate imports above. No new dependency.

# Deliverables

A new pure module `ngv2/gate_executor.py` in the NobleGreedv2 repo, emitted WHOLE-FILE, exposing exactly:

    def run_gates(from_phase: str, to_phase: str, evidence: dict) -> dict:
        # returns {"advance": <bool>, "blocked_by": <list[str]>, "results": <dict[str, dict]>}

It imports `classify_poc_authenticity`, `classify_detonation_evidence`, `verify_sink_present`, and `assess_sink_reachability` from their live `ngv2.*` modules and applies the transition→gate map from Scope. For each applicable gate whose required evidence key is present it calls the gate and reads `may_confirm`; `advance` is True iff every applicable gate was called and every one returned `may_confirm == True`; a missing required evidence key is fail-closed (gate not called, `"<gate_name>:missing_evidence"` recorded in `blocked_by`, `advance` False, no KeyError escapes); a transition with no applicable gate advances with empty `blocked_by`/`results`. The module is wired into the NobleGreed conductor transition path so the four may_confirm gates are enforced between stages. The committed oracle `tests/ngv2/test_gate_executor_wired.py` (a `*_wired` oracle named in the task's `verification_command`) proves both the behavior and the wiring.

EDGE CASES the behavior MUST satisfy (each mirrored as a committed-oracle case the plan's edge_cases/unit_tests/regression_tests enumerate — these are descriptors NAMING committed-oracle cases, NOT authorization to write new tests):
(a) `("poc","detonate")` with an evidence whose `poc_source` is a self-contained mock (defines a local `def vulnerable(...)`/vulnish def, imports nothing from the target) and a live `detonation_report` → poc_authenticity `may_confirm` False → `advance` False, `"poc_authenticity"` in `blocked_by`.
(b) `("detonate","novelty")` with a live `detonation_report` + present `expected_signature` but `call_sites` all constant string literals (e.g. `["os.system('ls -la')"]`) → sink_reachability `may_confirm` False → `advance` False, `"sink_reachability"` in `blocked_by`.
(c) `("detonate","novelty")` with a live `detonation_report` (`method="http_request"`, `ran_target=True`, `observed_runtime_effect=True`, `self_hosted_mock=False`) + an `expected_signature` present as live code in `target_source` + a non-constant call site (e.g. `["os.system(user_input)"]`) → all three gates `may_confirm` True → `advance` True, `blocked_by` empty.
(d) `("source","hunt")` (no applicable may_confirm gate) → `advance` True, `blocked_by` empty, `results` empty.
(e) `("poc","detonate")` missing `evidence["poc_source"]` → poc_authenticity not called → `advance` False, `blocked_by` contains the missing-evidence marker `"poc_authenticity:missing_evidence"`.

The task: EXACTLY ONE impl task. meta_task_type=`validation` (a pure deterministic executor over an evidence dict — the diff-fuzzer exercises `run_gates` over generated transitions/evidence and the committed oracle pins the table). priority: high. dependencies: []. working_dir: `/home/xnihil0zer0/NobleGreedv2`. files_touched: `["ngv2/gate_executor.py"]` ONLY (whole-file emission — the patches path cannot create files, so emit the new module whole; do NOT list `session_gate.py` or the conductor file you only reference). verification_command: `python -m pytest tests/ngv2/test_gate_executor_wired.py -q`. `spec.functional_requirements` CONSOLIDATED to at most 5 entries; `test_spec.unit_tests` MUST enumerate AT LEAST as many entries as `spec.functional_requirements` (validator floor) and `test_spec.regression_tests` MUST list at least two entries — all NAMING committed-oracle cases so every `spec.edge_cases` entry above is reflected (e.g. `test_poc_detonate_mock_poc_blocks_advance`, `test_detonate_novelty_constant_only_callsites_blocks`, `test_detonate_novelty_all_gates_pass_advances`, `test_source_hunt_no_gate_advances`, `test_poc_detonate_missing_poc_source_fails_closed`).
