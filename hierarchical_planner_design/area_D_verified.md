# Area D — Cross-Cutting Hierarchical State: Symbol/Interface Ledger, Failure Propagation, Recursion Safety (VERIFIED)

> Adversarial review of `gemini_area_D_crosscutting_state_recursion.md` against actual source @ branch `master`.
> This is the **most speculative / deferred** tier (Level 2). The verified design below is deliberately TRIMMED toward a minimal viable shape. See §9 for what was hallucinated/over-engineered and §10 for the Level-1/Level-2 boundary.

## 1. Summary

Area D is the **Level-2 cross-cutting runtime tier**, explicitly **deferred** past the first hierarchical-planner build. It comprises four capabilities, each **default-off / fail-closed**:

1. **Symbol/interface ledger** — a registry that flows produced symbol *signatures* downward across subtrees, so a dependent task's `spec.interfaces` (today a free-form string — Area B Level-1) can be *resolved* against what upstream tasks actually committed.
2. **Parent/child-aware completion ledger** — arbitrary-depth roll-up of completion state, generalizing the single-task `STATE.json` (`parent_task`, `children`, `decomposed`) and the append-only `state/impl_progress.jsonl` event log.
3. **Failure propagation** — make a failed descendant fail its ancestor *epic* without deadlocking siblings. Today failure is **contained** (dependents simply never become ready) but is **not positively propagated** to ancestors.
4. **Recursion safety** — depth/subtask budgets. These **already exist** at Level 1 (`decomposition.max_depth`, `decomposition.max_subtasks`, `depth_validator.check_true_depth`); Area D only *generalizes* the budget to planner-time arbitrary-depth DAGs.

The biggest correction vs. the draft: **most of the recursion-safety machinery already exists**, and **failure containment already exists** via `STAGING_DEP_GATE`. The genuinely new Level-2 work is narrow.

## 2. Existing Substrate (corrected anchors)

- **`harness/config.yaml`** — flat YAML, loaded as a plain dict by `orchestrator.load_config()` (`orchestrator.py:118`, `yaml.safe_load`). Relevant blocks:
  - `decomposition:` at **L79** with `max_depth: 2` (**L81**) and `max_subtasks: 5` (**L82**). NB: config value is **2**, but the in-code default fallback is **3** (`task_decomposer.py:291`, `depth_validator.check_true_depth(..., max_depth=3)`).
  - `autowork:` block **L42-58**. Real default-off / fail-closed flags to copy as a convention model: `enabled: false` (L51), `selfheal_auto_promote: true` (L58), `auto_approve_ro_gate: true` (L43), `auto_approve_sensitive_harness: true` (L44).
- **Config read convention** — *Plain dict `.get()` access is the norm*, e.g. `config['autowork'].get('auto_approve_ro_gate')` (`orchestrator.py:2658`) and `config.get('decomposition', {}).get('max_depth', 3)` (`task_decomposer.py:289-291`). The `@dataclass` validators in `config_loader.py` (`HooksConfig` L37-87 / `get_hooks_config` L90-111; `BatchExecutionConfig` L113 / `get_batch_execution_config` L149) are the **exception**, used only for the two most safety-critical blocks — NOT the default mechanism.
- **`state/STATE.json`** — single active-task object (`state.py:_state_file`, L19-20). Real fields: `task_id, round, phase, claude_status, gemini_status, antigravity_status, status_updated_at_epoch, fuzz_results, cross_exam_round, decomposed, parent_task, children, handoff_pending`. Mutated under a file lock via `locked_read_modify_write` (`state.py:67`). **It tracks ONE task, not a tree.**
- **`state/impl_progress.jsonl`** — append-only event ledger (`write_jsonl_row`). Verified event/phase vocabulary: `task_claim, ast_validation, ast_validation_failed, cross_examination, fuzzing, accepted, rejected, auto_commit, task_blocked, retry_budget_exhausted, retry_exhausted, decomposition, task_terminal, autowork, agent_status, phase_transition`. The canonical "accepted" row is written at **`orchestrator.py:3073`** with shape `{"ts","phase":"accepted","task_id","event":"auto_commit","commit_sha","files":[...],"exit":0}`.
- **`harness/orchestrator.py`** (4196 lines):
  - `_auto_commit_accepted` — defined at **L2150**, **988 lines (L2150-3138)**. ❗ MASSIVE RED-ZONE function. Draft's "L3578" is the *call site* (L3578), not the def.
  - `prepare_task_prompt` — **L1356-1406** (top-level fn, 50 lines). Confirmed. Builds prompt from `task['specification']` — it does **NOT** read `spec.interfaces`.
  - Orphan/crash reclaim — **L3603-3613** routes a still-`.processing` task to `blocked/` via `_mark_blocked` (single-level, serial-loop only). Confirmed.
  - `_mark_blocked` (**L1763**) / `_write_retry_sidecar` (**L1740**) — route a non-accept terminal to `state/tasks/blocked/` + `{attempts,last_outcome,ts}` sidecar.
  - `get_next_task` (**L1249**) — dependency gate at **L1306-1311**: a candidate is skipped while any `dependencies`/`depends_on` entry is not in `accepted_names`. Depth gate at L1313 (`check_true_depth`).
- **`harness/autowork_daemon.py`**:
  - `STAGING_DEP_GATE` (**L1346-1359**) — when a dependency was *processed* but is NOT in the accepted-set, the dependent is **skipped from staging**. Accepted-set built from `impl_progress.jsonl` `phase==accepted, event==auto_commit` rows (L1306-1324). **This is the existing failure-containment primitive.**
  - `_retry_blocked_tasks` (**L883**) — re-stages blocked tasks under a budget; `.exhausted` marker guard (L911); emits `retry_exhausted`.
  - `_auto_promote` (**L1204**).
- **`harness/depth_validator.py`** — `check_true_depth(task_id, tasks_dir, max_depth=3)` at **L6-75** (NOT L6-75 "validates lineages" loosely — it walks `parent_task`/`parent_task_id` up `tasks/` then `tasks/processed/`, cycle-guarded, returns `False` if depth > max_depth). **There is no line 45 "claim-time enforcement" symbol** as the draft's edit table implies — L45 is inside the loop body of the single function.
- **`harness/ast_enforcer.py`** — ALREADY has signature/symbol primitives: `_extract_func_name_from_signature` (L268), FunctionDef return-type extraction (L358-386), `visit_FunctionDef`/`visit_AsyncFunctionDef`. **Any ledger AST extraction must reuse these, not invent a parser.**
- **`harness/selfheal.py`** — the synth-plan pattern to imitate: `_synthesize_selfheal_plan` (L50) writes `plan_hooks_selfheal_<tid>.json`; `_harvest_selfheal_briefs` (L225) is the harvest loop; HMAC provenance gating (`_selfheal_secret` L132, `_selfheal_provenance_valid` L188).

## 3. Required Changes (corrected)

| Change | TRUE Anchor | New/Mod | Viability | Oracle-First | harness/? | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| Add `hierarchical_planning:` config block (`enabled: false`, `symbol_ledger: false`, `failure_propagation: false`, `max_planner_depth: 4`) | `config.yaml` (append, ~L114) | Modify | `[GREEN config-only]` | No | Yes | Flat YAML. NO dataclass needed — read via `config.get('hierarchical_planning', {}).get(...)` per the dict convention. |
| (OPTIONAL) `HierarchicalPlannerConfig` dataclass | `config_loader.py` (append after L170) | New | `[GREEN single-symbol]` | Yes | Yes | Only if validation is wanted. The dict convention makes this **optional / not Level-2-blocking**. |
| New module: symbol ledger writer/reader | `harness/symbol_ledger.py` | New file | `[GREEN new-file, oracle-first]` | Yes | Yes | Top-level fns only. Reuse `ast_enforcer` extraction. |
| Record symbols on acceptance | call-site near `orchestrator.py:3073` (the accepted row) — **as a one-line call to a NEW helper**, NOT an in-place edit of the 988-line body | Modify (1 line) | `[YELLOW — RED-ZONE host fn]` | Yes (oracle on helper) | Yes | ❗ Do NOT partial-edit `_auto_commit_accepted`. Add a guarded one-liner `record_symbols(...)` behind the flag. Prefer deriving the ledger *lazily* from existing `accepted`+`files` rows (see §7) to avoid touching this fn at all. |
| Resolve `spec.interfaces` against ledger | plan **staging / materialization** path (where the task dict is written), NOT `prepare_task_prompt` | Modify | `[YELLOW multi-symbol]` | Yes | Yes | ❗ Draft put this in `prepare_task_prompt` which never reads `spec.interfaces`. Resolve at staging so the resolved string flows through the normal `specification`. |
| Failure propagation to ancestor epic | new top-level helper invoked from `_mark_blocked` (`orchestrator.py:1763`) tail | Modify (call) + New fn | `[YELLOW]` | Yes | Yes | `_mark_blocked` is ~30 lines — appending a guarded call is GREEN-ish. The propagation logic lives in a NEW top-level fn. |
| Generalize depth budget to planner DAG | reuse existing `check_true_depth`; add a planner-time `max_planner_depth` check in the planner, not `depth_validator.py:45` | Modify | `[GREEN]` | Yes | Yes | ❗ No edit at `depth_validator.py:45`. The existing fn already short-circuits; only the planner needs a budget check. |

## 4. New Symbols / New Files (corrected, minimized)

- **`harness/symbol_ledger.py`** (New module — top-level fns only, no classes):
  - `def record_symbols(state_dir: Path, files_touched: list[str], task_id: str, commit_sha: str | None) -> None` — extract committed top-level signatures (reuse `ast_enforcer` helpers) and append rows to `state/symbol_ledger.jsonl`. Fail-closed: any parse/IO error is swallowed (best-effort), never raises into the commit path.
  - `def resolve_interfaces(interfaces_spec: str, state_dir: Path) -> str` — best-effort substitution of placeholder signatures with ledger entries. Returns input unchanged on miss/flag-off.
- **Failure propagation** — recommended as a SMALL top-level helper, e.g. `def mark_epic_blocked_on_failure(state_dir, failed_id, reason) -> list[str]` either in `orchestrator.py` (top-level) or a thin new module. **Do NOT create a whole `failure_propagator.py` module of machinery** — see §7/§9.

### `state/symbol_ledger.jsonl` row shape (grounded in `impl_progress.jsonl` conventions)
```json
{"ts": "2026-06-05T...Z", "task_id": "...", "commit_sha": "...",
 "file": "harness/foo.py", "symbol": "foo.bar", "kind": "function",
 "signature": "def bar(x: int) -> str"}
```
Append-only JSONL, one row per symbol, mirroring `write_jsonl_row`. This GENERALIZES Area B's Level-1 `spec.interfaces` *string*: Level 1 declares the interface statically up front; Level 2 records the *actually-committed* signature and lets dependents resolve against it.

## 5. Data-Flow / Sequence (corrected)

### Symbol resolution (seam corrected)
```
[Task A accepted] --(orchestrator.py:3073 accepted row, files=[...])-->
   record_symbols()  ->  state/symbol_ledger.jsonl  (append, flag-gated, best-effort)

[Task B staged]  (depends_on A, A in accepted-set)
   plan staging materializes B's task dict
        -> resolve_interfaces(B.spec.interfaces)  reads ledger, substitutes
        -> B.specification carries the resolved signature
   prepare_task_prompt(B)  -- unchanged; just renders B.specification
```
(Draft incorrectly injected at `prepare_task_prompt`, which does not read `spec.interfaces`.)

### Failure containment vs. propagation (corrected to reflect reality)
```
TODAY (containment, already works):
  Child fails -> _mark_blocked -> tasks/blocked/<child>.json  (NOT accepted)
  Dependent never enters accepted-set -> STAGING_DEP_GATE skips it
  Siblings WITHOUT that dep stage normally  (no deadlock)
  *** Ancestor epic is NOT marked failed -> can appear "in progress" forever ***

LEVEL-2 ADDITION (propagation):
  _mark_blocked(child) tail -> mark_epic_blocked_on_failure(child)
      walk parent_task chain (reuse depth_validator's walk semantics)
      append a 'task_blocked'-style row for each ancestor epic id
      DO NOT touch sibling subtrees
```

## 6. Dependencies & Ordering

1. **Level 1 prerequisite**: static `spec.interfaces` (Area B), sibling dependency edges + `STAGING_DEP_GATE` (already in `autowork_daemon.py`), `decomposition.max_depth/max_subtasks`, `check_true_depth` — all EXIST.
2. **Level 2 sequence**: (a) config flags land first (default-off); (b) `symbol_ledger.py` writer/reader oracle-first; (c) flag-gated `record_symbols` one-liner at the accepted row; (d) flag-gated `resolve_interfaces` at staging; (e) failure-propagation helper at `_mark_blocked` tail; (f) planner-depth budget. Each independently flag-gated so partial landing is safe.

## 7. Over-Engineering Check / Minimal Viable Design

- ❌ **`failure_propagator.py` as a module** — over-built. Failure *containment* already exists (`STAGING_DEP_GATE`, `get_next_task` accepted-gate). The ONLY gap is *announcing* ancestor failure. That is one small top-level fn appending ledger rows — not a module, not a recursion engine. The "avoid sibling deadlock" requirement is **already satisfied** by independent staging; no new code needed for it.
- ❌ **Separate completion-ledger store** — unnecessary. Arbitrary-depth roll-up can be COMPUTED on demand from `impl_progress.jsonl` (accepted/blocked rows) + `parent_task` chains. Do NOT introduce a second persisted tree-state file that can desync from STATE.json/the ledger.
- ❌ **In-place edit of `_auto_commit_accepted`** (988 lines) — forbidden by the "large-symbol partial_edit truncates" rule. Best path: derive the symbol ledger **lazily** in `symbol_ledger.py` from the already-emitted `accepted`+`files`+`commit_sha` rows, so `_auto_commit_accepted` is **not touched at all**. Second choice: a single guarded one-liner call.
- ❌ **New AST parser** — reuse `ast_enforcer.py` signature extraction.
- ❌ **Config dataclass requirement** — optional; the dict `.get()` convention is the norm.
- ✅ **Minimal viable Level 2** = (1) one `hierarchical_planning:` config block; (2) `symbol_ledger.py` that LAZILY reads existing accepted rows + git to expose signatures, and `resolve_interfaces` used at staging; (3) a ~15-line `mark_epic_blocked_on_failure` appended at `_mark_blocked`'s tail. Nothing else.

## 8. Viability Tags + Class-Method Red-Zone Check

- `prepare_task_prompt` — **top-level fn, GREEN** to edit (but it's the WRONG seam — see §3/§5).
- `_auto_commit_accepted` — **top-level fn but 988 lines: hard RED-ZONE for partial_edit.** Reshape to lazy-derive or single-line guarded call.
- `_mark_blocked` (~30 lines) — top-level, GREEN to append a guarded call.
- `check_true_depth` / `depth_validator.py` — single top-level fn, GREEN; but no edit needed (reuse).
- `record_symbols`, `resolve_interfaces`, `mark_epic_blocked_on_failure` — NEW top-level fns in NEW/existing modules: oracle-first GREEN.
- Config block — config-only, no symbol edit.
- **No class methods are involved**, so the 2-part-qualname AST-fail red-zone does not bite — provided new symbols are added as top-level fns (and, if appended to an existing symbol's patch, as a trailing node per the harness convention).

## 9. Adversarial Review Findings

**Hallucinated / wrong machinery removed:**
1. **`failure_propagator.py` module** — over-engineered; reality already contains/avoids the hard parts (containment + sibling-non-deadlock). Reduced to one small helper.
2. **`prepare_task_prompt` as the interface-resolution seam** — FALSE. `prepare_task_prompt` (L1356) builds the prompt from `task['specification']` and never reads `spec.interfaces`. Re-seated resolution at plan staging.
3. **`_auto_commit_accepted` at `orchestrator.py:3578`** — WRONG anchor. The def is at **L2150** (988 lines, L2150-3138); 3578 is the *call site*. The accepted ledger row is at **L3073**. Editing the body in place is forbidden by the large-symbol rule.
4. **Edit at `depth_validator.py:45`** — there is no enforcement symbol at L45; the whole module is one function (`check_true_depth`, L6-75). No edit needed — reuse.
5. **`config_loader.py` as the config mechanism** — MISLEADING. The codebase reads flags via plain `config.get(...)`; the dataclasses are the exception. The new flag needs NO dataclass.
6. **Separate persisted completion-ledger** — invented; roll-up is computable from existing ledger + `parent_task` chains.

**Confirmed-correct in the draft:**
- `prepare_task_prompt` at L1356 (anchor right, seam wrong) — ✅ line.
- `check_true_depth` at L6-75 — ✅.
- Crash reclaim region L3603-3613 — ✅ (it's single-level orphan-routing via `_mark_blocked`).
- "Failure is single-level today" — ✅ TRUE in the propagation sense; refined: it's *containment*, not *propagation*.
- Default-off / fail-closed mandate — ✅ correct and matches `selfheal_auto_promote`/`auto_approve_ro_gate` convention.

**Per-claim confidence:**
- Symbol-ledger feasibility & seam (lazy-from-accepted-rows): HIGH.
- Interface resolution belongs at staging, not prompt: HIGH (verified `prepare_task_prompt` source).
- Failure containment already exists (`STAGING_DEP_GATE`): HIGH (quoted L1346-1359).
- Multi-level propagation feasible via `parent_task` walk: MEDIUM-HIGH (semantics proven by `check_true_depth`/`_resolve_files_touched` walks; not yet wired).
- Recursion budgets already exist: HIGH (`config.yaml:79-82`, `task_decomposer.py:289-293`, `depth_validator.py`).
- Config mechanism = plain dict: HIGH (quoted call sites).

## 10. Level Boundary (Level 2 deferred vs. pull-forward to Level 1)

**Genuinely Level 2 (defer):**
- Symbol/interface LEDGER (`symbol_ledger.jsonl`) + `resolve_interfaces` runtime substitution.
- Active **failure PROPAGATION** to ancestor epics (announcing ancestor failure).
- Arbitrary-depth completion roll-up (computed view).

**Already Level 1 / already exists (do NOT rebuild in Area D):**
- Recursion safety: `decomposition.max_depth`/`max_subtasks` + `check_true_depth` + the `is_structural_decomposition_applicable` depth guard. Area D only adds a *planner-time* `max_planner_depth` budget — a thin reuse.
- Failure CONTAINMENT + sibling non-deadlock: already provided by `STAGING_DEP_GATE` and the `get_next_task` accepted-gate.
- Static `spec.interfaces` declaration: Area B Level 1. Level 2 generalizes it; it must not contradict it.

**Candidate to pull FORWARD into Level 1 (cheap, high value):**
- The planner-time `max_planner_depth` budget check is trivial (reuse `check_true_depth` semantics) and could ship with Level 1 to bound DAG depth at plan generation, independent of the rest of Area D.
