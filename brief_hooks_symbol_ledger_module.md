---
interfaces: "exposes `resolve_interfaces(interfaces_spec: str, state_dir: Path) -> str`; exposes `record_symbols(state_dir: Path) -> dict[str, str]`"
---

# Title

Symbol/interface ledger module (harness/symbol_ledger.py, lazy-derived)

# Scope

Create the NEW module harness/symbol_ledger.py (item 1 of the epic). It must record the top-level signatures actually committed by accepted tasks and resolve a downstream task's spec.interfaces prose against what upstream siblings really produced. The ledger MUST be LAZY-DERIVED: read it at call time from the existing state/impl_progress.jsonl accepted rows (phase==accepted, event==auto_commit) plus the committed files referenced in each row's `files` list, and extract signatures by REUSING the existing extraction in harness/ast_enforcer.py (_extract_func_name_from_signature, FunctionDef return-type extraction, visit_FunctionDef/visit_AsyncFunctionDef) — do NOT invent a new parser. resolve_interfaces returns its input UNCHANGED on any miss or when the symbol_ledger flag is off (the caller in the staging child does the flag gating; this module stays a pure read-derived helper). IMPLEMENTATION CONSTRAINTS (emit as implementation_notes): land entirely OUTSIDE the _NEVER_AUTO_APPROVE deny-list (harness/agent_jail.py, harness/dbus_proxy.py, harness/paths.py, harness/git_integration.py, harness/orchestrator.py, harness/interceptors.py, harness/selfheal.py, harness/autowork_daemon.py, services/); this is a BRAND-NEW MODULE so create it as a NEW FILE (oracle-first); do NOT add an eager record_symbols call anywhere in the orchestrator; do NOT modify existing class methods via partial edit; keep the verification_command to this child's own oracle plus HERMETIC regression files only (never glob tests/planner/, never touch network or pip).

# Non-Goals

Do NOT wire resolve_interfaces into the staging/materialization seam (that is staging_resolve_interfaces). Do NOT touch harness/brief_status.py, harness/planner/cli.py, or any deny-list file. Do NOT add an eager record_symbols call inside orchestrator._auto_commit_accepted. Do NOT invent a new AST/signature parser — reuse harness/ast_enforcer.py. Do NOT add new config flags (the symbol_ledger key already exists).

# Inputs

harness/ast_enforcer.py — reuse _extract_func_name_from_signature, FunctionDef return-type extraction, visit_FunctionDef/visit_AsyncFunctionDef. state/impl_progress.jsonl — append-only ledger; accepted rows look like {"phase":"accepted","event":"auto_commit","task_id","commit_sha","files":[...]}. harness/config.yaml — hierarchical_planning.symbol_ledger flag (read by the downstream caller, not here).

# Deliverables

NEW file harness/symbol_ledger.py exposing `resolve_interfaces(interfaces_spec: str, state_dir: Path) -> str` (returns the input unchanged on any miss or when the flag is off) and `record_symbols(state_dir: Path) -> dict[str, str]` (lazy-derived mapping of top-level symbol name to its committed signature, built by reading accepted auto_commit rows from state/impl_progress.jsonl plus the committed files and extracting signatures via harness/ast_enforcer.py). Plus a NEW HERMETIC oracle test file that pins both signatures and the lazy-derivation contract (fixture impl_progress.jsonl + committed file -> resolved signature; miss -> input returned unchanged). IMPLEMENTATION CONSTRAINTS to emit as implementation_notes: new module = new file (oracle-first); stay outside the _NEVER_AUTO_APPROVE deny-list; no partial edits of class methods; verification_command = this child's own oracle plus hermetic regression files only (no tests/planner/ glob, no network/pip).
