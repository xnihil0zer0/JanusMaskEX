---
epic: true
---

<!--
# STATUS: AUTHORED (2026-06-09) — DECOMPOSITION-ONLY epic, NOT dispatched, owner gate paused.
Validated via `python -m harness.planner.cli brief_hooks_wire_up_sweep.md --dry-run` (exit 0).
This epic CONSUMES the wire-up machinery built this session (brief_hooks_wire_up_phase.md, master
6c011a5..ea4955b: harness/wire_up.py check_wired/WireResult/LIVE_ROOTS, overseer gates.wired/FSM,
plan_validator missing_wiring_oracle, accept-gate). It does NOT rebuild any of it. Where that epic
built the GATE that stops NEW orphans, this epic SWEEPS the EXISTING tree for orphans that predate
the gate, reconciles the stale root set, and lays down a permanent regression guard so the orphan
class cannot regrow.

GROUNDING — a real sweep was run at authoring time (check_wired over the full module set, graph
built once, archives/samples/scripts/tests excluded):
  - 253 total non-test modules discovered; 118 are live SOURCE (harness/** + overseer/**).
  - Under the SHIPPED LIVE_ROOTS, 50 source modules report unwired. MOST ARE FALSE POSITIVES:
    `harness/hooks/_paths.py` has 15 inbound importers yet flags ORPHAN — because the REAL hook
    entrypoints (`harness/hooks/claude/pre_tool.py`, `harness/mcp_server.py`, `harness/hook_pre_tool.py`)
    are config-referenced and ABSENT from the shipped LIVE_ROOTS constant. ROOT RECONCILIATION is
    therefore leaf #1 and a precondition for every later verdict.
  - Genuine inbound=0 candidates surfaced (must be triaged WIRE/REMOVE/RECLASSIFY): agy_pool.py,
    config_loader.py, control_gate.py, pathology_score.py, task_id_normalizer.py, planner/oracle_attach.py,
    narrow_fuzz/_registry.py, rebuild/{decompose,job,oracle,venv}.py, the 5 hooks/rpc/submit_*.py.
  - overseer/** shows as a near-total orphan cluster (turn_runner/procedure_*/tmux_* inbound≈0); memory
    confirms the subsystem is config/local-import-referenced, not import-edge-reachable from any root.
The numbers above are the EVIDENCE the epic exists to make trustworthy and durable — not the verdict.
-->

# Title

JanusMaskJR — Wire-Up Sweep. The companion to the Wire-Up Phase. That epic built the GATE that
stops *new* orphans at the accept chokepoint. This epic answers the question the gate cannot:
**which features already in the tree were "implemented" but never wired** — orphans that predate the
gate and that no accept-time check will ever revisit, because the gate only fires on freshly-built
modules. The sweep audits the ENTIRE live source tree (`harness/**` + `overseer/**`) for
reachability, RECONCILES the stale live-root set that currently poisons the verdict, cross-checks
every candidate against the codebase-memory-mcp graph to catch dynamically-wired modules the static
AST misses, and lays down a COMMITTED regression guard so a green tree can never silently regrow an
orphan. As with every JanusMask property, "wired" is decided by a pure, scripted, testable check —
never by inspection or assertion. YOU (the planner) decide the leaf tree; a non-binding suggested
grouping is at the end.

# Scope

The Wire-Up Phase closed the *forward* hole: a new module cannot merge while orphaned. But the gate
fires only on the accept path for newly-created modules — it has NEVER run against the modules
already in the tree. Our own post-mortems name three confirmed pre-gate orphans (`agy_pool.py`, the
pre-P6 procedure-gates FSM, the `claude-tmux` backend); a real sweep at authoring time shows the
backlog is larger and, more importantly, **currently unmeasurable**, because the shipped
`LIVE_ROOTS` constant is stale and produces large-scale false positives (a 15-importer module flags
as ORPHAN). The defect this epic addresses is therefore twofold:

1. **No tree-wide audit has ever run.** `check_wired` is a single-module primitive invoked by the
   accept gate; there is no driver that sweeps every source module, classifies it, and emits a
   reviewable ledger. Orphans accumulate invisibly.
2. **The root set is stale, so the audit cannot be trusted yet.** `LIVE_ROOTS` lists
   `harness/hooks/claude_hook.py` / `gemini_hook.py`, but the runtime's real hook entrypoints are
   the per-event modules under `harness/hooks/claude/**` + `harness/hooks/gemini/**`,
   `harness/hook_pre_tool.py`, and `harness/mcp_server.py` — all registered by NAME in `config/**`
   and absent from the seed set. Seeded from a stale root set, the entire hooks subsystem
   (`_paths.py`=15 importers, `_ledger.py`=13, `_state_gates.py`=12, `_common.py`=12) reports
   orphaned. A sweep is worthless until the roots are reconciled from ground truth.

The cure is a deterministic, scripted sweep delivered in two waves:

**Wave 1 — make the audit trustworthy and run it (JM-buildable now, no orphan list needed):**
reconcile the live-root set from `config/**` + `__main__` blocks; build a tree-wide classifier over
the import graph; cross-check candidates against the MCP graph as advisory enrichment; emit a single
audited ledger (`WIRE_UP_SWEEP_REPORT.md`) partitioning every source module into WIRED /
CONFIG_WIRED / ORPHAN / ORPHAN_CLUSTER; and commit a regression guard test that fails if a confirmed
orphan ever appears.

**Wave 2 — remediate (data-dependent on Wave-1's ledger):** for each CONFIRMED orphan, JM authors
one remediation leaf that does exactly one of {WIRE it into a live importer, REMOVE it as dead code,
RECLASSIFY it as a legitimate root/config entrypoint}, each proven by an edge-asserting oracle.
Wave-2 leaves CANNOT be enumerated in this brief — the orphan list is the OUTPUT of Wave 1 — so the
brief specifies the per-orphan oracle template and decision rubric, and JM fans out one leaf per
ledger row after Wave 1 lands.

# Inputs

ALREADY BUILT — do NOT rebuild; the sweep IMPORTS / WRAPS these.
Treat as fixed seams (signatures verified at HEAD 2026-06-09, this session):

- `harness/wire_up.py` — `check_wired(repo_root, new_module_rel, *, roots=LIVE_ROOTS, exclude=())
  -> WireResult(wired: bool, importers: list[str], reason: str, fix_hint: str)`, the per-module
  reachability primitive (BFS forward from `roots` over the import graph, config-grep supplement,
  own-oracle exclusion). `LIVE_ROOTS` is the seed constant — the sweep RECONCILES it, it does not
  reimplement `check_wired`. `_grep_config(repo_root, stem)` is the config-string supplement.
- `harness/rebuild/discover.py` — `discover_modules(source_root) -> (modules, tests, seeds)` and
  `module_import_graph(source_root, modules) -> {module_rel -> set(intra-project imports)}`. The
  graph AST-walks the FULL tree so it catches FUNCTION-LOCAL imports (how most wiring in this repo
  actually works). The sweep builds this graph ONCE and reuses it — calling `check_wired` per module
  rebuilds the graph each time (O(n²); the authoring sweep timed out that way — proven).
- `overseer/gates.py::wired(report) -> GateResult` and `overseer/gate_runner.py` dispatch — the
  accept-time gate from the prior epic. The sweep does NOT touch the gate; it audits modules the
  gate never saw.
- `codebase-memory-mcp` — indexed for this repo (61,598 nodes / 182,775 edges, fresh 2026-06-09),
  exposing CALLS / IMPORTS / USAGE / DEFINES / TESTS edges via `query_graph` / `search_graph` /
  `trace_call_path`. ADVISORY ONLY (see below) — never the gate.

# The sweep model (what the audit computes, and the MCP's exact role)

The sweep is a pure function over the import graph plus an advisory MCP overlay:

- **Source set** = `discover_modules`' non-test modules, MINUS `_archive/**`, `_autowork_archive/**`,
  `samples/**`, `scripts/**`, `tests/**`, `venv/**` (these are not meant to be import-reachable; the
  authoring sweep's 176 raw "orphans" collapse to ~50 source candidates once filtered, and to far
  fewer once the roots are reconciled). State this filter explicitly in the report header.
- **Reconciled roots** = the SHIPPED `LIVE_ROOTS`, UNIONED with entrypoints discovered from ground
  truth: every module named in a `config/**` hook/entrypoint table, every module carrying an
  `if __name__ == '__main__'` block, and the service/web entrypoints. Derived by a pure
  `discover_live_roots(repo_root)` — reads `config/**`, greps `__main__`. The reconciliation is
  itself a fixable defect in `LIVE_ROOTS` (leaf #1 corrects the constant AND adds the discoverer).
- **Classification** of each source module, from the BFS-reachable set over the reconciled roots:
  - **WIRED** — at least one reachable live importer (excluding the module's own oracle).
  - **CONFIG_WIRED** — no static importer, but referenced by stem in `config/**` (dynamic wiring,
    e.g. the hook entrypoints, `claude-tmux`). PASS, but listed so the config-only set is auditable.
  - **ORPHAN_CLUSTER** — inbound importers EXIST but NONE is reachable from a root (a connected
    component of modules that import each other yet hang off no entrypoint). This is the subtle class
    the per-module gate obscures; it requires component-level triage, not a single-module fix.
  - **ORPHAN** — zero inbound importers and no config reference. The dominant, unambiguous class.
- **MCP advisory cross-check** — for every ORPHAN / ORPHAN_CLUSTER candidate, query the MCP graph
  for inbound CALLS / IMPORTS / USAGE edges. The MCP sees some dynamic/runtime wiring the static AST
  cannot. Its role is STRICTLY to RAISE DISAGREEMENTS for human triage: "static says orphan, MCP
  shows N inbound usages → likely dynamic wiring, do not auto-remove." It NEVER flips a verdict
  automatically and NEVER gates. (Proven unreliable both ways: it flags live `state.py` with 9 real
  importers as zero-import because IMPORTS edges target the symbol not the module node, and it MISSES
  `agy_pool`'s genuine function-local wiring. Authoritative gate = the in-process AST check;
  MCP = enrichment in the report only.)

# THE TRAP — the sweep tooling must itself be wired (READ BEFORE AUTHORING)

The Wire-Up Phase's cardinal lesson applies recursively: it would be self-parody to land an
orphaned wire-up SWEEP. Every new module this epic adds (the root discoverer, the sweep
classifier, the MCP cross-checker) must itself be reachable from a live root or the runner that
invokes it, and each ships an EDGE-ASSERTING oracle, never an isolated unit test that merely proves
the function computes.

1. **`discover_live_roots` and the sweep classifier are EDITS/additions to `harness/wire_up.py`** (an
   already-WIRED module — `harness/orchestrator.py` imports `check_wired`), so they ride an existing
   live import edge and are born reachable. Prefer extending `harness/wire_up.py` over a brand-new
   module wherever the addition is a pure function, precisely to avoid minting a fresh orphan.
2. **The sweep RUNNER** (the thing operators invoke to regenerate the ledger) must be reachable. A
   `scripts/**` runner is acceptable for the human-invoked report, BUT the load-bearing durable
   artifact is NOT the script — it is the COMMITTED REGRESSION-GUARD TEST (`tests/harness/
   test_no_source_orphans.py`) that imports the live classifier and asserts zero confirmed orphans.
   That test is what makes the property permanent; the script is a convenience.
3. **EDGE-ASSERTING oracles only.** The root-reconciliation oracle must assert that, with the
   reconciled roots seeded, the high-inbound hooks cluster (`_paths.py`, `_ledger.py`) is NO LONGER
   orphan AND that a synthetic true-orphan still is — driving the real graph, not a mock. The
   classifier oracle drives a fixture import graph and asserts each of the four classes lands
   correctly, archives/samples excluded, own-oracle excluded. The MCP-crosscheck oracle feeds a
   stubbed MCP client and asserts disagreements are RAISED, never auto-applied.

# Correctness regimes (the build boundary)

DETERMINISTIC logic — `discover_live_roots`, the sweep classifier, the report serializer, the
regression-guard assertion — is fully JM-rebuildable and MUST be pure/stdlib-only over INJECTED
seams (the import graph via `discover`, the root set as a parameter, plain filesystem reads of
`config/**`). It NEVER spawns a process, makes a model/API call, or shells out un-injected. The MCP
cross-check is the ONE seam that touches an external service; it MUST take the MCP query function as
an INJECTED callable so the oracle drives it with a stub (no live MCP call in any test), and it is
ADVISORY — its output decorates the report and never changes a verdict or gates a build.

THE CARDINAL PROJECT RULE this epic obeys: NEVER hand-edit production outside the pipeline. The
LIVE_ROOTS reconciliation and every classifier line route through planner → stage → worker. Edits to
`harness/wire_up.py` are protected-path writes ⇒ meta_task_type=harness_self_fix + an operator
decision file, exactly as the Wire-Up Phase's three protected writes were handled.

# Per-leaf contract (oracle-first)

Each leaf's `verification_command` names its own pre-committed RED oracle as
`python -m pytest tests/<area>/<oracle>.py -q`; oracles are HAND-AUTHORED + committed BEFORE any
leaf is dispatched (the next gated step after this digestion). Wave-1 additions to
`harness/wire_up.py` are EXISTING-symbol-adjacent edits to ONE file; a brand-new module (if JM
chooses one for the sweep driver) is a single-file whole-file emission. Every leaf that adds a
call/import edge ships an EDGE-ASSERTING oracle per THE TRAP; only a genuinely-pure new primitive
may use an isolated oracle, and only if a sibling leaf wires it.

# Suggested decomposition (NON-BINDING — you decide the final tree)

WAVE 1 — trustworthy audit + permanent guard (deterministic, JM-buildable now):

- **Root reconciliation.** EDIT `harness/wire_up.py`: add `discover_live_roots(repo_root) ->
  list[str]` (reads `config/**` hook/entrypoint tables + greps `if __name__ == '__main__'` blocks +
  the known service/web entrypoints; unions with the shipped `LIVE_ROOTS`) and make the sweep seed
  from it. → `tests/harness/test_live_root_reconciliation.py`: drives the REAL graph and asserts the
  config hook entrypoints (`harness/hooks/claude/pre_tool.py`, `harness/mcp_server.py`,
  `harness/hook_pre_tool.py`) are in the reconciled roots, AND that `harness/hooks/_paths.py`
  (15 importers — the proven false positive) is WIRED under the reconciled roots, AND that a
  synthetic zero-importer module is still ORPHAN. `dependencies: []`.

- **Sweep classifier + report.** ADD `sweep_modules(repo_root, *, roots) -> SweepReport` (builds the
  graph ONCE, applies the source-set filter, classifies every module WIRED / CONFIG_WIRED /
  ORPHAN_CLUSTER / ORPHAN, serializes a deterministic sorted JSON + `WIRE_UP_SWEEP_REPORT.md`).
  Prefer adding to `harness/wire_up.py` (born-wired). → `tests/harness/test_sweep_classifier.py`:
  drives a fixture import graph + fixture config dir and asserts each of the four classes lands on
  the right module, archives/samples/scripts excluded, own-oracle excluded, output deterministic
  (sorted). `dependencies: [root-reconciliation]`.

- **MCP advisory cross-check.** ADD a cross-checker taking the MCP query as an INJECTED callable:
  for each static ORPHAN/ORPHAN_CLUSTER it queries inbound CALLS/IMPORTS/USAGE and appends a
  DISAGREEMENT note to the report when the MCP shows inbound edges. → `tests/harness/
  test_mcp_crosscheck_advisory.py`: feeds a STUB MCP client (no live call); asserts a disagreement is
  RAISED into the report and that the verdict is UNCHANGED (advisory, never gates). `dependencies:
  [sweep-classifier]`.

- **Regression guard (the durable deliverable).** ADD `tests/harness/test_no_source_orphans.py`: a
  committed test that runs `sweep_modules` over the live source tree and asserts ZERO confirmed
  ORPHANs, modulo an EXPLICIT, reviewed allowlist of intentionally-deferred modules (each allowlist
  entry carries a one-line justification). This is what makes the property permanent — once Wave 2
  remediates, the orphan class cannot silently regrow. Its own `verification_command` IS this test.
  `dependencies: [sweep-classifier, mcp-crosscheck]`.

WAVE 2 — remediation (data-dependent; JM fans out AFTER Wave 1's ledger exists):

- For each row classified ORPHAN (or an ORPHAN_CLUSTER component) in `WIRE_UP_SWEEP_REPORT.md`, JM
  authors ONE remediation leaf choosing exactly one verdict by this rubric:
  - **WIRE** — the feature is intended-live but its wiring leaf was never authored: add the missing
    import/call edge from a module already reachable from a root. Oracle: re-run `check_wired` over
    the module post-fix and assert WIRED with the new importer named (edge-asserting), plus the
    behavior the wiring enables.
  - **REMOVE** — the module is genuinely dead (no caller, superseded, scratch). Oracle: assert the
    module is gone AND the full suite stays green (nothing referenced it). Route protected-path
    deletes through the pipeline like any other change.
  - **RECLASSIFY** — the module IS a legitimate entrypoint or config-wired surface mis-seen as an
    orphan: add it to the reconciled roots / confirm its `config/**` reference, and move it to the
    regression-guard allowlist with justification. Oracle: assert it now classifies CONFIG_WIRED or
    root, not ORPHAN.
  - Each Wave-2 leaf is `dependencies: [regression-guard]` so it cannot land before the guard exists
    to ratify it. The known inbound=0 candidates from the authoring sweep (agy_pool, config_loader,
    control_gate, pathology_score, task_id_normalizer, planner/oracle_attach, narrow_fuzz/_registry,
    rebuild/{decompose,job,oracle,venv}, hooks/rpc/submit_*) and the overseer cluster are the LIKELY
    Wave-2 inputs — but the BINDING list is whatever Wave 1's reconciled ledger reports, NOT this
    pre-reconciliation snapshot.

# Bootstrap dogfood acceptance (MANDATORY, manual, once)

After the root-reconciliation + classifier leaves merge: run `sweep_modules` over the live tree and
confirm (a) `harness/hooks/_paths.py` classifies WIRED (the false positive is cured), (b)
`harness/wire_up.py` itself classifies WIRED (importer = `orchestrator` — the tool is not its own
orphan), and (c) a known-orphan fixture still classifies ORPHAN. Record the result. Only with this
dogfood green is the Wave-1 ledger trustworthy enough to drive Wave-2 remediation.

# Deliverables

A decomposed Wave-1 leaf tree (one `brief_hooks_<slug>.md` per leaf at repo root) plus an epic plan
record, covering: the live-root reconciliation (edit to `harness/wire_up.py` + `discover_live_roots`),
the tree-wide sweep classifier + `WIRE_UP_SWEEP_REPORT.md` producer, the injected MCP advisory
cross-check, and the committed `tests/harness/test_no_source_orphans.py` regression guard. Each leaf
names its own pre-committed RED oracle as its `verification_command`; every edge-adding leaf ships an
edge-asserting oracle. The end state of Wave 1: a trustworthy, reproducible orphan ledger over the
real source tree, a root set reconciled from ground truth, and a permanent guard that fails CI the
instant a confirmed orphan reappears. Wave 2 is then a data-driven fan-out — one wire/remove/
reclassify leaf per ledger row. This epic delivers the DECOMPOSITION ONLY: it authors no oracle and
builds/dispatches no leaf; the owner gate stays paused.

# Non-Goals

No new agent spawns, model/API/network calls, or un-injected subprocesses in the deterministic
leaves — the import graph, root set, config reads, and MCP query all flow through injected seams so
oracles drive them hermetically (the MCP is stubbed in tests; no live MCP call in any oracle). No
reimplementation of `check_wired`, `discover.module_import_graph`, or the accept-time wired gate —
the sweep WRAPS them. The codebase-memory-mcp graph is ADVISORY enrichment only, never a verdict and
never a gate (it is proven unreliable both ways). The sweep proves REACHABILITY, not USEFULNESS: a
module wired by a trivial inert importer passes — code review and the mutation gate remain the
backstop for "wired but inert" (stated, not silently covered). Dynamically/reflectively-registered
wiring beyond the `config/**` grep + MCP overlay is a stated blind spot. Wave-2 remediation leaves
are NOT authored here — they are data-dependent on Wave 1's ledger and fanned out afterward. This
epic is DECOMPOSITION ONLY: it authors no oracle and dispatches no build; the owner gate stays paused.
