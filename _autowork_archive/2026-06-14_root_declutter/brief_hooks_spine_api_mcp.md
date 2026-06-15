---
epic: false
working_dir: "/home/xnihil0zer0/NobleGreedv2"
interfaces: "pure JSON-in/JSON-out session handler over an injected SessionDB; thin stdio MCP transport"
---

# Title

MCP session-control surface for NobleGreedv2 (Agentic Spine Epic C)

Expose the gated session pipeline to a supervising agent as **MCP tools** over a pure handler —
NOT as a REST/FastAPI service. The blueprint's HTTP surface both violates NobleGreedv2's stdlib-only
core policy and duplicates the role of the existing stdio MCP server pattern; this epic instead
follows the proven JanusMaskJR `overseer/web_api.py` shape: a pure, in-process handler class
(`OverseerWebApi` is the reference — a pure class over an injected store) with the stdio transport
bolted on separately behind a `__main__` guard so the fuzz-gated logic stays transport-free. It is a
single multi-task **leaf** brief (two tasks), NOT a decomposed epic.

# Scope

- `ngv2/session_api.py` (NEW, whole-file): `SessionApi(db)` — a pure class over an injected
  `SessionDB` (from Epic B). Methods return JSON-serializable dicts only, no transport, no network:
  `create_session(session_id, target_spec)`, `get_state(session_id)`,
  `submit_artifacts(session_id, phase, artifacts)` (validates each artifact via the contract
  `validate()` before writing), `transition(session_id, to_phase)` (delegates to the Epic-B
  `session_gate.gate_transition` + `phase_runner.get_next_phase`, writes a `phase_validation_logs` row
  on every attempt). Every method is deterministic given the injected store.
- `ngv2/session_mcp.py` (NEW, whole-file): the thin transport. Registers three MCP tools
  (`create_session`, `submit_artifacts`, `transition`) that call straight through to `SessionApi`.
  The actual server `.run()` sits behind `if __name__ == "__main__":` so importing the module has no
  side effect and the tool functions remain pure-ish callables.

# Non-Goals

The word integration appears here deliberately. Out of bounds: FastAPI, Flask, `http.server`, or any
bound network socket (the fuzz sandbox blocks `socket`, and a networked daemon violates the stdlib
core policy); any new SQLite schema (reuse Epic B's `SessionDB`); duplicating the legacy
`NobleGreed/services/mcp_server.py` task/feedback tools (this server's domain is session phase
control, orthogonal to those); putting any transport call inside the fuzz-gated handler path.

# Inputs

Already built — consume as-is: Epic B's `ngv2/session_db.py` (`SessionDB(db_path)`) and
`ngv2/session_gate.py` (`gate_transition`/`GateResult`); `ngv2/contracts.py` validators
(`Finding`/`PoC`/`LiveTestReport.validate()`); `ngv2/phase_runner.py::get_next_phase`. Pattern
reference (cleanroom, do not import): JanusMaskJR `overseer/web_api.py` — the `OverseerWebApi` pure
handler over an injected store with transport kept in a separate module. Reference for the stdio MCP
idiom: legacy `/home/xnihil0zer0/NobleGreed/services/mcp_server.py` (FastMCP stdio, `from
mcp.server.fastmcp import FastMCP`, validated writes) — copy the *shape*, not the tools. Note that the
MCP SDK (`mcp`) is not in NGv2's `requirements.txt`; the `session_mcp` import-purity oracle must not
hard-depend on it (guard the FastMCP import so the module imports cleanly under test and only the
`__main__` path needs the SDK).

# Deliverables

1. `ngv2/session_api.py` — oracle drives a `SessionApi` over a fake/in-memory `SessionDB`: asserts
   `create_session` then `get_state` reflects phase `hunt`; `submit_artifacts` rejects an invalid
   `Finding` and accepts a valid one; `transition` to an allowed phase succeeds and writes an audit
   row, to a disallowed phase returns a 422-style error dict and writes a failed audit row. Pure over
   the injected store → fuzzable on the handler logic. meta_task_type `orchestration`.
2. `ngv2/session_mcp.py` — oracle imports the module (asserting zero import side effects), asserts the
   three tools are registered and each dispatches to the matching `SessionApi` method, and asserts the
   server `.run()` is guarded by `__main__`. meta_task_type `io_adapter` (differential fuzz bypassed;
   oracle load-bearing).

# Required plan shape

Exactly two leaf tasks (C1, C2), module-creating
order. This is a single non-epic plan — the planner emits these tasks directly; do NOT decompose into
child briefs.

- LEAF C1 `session_api` — meta_task_type `orchestration`, NEW whole-file, pure over injected store.
- LEAF C2 `session_mcp` — meta_task_type `mcp_plumbing` (bypass differential fuzz — a thin MCP stdio
  transport shim is NOT differentially fuzzable; the import-purity oracle is load-bearing), NEW
  whole-file, thin transport behind `__main__`; oracle asserts import-purity + tool registration.
- (C0 `session_schema` is DROPPED — no separate request/response dataclass module is warranted; do NOT
  emit it. Exactly two leaves: C1, C2.)

PINNED CONTRACTS (the committed oracles assert these EXACTLY — build to them):
- C1 `SessionApi(db)`: `create_session(session_id, target_spec)->{'ok':True,'session_id','phase':'hunt'}`;
  `get_state(session_id)->{'ok':True,'session_id','phase','target_spec'}` (unknown id ->
  `{'ok':False,'status':404,'error':<str>}`); `submit_artifacts(session_id, phase, artifacts)->
  {'ok':True,'accepted':<int>,'rejected':[{'index':<int>,'error':<str>},...]}` (artifacts = list of
  to_dict() forms; each rebuilt + validate()-checked BEFORE write; invalid never persisted; partial
  accept; rejected carries input index); `transition(session_id, to_phase)` writes a
  phase_validation_logs audit row on EVERY attempt — allowed+gate-pass ->
  `{'ok':True,'session_id','from','to'}` and advances; disallowed -> `{'ok':False,'status':422,'error':<str>}`
  phase unchanged + FAILED audit row; allowed-but-gate-fails -> ok False, phase unchanged, audit row still
  written. Persist/read session phase via the EXISTING `session_pipeline` table through the injected db
  (NO new schema). Audit read accessor is `get_phase_validation_logs()`, writer
  `append_phase_validation_log(...)`.
- C2 `session_mcp`: module imports cleanly with the `mcp` SDK ABSENT (guard FastMCP import in try/except
  ImportError; `'mcp' not in sys.modules` after import). Expose `build_tools(api)->dict[str,callable]` with
  EXACTLY keys {'create_session','submit_artifacts','transition'}, each delegating to the matching
  SessionApi method and returning its identical dict. `.run()` (FastMCP construction) ONLY under
  `if __name__ == "__main__":` — no top-level run, no import side effect.

DETERMINISM (every leaf): the AST enforcer REJECTS wall-clock/random — do NOT call time.time(),
datetime.now(), or random anywhere. session_api writes audit rows via the injected SessionDB; if a
timestamp is ever needed take an injected now_fn (WorkerRegistry convention) or omit it.
IMPORT PURITY (C2): guard the FastMCP/`mcp` SDK import (it is NOT in NGv2 requirements) so the module
imports cleanly under the oracle and only the `__main__` path needs the SDK.

**Plan-shape invariants for EVERY leaf:** every leaf MUST list at least two edge_cases in its test_spec and mirror EACH into regression_tests or property_tests (the plan validator hard-drops any leaf without this); name a `*_wired` oracle in `verification_command` — required
because the plan validator resolves `files_touched` against the JanusMaskJR repo root, where these
NGv2 paths are absent, so every leaf reads as module-creating (the runtime wire-up gate no-ops for
external targets). Carry the literal word `integration` in each leaf's `non_goals`. NEW modules emit
whole-file, one file per task.

Sequencing: do not allowlist this epic until Epic B is green (C1 imports `SessionDB`/`session_gate`).
