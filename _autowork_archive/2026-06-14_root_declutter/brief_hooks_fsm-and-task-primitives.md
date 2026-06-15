---
interfaces: "def advance_with_gates(session_id: str, db: Any, run_gates: Callable, advance: Callable, build_evidence: Callable) -> dict\ndef get_task(session_row: dict) -> dict"
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

NobleGreed FSM Gated Transition and Task Extraction Primitives

# Scope

Build `ngv2/gated_advance.py` and `ngv2/session_get_task.py`. `gated_advance.py` implements the state transition gating logic, coordinating the four validation gates (poc_authenticity, sink_presence, sink_reachability, detonation_evidence) using `gate_executor.run_gates`. `session_get_task.py` extracts phase input, target, prior findings, and parked package from a database session row, failing closed on missing keys.

# Non-Goals

Do not edit any existing committed modules or patch session_api.py/session_gate.py. Must not contact external services or auto-submit to huntr. Must not use live database connection or network calls; all external seams must be injected.

# Inputs

Consumes existing pipeline interfaces from `ngv2/session_api.py` (advance, transition, get_current_phase) and `ngv2/gate_executor.py` (run_gates).

# Deliverables

Produces `ngv2/gated_advance.py` which exposes `advance_with_gates(session_id: str, db: Any, run_gates: Callable, advance: Callable, build_evidence: Callable) -> dict`. Produces `ngv2/session_get_task.py` which exposes `get_task(session_row: dict) -> dict`.
