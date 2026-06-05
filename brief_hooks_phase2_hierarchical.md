---
epic: true
complexity_score: 8
---

# Title

phase2_hierarchical: Level-2 of the hierarchical planner — symbol/interface ledger, read-derived failure propagation, planner-time depth budget, and arbitrary-depth epic recursion.

# Scope

This is an EPIC. Decompose it into a small set (4–6) of independent child briefs
that together complete "Level 2" of the hierarchical planner. Phase 1 already
delivered: epic decomposition (`_run_epic_pipeline`), child-brief serialization,
transitive allowlist auto-admission, `compute_epic_status` read-derived roll-up
(already returns `blocked` when any child is blocked/zombie), `check_brief_depth`
(already implemented in `harness/depth_validator.py`), and failure *containment*
via `STAGING_DEP_GATE`. DO NOT rebuild any of those.

The remaining Level-2 capabilities to build:

1. **Symbol/interface ledger** (`harness/symbol_ledger.py`, NEW module): record
   the top-level signatures actually committed by accepted tasks, and let a
   downstream task's `spec.interfaces` prose be resolved against what upstream
   siblings really produced. The ledger MUST be **lazy-derived** — read it from
   the existing `state/impl_progress.jsonl` accepted rows (`phase==accepted,
   event==auto_commit`) plus the committed files, reusing the signature
   extraction already in `harness/ast_enforcer.py`. Expose
   `resolve_interfaces(interfaces_spec: str, state_dir: Path) -> str` returning
   the input unchanged on any miss or when the flag is off.

2. **`resolve_interfaces` at the staging seam**: where the plan/task dict is
   materialized for execution (the staging/materialization path — NOT
   `prepare_task_prompt`, which never reads `spec.interfaces`), call
   `resolve_interfaces` so the resolved signatures flow through the normal
   `specification`. Gate on `config['hierarchical_planning']['symbol_ledger']`.

3. **Read-derived failure propagation**: extend the EXISTING
   `compute_epic_status` (and a small new top-level helper if needed) in
   `harness/brief_status.py` so an epic surfaces as `blocked` when a descendant
   leaf/child has failed — derived at READ time from the existing ledger/blocked
   state. Gate on `config['hierarchical_planning']['failure_propagation']`. Do
   NOT hook `orchestrator._mark_blocked` and do NOT write any new persistence;
   build on the roll-up that already exists.

4. **Planner-time depth budget**: call the already-implemented
   `check_brief_depth(slug, repo_root, max_depth)` in `harness/planner/cli.py`
   `main` (after the brief loads, before any pipeline runs), using
   `config['hierarchical_planning']['max_planner_depth']`. Refuse to plan a brief
   whose epic lineage exceeds the budget (non-zero exit). This bounds runaway
   recursion.

5. **Arbitrary-depth epic recursion**: allow a child brief that is itself an epic
   (`epic: true`) to be re-decomposed by the normal pipeline, bounded by the
   depth budget from item 4. The Phase-1 `_run_epic_pipeline` in
   `harness/planner/cli.py` writes child `brief_hooks_<slug>.md` files; the
   daemon re-plans each. Ensure a nested epic child is decomposed rather than
   treated as a leaf, with the depth gate preventing unbounded recursion.

# Non-Goals

- Do NOT edit any file on the `_NEVER_AUTO_APPROVE` deny-list: `harness/agent_jail.py`,
  `harness/dbus_proxy.py`, `harness/paths.py`, `harness/git_integration.py`,
  `harness/orchestrator.py`, `harness/interceptors.py`, `harness/selfheal.py`,
  `harness/autowork_daemon.py`, or anything under `services/`. Every child brief
  MUST land entirely outside these paths. In particular, do NOT add an eager
  `record_symbols` call inside `orchestrator._auto_commit_accepted` and do NOT
  hook `orchestrator._mark_blocked` — use the lazy-derived / read-derived designs
  above instead.
- Do NOT rebuild Phase-1 work (epic decomposition, `compute_epic_status`,
  `check_brief_depth`, containment, allowlist auto-admission).
- Do NOT add new default-off config switches beyond the existing
  `hierarchical_planning` keys (`symbol_ledger`, `failure_propagation`,
  `max_planner_depth`), which are already present and will be enabled by the
  operator. No new flags.
- Do NOT implement child-plan garbage collection in this epic (deferred).

# Inputs

- `harness/symbol_ledger.py` — does not exist yet (item 1 creates it).
- `harness/ast_enforcer.py` — reuse its signature/symbol extraction
  (`_extract_func_name_from_signature`, FunctionDef return-type extraction,
  `visit_FunctionDef`/`visit_AsyncFunctionDef`); do NOT invent a new parser.
- `state/impl_progress.jsonl` — append-only ledger; accepted rows are
  `{"phase":"accepted","event":"auto_commit","task_id","commit_sha","files":[...]}`.
- `harness/brief_status.py` — `compute_epic_status` / `compute_brief_status` /
  `compute_autowork_eligibility` (the read-derived roll-up substrate).
- `harness/planner/cli.py` — `main`, `_run_epic_pipeline`, `_should_run_epic`.
- `harness/depth_validator.py` — `check_brief_depth` (already implemented).
- `harness/config.yaml` — `hierarchical_planning` block (enabled: true;
  symbol_ledger / failure_propagation enabled by operator; max_planner_depth: 4).

# Deliverables

- `harness/symbol_ledger.py` with `record_symbols(...)` and
  `resolve_interfaces(interfaces_spec: str, state_dir: Path) -> str` (lazy-derived).
- A staging-seam call to `resolve_interfaces`, flag-gated on `symbol_ledger`.
- Extended `compute_epic_status` (+ optional top-level helper) in
  `harness/brief_status.py` for read-derived failure propagation, flag-gated on
  `failure_propagation`.
- A `check_brief_depth` budget call in `harness/planner/cli.py` `main`.
- Arbitrary-depth epic recursion in the planner, bounded by the depth budget.
- An end-to-end acceptance test proving: epic -> child briefs -> leaf tasks; a
  nested epic child is re-decomposed; depth beyond the budget is refused; a
  descendant failure surfaces the epic as blocked; interface resolution works.
- Every change committed; `auto_commit` ledger rows; no NEW test regressions.

# Implementation constraints (PROPAGATE INTO EVERY CHILD BRIEF)

Each child brief's `scope`/`deliverables` MUST carry these so the leaf planner
emits them as `implementation_notes`:

- Land entirely OUTSIDE the `_NEVER_AUTO_APPROVE` deny-list (see Non-Goals).
- A BRAND-NEW top-level symbol added to an EXISTING module must ride as a
  TRAILING extra node inside an EXISTING symbol's patch block (same patch `code`
  string, 1-part qualname) — NOT its own standalone patch entry — so the
  worker's symbol-patch apply commits cleanly. New MODULES are created as a new
  file (oracle-first).
- Do NOT modify existing class methods via partial edit (the AST merge fails on
  2-part qualnames); add NEW top-level functions/helpers instead.
- Keep each child's `verification_command` to the child's own oracle plus
  HERMETIC regression files only — never glob `tests/planner/`, never include
  tests that pip-install or touch the network (e.g. rebuild dry-runs).
- Each child is oracle-first: the test that pins the contract is a deliverable.
