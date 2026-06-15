---
epic: false
working_dir: "/home/xnihil0zer0/NobleGreedv2"
interfaces: "SQLite session store with injected db_path; pure transition-gate validators"
---

# Title

Gated-determinism session state core for NobleGreedv2 (Agentic Spine Epic B)

Build the crash-resilient session-state layer that lets a supervisor step the NobleGreedv2
hunt→triage→poc→detonate→report→done pipeline with atomic, gated phase transitions. A normalized
SQLite session database (own file, injected path) persists findings, PoCs, detonation reports, and a
phase-validation audit log; pure validators gate every transition by deserializing the prior phase's
artifacts and running the existing contract `validate()` methods. The FSM, contracts, and validators
mostly already exist — this epic adds durable persistence and the gate orchestration around them,
correcting the blueprint's hallucinated `/tmp/ngv2/registry.db` unification (the DB path is an
injected seam; three existing modules already collide on schema, so the session DB lives in its own
file). It is a single multi-task **leaf** brief (three tasks), NOT a decomposed epic.

# Scope

- `ngv2/session_db.py` (NEW, whole-file): the normalized schema (`session_pipeline`, `findings`,
  `pocs`, `live_test_reports`, `phase_validation_logs`) with FK constraints and CHECK constraints
  matching `contracts.SEVERITIES` (`('low','medium','high','critical')`) and `contracts.VERDICTS`
  (`('confirmed','refuted','error','inconclusive')`); a `SessionDB(db_path)` class taking an
  **injected** path (no hardcoded `/tmp` default; follow the `WorkerRegistry(db_path)` convention at
  `worker_registry.py:46`); connection setup issuing `PRAGMA journal_mode=WAL`,
  `PRAGMA synchronous=NORMAL`, `PRAGMA busy_timeout=5000`; writes wrapped in `BEGIN IMMEDIATE`.
  Insert/fetch/round-trip helpers for each artifact type. Build row serialization on the contracts'
  **existing** `to_dict`/`from_dict` (verified present on `Finding`/`PoC`/`LiveTestReport`); do not
  invent a parallel `to_row`/`from_row` unless a column-level shape genuinely needs it.
- `ngv2/session_gate.py` (NEW, whole-file): pure `gate_transition(rows, from_phase, to_phase)` that
  deserializes the relevant artifacts and enforces the gate rules — `hunt→triage` needs ≥1 valid
  `Finding`; `triage→poc` needs deduped findings; `poc→detonate` needs every `PoC.finding_id` to map
  to a registered finding; `detonate→report` needs every PoC to have a `LiveTestReport`. Returns a
  structured `GateResult(ok, error)`. Pure over injected rows — no DB access in this module.
- `ngv2/contracts.py` (EDIT, ADDITIVE — likely a no-op): contracts already provides
  `to_dict`/`from_dict` and `validate()` on each dataclass. Only add a helper if `session_db` genuinely
  needs one the existing API cannot serve; otherwise SKIP this leaf. If added, preserve all existing
  dataclasses (`Finding`/`PoC`/`LiveTestReport`), `SEVERITIES`, `VERDICTS`, and every `validate()`.
- `ngv2/state_machine.py` (EDIT, ADDITIVE): add a top-level `transition_with_gate(machine, to, gate_result)`
  wrapper that transitions `machine` to `to` ONLY when `gate_result.ok` is truthy AND the move is in
  `ALLOWED_TRANSITIONS` (a passing gate does NOT bypass the allow-map); otherwise raise `ValueError`
  carrying `gate_result.error` and leave `machine.state.phase` unchanged. Duck-type `.ok`/`.error`
  (do NOT import `session_gate`). Preserve `HuntStateMachine.can_transition`/`transition`,
  `PHASES` (`('hunt','triage','poc','detonate','report','done')`), and `ALLOWED_TRANSITIONS`.

# Non-Goals

The word integration appears here deliberately. Out of bounds: any HTTP/REST server (that is Epic C,
and it is MCP not REST); any network or LLM call; physically merging into `worker_registry.db` /
`agent_registry` / `work_intents` tables (use a separate session DB file; `ATTACH DATABASE` only if a
cross-DB read is ever needed); reconciling the pre-existing three-way intent-table schema collision
(out of scope — just do not add to it); any concurrency *guarantee* claim (WAL/busy_timeout reduce
`SQLITE_BUSY` but are not unit-provable — build the schema deterministically, document concurrency,
do not gate on it).

# Inputs

Already built — consume as-is. `ngv2/contracts.py`: `Finding` (fields `id, target, category, severity,
title, description, evidence`), `PoC` (`finding_id, language, code, entrypoint`), `LiveTestReport`
(`poc_finding_id, verdict, exit_code, stdout, stderr, duration_ms`), each with
`to_dict`/`from_dict`/`validate()`; module constants `SEVERITIES`, `VERDICTS`. `ngv2/state_machine.py`:
`PHASES`, `ALLOWED_TRANSITIONS`, `HuntStateMachine.can_transition`/`transition`. `ngv2/phase_runner.py`:
`get_next_phase(current_phase: Optional[str]) -> str`. Convention reference for an injected DB path:
`ngv2/worker_registry.py:46` (`WorkerRegistry(db_path, *, now_fn=None)` — required path, no default,
no WAL/busy_timeout today), `ngv2/agent_registry.py` (`AgentRegistry(db_path, now_fn=...)`,
`_init_schema`). Do NOT introduce a hardcoded registry-DB path — there is none today by design.

# Deliverables

1. `ngv2/session_db.py` — oracle creates a `SessionDB(tmp_path/"s.db")`, asserts the WAL/
   busy_timeout pragmas are in effect (`PRAGMA journal_mode` returns `wal`), inserts one
   `Finding`/`PoC`/`LiveTestReport`, and asserts a faithful round-trip plus FK/CHECK enforcement
   (a bad `severity` or orphan `finding_id` is rejected). meta_task_type `io_adapter` (stateful_fuzz;
   the differential gate is bypassed — the oracle is load-bearing).
2. `ngv2/session_gate.py` — oracle asserts each of the four transition gates passes on a valid row set
   and fails (with a specific error) on each violation (zero findings; orphan PoC; PoC without report).
   Pure → fully fuzzable. meta_task_type `validation`.
3. `ngv2/contracts.py` (additive, if needed) and `ngv2/state_machine.py` (additive) — oracles assert
   the new helpers/wrappers work AND every existing symbol is preserved.

# Required plan shape

Exactly three leaf tasks (B1, B2, B4), module-creating first. This is a single non-epic plan — the planner emits
these tasks directly; do NOT decompose into child briefs.

- LEAF B1 `session_gate` — meta_task_type `validation`, NEW whole-file, pure/fuzzable. (Build before
  B2 so the DB layer can reuse its `GateResult` shape, but it has no code dependency on B2.)
- LEAF B2 `session_db` — meta_task_type `data_model` (bypass differential fuzz — stateful SQLite is not differentially fuzzable; the oracle is load-bearing), NEW whole-file, side-effecting SQLite; oracle is
  the gate (differential fuzz bypassed for stateful DB code, per the taxonomy).
- (B3 `contracts_serialization` is DROPPED — the existing `to_dict`/`from_dict` fully serve session_db;
  do NOT emit a contracts.py leaf.)
- LEAF B4 `state_machine_gate` — meta_task_type `validation`, EDIT `ngv2/state_machine.py` additively
  (adds ONLY the new top-level function `transition_with_gate`; modifies nothing). PATCH FORMAT
  (MANDATORY): emit a single `__JANUSMASK_PATCHES__` list with EXACTLY ONE entry of kind `'symbol'`
  whose `name` is the EXISTING module constant `PHASES`. In `code`, reproduce that anchor line
  BYTE-FOR-BYTE exactly as staged read-only at `{WORK_DIR}/inbox/targets/ngv2/state_machine.py` — it is
  the single line `PHASES = ('hunt', 'triage', 'poc', 'detonate', 'report', 'done')` — then append your
  new top-level `def transition_with_gate(machine, to, gate_result):` after it. The harness inserts the
  new function next to the anchor and preserves every other byte. DO NOT reproduce or modify
  `HuntStateMachine`, `ALLOWED_TRANSITIONS`, `transition`, `can_transition`, or any other existing
  symbol. DO NOT anchor on a class/function. DO NOT emit whole-file.

**Plan-shape invariants for EVERY leaf (NEW and EDIT alike):** every leaf MUST list at least two edge_cases in its test_spec and mirror EACH into regression_tests or property_tests (the plan validator hard-drops any leaf without this); name a `*_wired` oracle in
`verification_command` — required because the plan validator resolves `files_touched` against the
JanusMaskJR repo root, where these NGv2 paths are absent, so every leaf reads as module-creating and a
`*_wired` oracle name is mandatory (the runtime wire-up gate no-ops for external/rootless targets).
Carry the literal word `integration` in each leaf's `non_goals`. NEW modules emit whole-file (the
patch path cannot create files), one file per task; EDIT leaves preserve all existing symbols and emit
additively.

Sequencing: hold this epic's allowlist entry until Epic A is green (no code dep, but sequence for a
clean proof). Epic C depends on B2 (`session_db`) and B1 (`session_gate`) — do not allowlist C until B
is green.
