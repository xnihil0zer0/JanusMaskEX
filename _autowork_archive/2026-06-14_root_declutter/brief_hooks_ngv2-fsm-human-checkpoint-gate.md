---
interfaces: "exposes `check_human_approval(decision_filepath: str) -> bool` returning True iff the injected operator decision file contains an approve decision (the SINGLE human checkpoint of the lifecycle), and `persist_submission(record: dict, now_fn: callable) -> None` which stamps the final submission record via the injected now_fn and writes/returns it to the ledger. Deterministic over the injected filepath + now_fn."
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

Human checkpoint gate (awaiting_submission -> submitted -> done): the SINGLE human decision via an injected operator decision-file, plus timestamped ledger persistence.

# Scope

Build a stdlib+ngv2-only, deterministic module ngv2/human_checkpoint_gate.py exposing two functions. This is the SINGLE human checkpoint of the entire autonomous lifecycle: a fully-assembled, turn-in-ready package is parked in awaiting_submission and advances to submitted ONLY when the operator approves through an INJECTED decision-file seam (mirroring JanusMaskJR's own decision-file gate).
- `check_human_approval(decision_filepath: str) -> bool`: reads the operator decision at the injected `decision_filepath` (a JSON/markdown decision file written by the human operator out-of-band) and returns True iff it contains an APPROVE decision (e.g. {"decision": "approve"} or an equivalent approve token, case-insensitive). Returns False on reject/hold, on absent/empty file, or on any non-approve content — never auto-approve, never advance on missing decision.
- `persist_submission(record: dict, now_fn: callable) -> None`: stamps the final submission `record` with a timestamp obtained from the injected `now_fn()` (NOT the wall clock) and persists it as a ledger row. The record carries (target, cwe, severity, payout_estimate, novelty, evidence, approval, timestamp). Deterministic over (record, now_fn) — given the same now_fn it produces the same stamped row.
Determinism: all non-determinism (filesystem read of the decision file, the clock) is confined to the injected `decision_filepath` and `now_fn` seams; no internal wall-clock or randomness.

# Required plan shape

The impl task (the one delivering ngv2/human_checkpoint_gate.py) MUST pin meta_task_type=`data_model`: external NGv2 target — the diff-fuzzer cannot resolve external imports, so use a fuzzer-bypassed, smoke-gated meta-type (data_model). NEVER `io_adapter` or any other fuzz-eligible meta-type. `test_spec.regression_tests` MUST list at least two entries that NAME existing test cases from the committed oracle (plan descriptors referencing committed/landed tests — this does NOT authorize authoring new tests), so every `spec.edge_cases` entry is reflected per the validator's edge-case rule.

# Non-Goals

Do NOT implement the real operator UI or automate the actual platform turn-in — the human performs the submission; this gate stops at recording an approved, turn-in-ready package. Do NOT implement the decision-file writer/adapter (the operator authors it; the path is injected). Do NOT auto-approve or advance on a missing/ambiguous decision. Do NOT build the package (consume ngv2_submission_package_builder). No network, subprocess, LLM, real wall-clock (use the injected now_fn), or randomness. Do NOT wire the FSM transition (that is ngv2_lifecycle_fsm_wiring). The literal word integration appears here to flag that wiring/integration of this checkpoint into the FSM is out of scope; this brief delivers the pure approval+persist functions.

# Inputs

Consumes ngv2.contracts and ngv2.session_db.SessionDB for the ledger. Injected at runtime: `decision_filepath: str` (path to the operator decision file, analogous to JanusMaskJR's decision-file gate) and `now_fn: callable` (returns the timestamp for the ledger row). The turn-in-ready package/record originates upstream from ngv2_submission_package_builder `build_submission_package(...) -> str` and the readiness check.

# Deliverables

ngv2/human_checkpoint_gate.py exposing `check_human_approval(decision_filepath: str) -> bool` (True iff the injected decision file holds an approve decision; False on reject/hold/absent) and `persist_submission(record: dict, now_fn: callable) -> None` (stamps the submission record via the injected now_fn and writes the ledger row). Plus a committed, non-vacuous hand-authored RED oracle (test_human_checkpoint_gate.py, importing ngv2.human_checkpoint_gate) covering: an approve decision file -> True; a reject/hold file -> False; an absent/empty decision file -> False; and persist_submission stamping a record with a deterministic injected now_fn and producing the expected ledger row.
