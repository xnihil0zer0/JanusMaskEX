# WIRE-UP PHASE: Reachability-Detection Research

Research date: 2026-06-09. Goal: a deterministic, in-process check the pipeline can run
after building a module to PROVE it is reachable on a live (non-test) code path, so the
"orphaned module that passes an isolated oracle" defect
(`memory/implementation-is-not-wired-defect.md`) is caught mechanically instead of being
laundered into "✅ BUILT".

---

## 1. Existing import / AST analysis in the repo (REUSE, do not reinvent)

The repo ALREADY contains a production-grade, pure-stdlib intra-project import-graph
builder. This is the single most important finding: the wire-up phase should reuse it.

### `harness/rebuild/discover.py` — the reusable core
- **`module_import_graph(source_root, modules) -> dict[str, set[str]]`** (line 125).
  Returns `{module_rel: set(intra-project module_rels it imports)}`. It:
  - `ast.parse`es every module, walks the FULL tree (`ast.walk`), so it catches BOTH
    top-level AND function-local imports (line 141 comment explicitly notes lazy
    cross-module imports order/taint correctly). This matters enormously — the real
    wiring in this codebase is overwhelmingly function-local (`def f(): from harness
    import agy_pool`), see §2.
  - Handles `ast.Import` AND `ast.ImportFrom`, absolute AND relative imports
    (`_import_from_targets` + `relative_base`, importlib semantics).
  - Resolves import names to module rel-paths via `_stem_map` (registers both the dotted
    path `pkg.sub` and the leaf `sub`).
- **`discover_modules(source_root)`** (line 44) classifies every `.py` into
  `(modules, test_files, seed_files)`. Test detection: `_is_test_file` = `test_*.py` or
  `*_test.py` (line 36). Seeds: `__init__.py` / `conftest.py`. Skips `__pycache__`,
  `.git`, `state`, build/venv dirs. This is the exact non-test partitioning the wire-up
  check needs.
- `order_modules` does a topological DFS over the graph (cycles fall back to source
  order) — proof the graph primitive is trusted for ordering already.

### `harness/rebuild/deps.py` — external-vs-intra import classification
- `_from_ast` (line 196) walks module-body imports, subtracts `sys.stdlib_module_names`
  and `_intra_project_names`, to isolate external packages. `_intra_project_names`
  (line 184) is the canonical "what top-level names does THIS project own" computation.
- `external_units` / `module_has_top_level_external_import` show the established pattern
  for "does a unit reference an imported name" via an `ast.Name`-root walk (`_references`,
  line 251).

### Other AST users (context, not directly reused)
`ast.parse` appears in `git_integration.py` (symbol-patch merge), `symbol_ledger.py`,
`ast_enforcer.py`, `diff_fuzzer.py`, `test_scoper.py`, `embedded_test_runner.py`,
`orchestrator.py`. None of these build a cross-module reachability graph — they operate
within a single module. `module_import_graph` is the only import-graph builder.

### Where a wire-up phase would hook in
The build/accept chokepoints are:
- `harness/orchestrator_worker.py:_emit_gate_failure` (line 148) — the established
  pattern for logging a gate failure as a ledger row (used for smoke/embedded/narrow gates).
- `harness/orchestrator.py:_auto_commit_accepted` (line 2342) — accept→commit.
- `smoke_import` (`harness/sandbox_smoke.py`) is already called at
  `orchestrator_worker.py:509` and `orchestrator.py:3627` as a post-accept gate. A
  reachability gate is the natural sibling of the smoke gate.

---

## 2. The codebase-memory-mcp graph: capability AND its limits (EMPIRICALLY TESTED)

The MCP IS indexed and ready for this repo:
- `index_status`: project `home-xnihil0zer0-JanusMaskJR`, root `/home/xnihil0zer0/JanusMaskJR`,
  **61,460 nodes / 182,575 edges**, `status: ready`, `index_type: incremental`,
  `indexed_at 2026-06-09T04:12:36Z`. DB at `~/.cache/codebase-memory-mcp/home-xnihil0zer0-JanusMaskJR.db`.

### Edge types relevant to reachability (from `get_graph_schema`)
- `CALLS` (65,910), `IMPORTS` (3,158), `USAGE` (23,963 — read refs / callbacks /
  variable assignment), `DEFINES` (33,094, Module->Function/Class/Var), `TESTS` (3,381,
  lets us EXCLUDE test callers). Patterns include `(:Module)-[:IMPORTS]->(:Module)` [511x]
  and `(:Module)-[:IMPORTS]->(:Function)` [2,289x] — note IMPORTS frequently targets the
  specific imported SYMBOL, not the module node.
- Node `in_degree` / `out_degree` are precomputed and returned by `search_graph`.

### Dead-code detection is available — but UNRELIABLE here (false positives + false negatives)
The `codebase-memory-quality` skill recipe is:
`search_graph(label="Function", relationship="CALLS", direction="inbound",
max_degree=0, exclude_entry_points=true)`.

I tested the module-import variant against KNOWN cases and it FAILS both ways on this repo:

**FALSE NEGATIVE (graph misses real wiring):**
- `agy_pool.py` is genuinely wired NOW (`orchestrator.py:240` `from harness import
  agy_pool` then `agy_pool.worker_env(...)` line 246; `autowork_daemon.py:1070` then
  `agy_pool.allocate_slot(...)` line 1082) — both FUNCTION-LOCAL imports + QUALIFIED calls.
- `query_graph MATCH (a)-[:IMPORTS]->(b) WHERE b.name~agy_pool` → **0 rows**.
- `query_graph MATCH (a)-[:CALLS]->(b) WHERE b.name=allocate_slot` → **0 rows**.
- BUT the `agy_pool` MODULE node reports `in_degree: 4`, and `MATCH (a)-[r]->(b:Module)
  WHERE b.qualified_name=...agy_pool` DID return the 2 live importers
  (autowork_daemon.py, orchestrator.py). So the aggregate `in_degree` captured it even
  though the typed edge queries did not. The graph's function-local-import + qualified-call
  resolution is incomplete/lossy.

**FALSE POSITIVE (graph flags live modules as orphans):**
- `search_graph(label=Module, relationship=IMPORTS, direction=inbound, max_degree=0,
  file_pattern="harness/**")` flagged `state.py`, `cross_examiner.py`, `plan_validator.py`,
  `plan_normalizer.py`, `reconciliation.py`, `brief_loader.py` as zero-import.
- `state.py` has **9 live importers** by grep (orchestrator, orchestrator_worker,
  control_gate, task_decomposer, hooks/_state_gates, webui_server, track_record, ...).
  `MATCH (a)-[:IMPORTS]->(b) WHERE b.file_path='harness/state.py'` → **0 rows**.
  Reason: the IMPORTS edge points at the imported SYMBOL (`from harness.state import
  set_phase` → edge to `set_phase`), so the MODULE node's inbound-IMPORTS degree is 0.

**Conclusion on the MCP:** the graph is a good RICHER signal (call-path tracing, USAGE
edges, fan-in) but it CANNOT be the authority for orphan detection — module-level
`IMPORTS max_degree=0` over-reports orphans, and typed edge queries under-report
function-local wiring. It is also (a) an external process, (b) only as fresh as its last
incremental index (a just-built module may be unindexed), (c) caps `query_graph` at 200
rows. Use it as an OPTIONAL secondary cross-check, never the gate.

---

## 3. "Imported but never called" vs "never imported" — strongest cheap signal

Both are orphaning, but they are different defects:
- **Never imported** = no live `.py` contains `import <mod>` / `from <pkg> import <mod>`.
  This is the dominant orphan class in this repo (the wiring leaf was never authored).
  Cheap, deterministic, zero-false-negative signal: an AST import scan over live modules
  (exactly `module_import_graph` restricted to live importers). Grep confirms it
  (`agy_pool` → 2 hits; a true orphan → 0 hits).
- **Imported but never called** = a live module imports the symbol but no live code
  invokes it (dead import, or imported only to satisfy a linter / re-export). Detecting
  this robustly needs call-resolution; the pure-AST cheap approximation is
  `deps._references` (does any live unit's body reference an `ast.Name` bound to the
  import?). The MCP `CALLS`/`USAGE` inbound degree is the richer-but-lossy version.

**Strongest cheap signal = the AST import scan (`never imported`).** It is deterministic,
in-process, has no false negatives for the "wiring leaf never written" case (the actual
defect), and reuses `module_import_graph`. "Imported but not called" should be a
SECONDARY, advisory check (warn, don't hard-fail) because static call resolution is
inherently approximate (qualified calls, getattr, dispatch tables) — over-strictness
would block legitimate re-exports and registries.

The single cheapest hard gate: **is the new module in the set of intra-project import
targets of ANY live (non-test, non-oracle, non-seed) module?** If not → orphan → fail.

---

## 4. Live entrypoints / reachability roots of this system

These are the roots from which a reachability BFS should start (a module is "live" iff
some path of intra-project imports reaches it from one of these). Identified from
`if __name__=="__main__"`, `config/*hooks*.json` command strings, and `config/MEMORY.bootstrap.md`:

Pipeline / build roots (run via `python -m ...`):
- `harness/orchestrator.py`  (synthesis orchestrator; out_degree 57 in graph)
- `harness/orchestrator_worker.py`  (`python -m harness.orchestrator_worker --task-id`)
- `harness/autowork_daemon.py`  (autonomous daemon)
- `harness/planner/cli.py`  (`python -m harness.planner.cli <brief>.md`)
- `harness/sandbox.py`, `harness/rebuild/{job,loop,oracle}.py`  (rebuild engine)
- `harness/mcp_server.py`, `harness/hook_pre_tool.py`

Worker/agent hook roots (registered in `config/claude_worker_hooks.json`,
`config/gemini_settings.json`, `config/claude_worker_planning_hooks.json`):
- `harness/hooks/claude/{session_start,user_prompt_submit,pre_tool,post_tool,stop,pre_compact}.py`
- `harness/hooks/gemini/{session_start,user_prompt_submit,pre_tool,post_tool,stop}.py`

Web / overseer roots:
- `tools/webui_server.py`, `webui/app.py`, `tools/webui_control.py` (imports `overseer`)
- `overseer/procedure_hook.py` (P6 PreToolUse hook, registered into work_dir settings)

Service roots:
- `services/{bounty_gate,spawn_preflight,qualify_target,permission_model,dynamic_scheduler}.py`

Scripts (`scripts/*.py`, `tools/brief_status.py`, `scripts/brief_status.py`) are operator
CLIs — treat as roots too (a module reachable only from a script is still "wired" for a
tool-type leaf, but NOT for a harness-feature leaf — see §5 root-set selection).

NOTE: top-level entrypoints correctly have inbound-import-degree 0 (they are run, not
imported). A reachability check must therefore SEED from these roots, not flag them.

---

## 5. RECOMMENDED REACHABILITY CHECK

Design principles:
1. **In-process, pure-stdlib, deterministic** — reuse `harness.rebuild.discover.module_import_graph`.
   No MCP as a hard dependency.
2. **Seed from declared live roots** (§4) and do a BFS over intra-project imports; a
   module is WIRED iff reachable from a root WITHOUT passing through a test/oracle file.
3. **The new module's own oracle/test does NOT count** as a live importer (that's exactly
   the laundering the defect describes). Exclude `test_*.py` / `*_test.py` and
   `tests/**` from the importer set.
4. **Two-tier verdict:** hard-fail on "never imported by any live module"; soft-warn on
   "imported but no live unit references its public symbols".
5. **MCP optional enrichment:** if `index_status` is ready AND fresh, additionally report
   the module node's `in_degree` and a `trace_call_path(direction=inbound)` for the new
   public symbols — purely advisory, never flips the verdict (it both over- and
   under-reports here, §2).

### Pseudo-code

```python
# harness/wire_up.py  (NEW — pure stdlib + reuse of rebuild.discover)
from pathlib import Path
from harness.rebuild.discover import discover_modules, module_import_graph

# §4 roots, repo-relative. A module is "live" iff some import-path from one of
# these reaches it without traversing a test/oracle module.
LIVE_ROOTS = [
    "harness/orchestrator.py", "harness/orchestrator_worker.py",
    "harness/autowork_daemon.py", "harness/planner/cli.py",
    "harness/mcp_server.py", "harness/hook_pre_tool.py",
    "harness/sandbox.py", "harness/rebuild/job.py", "harness/rebuild/loop.py",
    "tools/webui_server.py", "webui/app.py", "tools/webui_control.py",
    "overseer/procedure_hook.py",
    # hooks (registered in config/*hooks*.json):
    *[f"harness/hooks/{a}/{h}.py"
      for a in ("claude", "gemini")
      for h in ("session_start","user_prompt_submit","pre_tool","post_tool","stop")],
    # services:
    *[f"services/{s}.py" for s in
      ("bounty_gate","spawn_preflight","qualify_target","permission_model","dynamic_scheduler")],
]

def _is_test_or_oracle(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    return (name.startswith("test_") or name.endswith("_test.py")
            or rel.startswith("tests/") or "/tests/" in rel)

def reachable_live_modules(repo_root: Path) -> set[str]:
    """BFS over intra-project imports from LIVE_ROOTS, never through a test/oracle."""
    modules, tests, seeds = discover_modules(repo_root)          # reuse
    all_units = modules + seeds                                   # importers can be pkg __init__
    graph = module_import_graph(repo_root, all_units)            # reuse: {mod -> {imported mods}}
    roots = [r for r in LIVE_ROOTS if r in graph]
    seen, frontier = set(), list(roots)
    while frontier:
        m = frontier.pop()
        if m in seen or _is_test_or_oracle(m):
            continue
        seen.add(m)
        frontier.extend(d for d in graph.get(m, ()) if not _is_test_or_oracle(d))
    return seen

def check_wired(repo_root: Path, new_module_rel: str) -> dict:
    """Hard reachability verdict for a freshly-built module.

    Returns {"wired": bool, "reason": str, "live_importers": [...]}.
    """
    repo_root = Path(repo_root).resolve()
    new_module_rel = new_module_rel.replace("\\", "/").lstrip("./")
    reachable = reachable_live_modules(repo_root)

    if new_module_rel in reachable:
        # Tier 1 PASS: reachable from a live root via the import graph.
        return {"wired": True, "reason": "reachable from live entrypoint", "live_importers": _direct_live_importers(repo_root, new_module_rel)}

    importers = _direct_live_importers(repo_root, new_module_rel)
    if importers:
        # Imported by a live module, but that importer itself isn't root-reachable.
        # Still a wiring gap (importer is also orphaned) — fail, name the chain.
        return {"wired": False,
                "reason": f"imported only by non-root-reachable module(s): {importers}",
                "live_importers": importers}
    # Tier 1 FAIL: no live (non-test) module imports it at all → classic orphan.
    return {"wired": False, "reason": "NO live module imports it (orphan)", "live_importers": []}

def _direct_live_importers(repo_root: Path, target_rel: str) -> list[str]:
    modules, _t, seeds = discover_modules(repo_root)
    graph = module_import_graph(repo_root, modules + seeds)
    return sorted(m for m, deps in graph.items()
                  if target_rel in deps and not _is_test_or_oracle(m))

# --- Tier 2 (advisory only): imported-but-uncalled ---------------------------
def public_symbols_referenced(repo_root, target_rel, importer_rels) -> bool:
    """True if any live importer's body references a name bound from target_rel.

    Reuse harness.rebuild.deps._references-style ast.Name walk over each importer,
    matching names bound by `from target import X` / `import target` (asname-aware).
    Soft-warn if False (dead import) — DO NOT hard-fail (qualified/dispatch calls
    are not statically resolvable).
    """
    ...  # see harness/rebuild/deps.external_units for the binding+_references pattern

# --- Optional MCP enrichment (never flips verdict) ---------------------------
def mcp_enrichment(new_module_rel) -> dict | None:
    """If codebase-memory-mcp index is ready+fresh, return node in_degree and
    inbound CALLS for the module's public symbols. Advisory context only."""
    ...  # index_status -> if ready: search_graph(file_pattern=new_module_rel) in_degree
```

### How the pipeline wires this in
Add a `wire_up` gate AFTER the existing smoke gate, at the accept chokepoint
(`orchestrator.py:_auto_commit_accepted` / `orchestrator_worker.py` near the
`smoke_import` call, line ~509). On `check_wired(...).wired == False`:
- Emit a ledger row via the established `_emit_gate_failure(state_dir, task_id,
  "wire_up", reason)` pattern (`orchestrator_worker.py:148`).
- Do NOT mark the leaf BUILT/accepted; instead surface the orphan + the required wiring
  edit (which live root/module must import+call it) so the follow-on wiring leaf is forced.

Gate it behind a config flag (e.g. `autowork.require_wire_up`, default-OFF first, mirroring
the project's default-OFF rollout convention) so it can be screened before becoming a hard gate.

### Why this beats the alternatives
- Deterministic + in-process + reuses already-trusted code (`module_import_graph` is
  used by `order_modules`/`loop.py`/`harvest.py`).
- Catches the ACTUAL defect (wiring leaf never authored → zero live importers) with NO
  false negatives, because the AST walk includes function-local imports — which is how
  `agy_pool`, the overseer FSM, etc. are wired in this codebase.
- Excludes the module's own isolated oracle from counting as "wired" (the laundering bug).
- The MCP, which is genuinely indexed and rich, is kept as OPTIONAL enrichment precisely
  because it was empirically shown to both over-report (state.py) and under-report
  (agy_pool) orphans on this repo.

### Caveats / tuning knobs
- LIVE_ROOTS must be maintained; consider auto-deriving it from `config/*hooks*.json`
  command strings + every module with `if __name__=="__main__"` (excluding `scripts/impl_*`
  and tests) so it can't drift. A drifted/too-small root set causes false orphan reports.
- Dynamic wiring (entrypoint registered only via a string in a config/registry, e.g.
  `agent_backend='claude'` selection, or hook command strings) is invisible to the import
  graph. For those, augment with a grep of `config/**` + registry tables for the module's
  dotted name. (This is exactly the `claude-tmux backend` orphan class from the defect memo
  — wired by imports but unselectable because a config string hard-codes the alternative.)
- For tools/scripts leaves, allow a script root to count; for harness-feature leaves,
  require reachability from a pipeline/daemon/hook root (not merely a script), so a
  feature reachable "only from an audit script" is still flagged unwired.
