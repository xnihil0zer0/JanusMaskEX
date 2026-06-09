---
epic: true
---

<!--
# STATUS: AUTHORED (2026-06-09) — Wave-2 remediation epic, DECOMPOSITION-ONLY, owner gate paused.
Consumes the Wave-1 sweep tooling (master ..6744b1a, PUSHED): harness/wire_up.py check_wired /
discover_live_roots / sweep_modules / SweepReport / mcp_crosscheck, the committed regression guard
tests/harness/test_no_source_orphans.py + its 36-module justified allowlist, and the audit ledger
WIRE_UP_SWEEP_REPORT.md. This epic does NOT rebuild any of it; it REMEDIATES the 36 confirmed
orphans the Wave-1 audit baselined. Validate with `python -m harness.planner.cli
brief_hooks_wire_up_remediation.md --dry-run` (exit 0). Suggested as MULTI-LEVEL: a top epic that
decomposes into per-CATEGORY sub-epics, each fanning into per-MODULE leaves — but JM decides the tree.
-->

# Title

JanusMaskJR — Wire-Up Remediation (Wave 2). The Wave-1 sweep made the orphan backlog MEASURABLE:
36 source modules are confirmed unwired (21 ORPHAN with zero importers, 15 ORPHAN_CLUSTER whose
importers hang off no live root), baselined with justifications in the regression guard's allowlist.
This epic DISCHARGES that backlog: for each confirmed orphan it applies exactly one verdict —
**WIRE** it into a live importer, **REMOVE** it as dead, or **RECLASSIFY** it as a legitimate
entrypoint / config-wired surface — each proven by an edge-asserting oracle, and each shrinking the
guard's allowlist by exactly its module. The terminal acceptance is structural: when the backlog is
discharged, `tests/harness/test_no_source_orphans.py` passes with a SMALLER allowlist, and no module
is both un-allowlisted and orphaned. YOU (the planner) decide the tree; a multi-level grouping by
category is suggested at the end. Read the codebase to assign each module's verdict — do not guess.

# Scope

The Wave-1 gate stops NEW orphans; it never remediates the ones already in the tree. Those 36 are
real debt: a module that no live path reaches is either (a) a feature whose wiring leaf was never
authored (WIRE), (b) dead code that should not exist (REMOVE), or (c) a genuine entrypoint / a
surface the runtime resolves dynamically that the static graph cannot see (RECLASSIFY). The defect
is that today they are indistinguishable — all 36 sit in one allowlist marked "pending Wave-2." This
epic resolves each into its true verdict, with EVIDENCE, and lands the fix through the pipeline.

The cure is one remediation unit per confirmed orphan, each:
1. **Triaged with evidence** (read the module + the codebase): is it imported anywhere — even
   dynamically (importlib, a config/hook dispatch table, a plugin registry)? Does it carry an
   `if __name__ == '__main__'` CLI entrypoint? Is its stem referenced in `config/**`? The answers
   pick the verdict.
2. **Remediated by exactly ONE verdict** (see the rubric).
3. **Proven by an edge-asserting oracle** that drives the live path, not an isolated unit test.
4. **Reconciled against the guard**: the module's entry is removed from
   `KNOWN_ORPHAN_ALLOWLIST` so the guard tightens; the guard must stay green.

# Inputs

ALREADY BUILT — do NOT rebuild; remediation leaves IMPORT / CONSUME these (verified at HEAD
`6744b1a`, PUSHED 2026-06-09):

- `harness/wire_up.py` — `check_wired(repo_root, module_rel, *, roots, exclude) -> WireResult`,
  `discover_live_roots(repo_root) -> list[str]` (the reconciled live-root set; SEED check_wired from
  it), `sweep_modules(repo_root, *, roots) -> SweepReport`, `SweepReport` (`.wired/.config_wired/
  .orphan_cluster/.orphan/.to_dict()/.to_markdown()`), `mcp_crosscheck(report, mcp_query)` (advisory),
  `LIVE_ROOTS`. A WIRE oracle asserts `check_wired(repo_root, m, roots=discover_live_roots(repo_root))
  .wired is True` after the fix; a RECLASSIFY-to-root oracle asserts the module appears in
  `discover_live_roots`.
- `tests/harness/test_no_source_orphans.py` — the regression guard. `KNOWN_ORPHAN_ALLOWLIST` is a
  dict `{module_rel: justification}` baselining the 36. EVERY remediation leaf DELETES its module's
  key from this dict (a RECLASSIFY-to-allowlist leaf instead REWRITES the justification to the final
  reason). The guard must remain green after every leaf — this is the per-leaf meta-acceptance.
- `WIRE_UP_SWEEP_REPORT.md` — the audit ledger (92 WIRED / 4 CONFIG_WIRED / 15 ORPHAN_CLUSTER /
  21 ORPHAN). The binding orphan list is the allowlist keys, not this snapshot.

# The 36 confirmed orphans (the binding work-list, by category)

- **overseer subsystem (18)** — `overseer/{driver,gate_runner,mode_gate,mode_prompts,model_select,
  modes,procedure_artifacts,procedure_state,service,session_store,tmux_chat,tmux_driver,tmux_seams,
  tmux_session,tmux_transcript,transcript,turn_runner,web_api}.py`. The subsystem is reached at
  RUNTIME via the web service + the P6 PreToolUse hook, but NO static import edge connects it to a
  live root (`harness/overseer.py` / `harness/services.py` resolve it lazily). Likely a connected
  component: wiring its true entry (the service handler that constructs the FSM) into a live-reachable
  module wires the cluster transitively. Triage whether one WIRE edge at the subsystem's entry
  suffices, or whether these are config-wired surfaces to RECLASSIFY.
- **hook RPC handlers (5)** — `harness/hooks/rpc/{clarification,error_report,submit_code,
  submit_plan_draft,submit_reconciliation}.py`. Dispatched by NAME from the hook router/inbox, not a
  static import. Triage: WIRE the dispatch-table import, or RECLASSIFY as config/dynamic-wired.
- **rebuild engine (4)** — `harness/rebuild/{decompose,harvest,strip,venv}.py`. Invoked via the
  rebuild loop/CLI (`harness/rebuild/loop.py`, config-referenced). Triage whether `loop.py` (or a
  reachable sibling) should import them (WIRE) or they are CLI-only (RECLASSIFY).
- **narrow-fuzz (2)** — `harness/narrow_fuzz/{_registry,validation}.py`. Plugin-registry modules
  loaded dynamically. Triage WIRE vs RECLASSIFY.
- **misc harness (4)** — `harness/agy_pool.py` (default-OFF worker pool), `harness/config_loader.py`,
  `harness/control_gate.py`, `harness/planner/oracle_attach.py`. Individual triage; agy_pool and
  oracle_attach are REMOVE candidates IF positively proven dead.
- **operator tools (3)** — `tools/{brief_status,webui_auth,webui_control}.py`. Standalone CLI tools
  not on the live import path. Most likely RECLASSIFY: either add `tools/` to the sweep's source-set
  exclusion (a one-line edit to `sweep_modules`' EXCLUDE tuple, then they leave the classified set
  entirely) or confirm their `__main__` entry and allowlist them with a final justification.

# The verdict rubric (assign exactly one per module; bias toward safety)

- **WIRE** — the module is intended-live but its wiring leaf was never authored. Add the MISSING
  import/call edge from a module already reachable from a live root, such that the feature actually
  runs. Oracle (edge-asserting): `check_wired(repo_root, m, roots=discover_live_roots(repo_root))
  .wired is True` with the new importer named, PLUS an assertion that the behavior the wiring enables
  now fires (drive the live path; do not merely add an inert `import m`). The gate proves reachability,
  not usefulness — the behavior assertion is what stops a trivial inert import.
- **RECLASSIFY** — the module is a legitimate entrypoint or a surface the runtime resolves
  dynamically (config string, hook table, plugin registry, CLI `__main__`) that the static graph
  cannot see. Either (i) make it discoverable: ensure its `config/**` reference exists so it
  classifies CONFIG_WIRED, or add it to `discover_live_roots` if it is a true entrypoint; OR (ii)
  keep it allowlisted but REWRITE its justification to the final, evidence-backed reason (no longer
  "pending Wave-2"). Oracle asserts the module classifies CONFIG_WIRED / root, or that the guard
  passes with the rewritten justification.
- **REMOVE** — the module is genuinely dead: positively proven to have NO importer (static OR
  dynamic — grep for importlib / the stem in config / hook tables / plugin registries), NO `__main__`
  entry, and superseded or scratch. Oracle asserts the module file is gone AND the full affected test
  suite stays green (nothing referenced it). REMOVE is destructive and hard to reverse — when triage
  is not CONCLUSIVE, do NOT remove; fall back to RECLASSIFY (allowlist with an evidence justification)
  and surface the ambiguity. Protected-path deletes route through the pipeline like any change.

# Correctness regimes (the build boundary)

WIRE and RECLASSIFY edits are ADDITIVE to live code (a new import/call edge, a `config/**` reference,
a `discover_live_roots`/EXCLUDE update) and must preserve every existing behaviour and passing test.
REMOVE is a destructive delete gated on positive proof of deadness. The DETERMINISTIC parts (the
allowlist edit, the EXCLUDE-tuple edit, the check_wired re-assertion) are pure. Edits to
`harness/**` are protected-path writes ⇒ `meta_task_type=harness_self_fix` + an operator decision
file; edits to `overseer/**` are not protected; edits to `tools/**` are protected (scripts/tools
policy). NEVER hand-edit production outside the pipeline — every WIRE/REMOVE/RECLASSIFY of production
code routes through planner → stage → worker; only the oracles/tests are hand-authored.

THE TRAP (read before authoring any WIRE leaf): a WIRE leaf must add a GENUINE importer that makes
the feature run, proven by the behavior assertion — not a one-line inert `import m` that satisfies
reachability while the code stays dead. The wire-up gate (now live for new modules) proves
reachability, not usefulness; the edge-asserting oracle's behavior clause is the backstop. And the
remediation tooling must not re-orphan itself: every leaf that claims WIRED must leave the guard
green with the module removed from the allowlist.

# Per-leaf contract (oracle-first)

Each leaf names its own pre-committed RED oracle as its `verification_command`
(`python -m pytest tests/<area>/<oracle>.py -q`), hand-authored + committed BEFORE dispatch. A WIRE
or RECLASSIFY leaf edits ONE production file (the importer/config/roots edit) PLUS the allowlist edit
in `tests/harness/test_no_source_orphans.py`; keep the production edit and the allowlist edit in the
same leaf so the guard tightens atomically with the fix. A REMOVE leaf deletes one module + its
allowlist key. New top-level symbols are R-anchored; multi-file emission is avoided (one production
file per leaf). Every leaf's oracle is EDGE-ASSERTING (drives check_wired / the live path), never an
isolated unit test.

# Suggested decomposition (NON-BINDING — you decide the final tree; MAY be multi-level)

A natural MULTI-LEVEL shape: this top epic → one sub-epic per category → one leaf per module.

- **Sub-epic: overseer-wiring** (18 modules) — triage the cluster's true entry; likely a small number
  of WIRE edges at the service/FSM construction site wire most of it transitively, with the remainder
  RECLASSIFIED. This is itself an epic (cross-module reasoning) → decompose into per-module leaves
  after deciding the connecting edge.
- **Sub-epic: hook-rpc-wiring** (5 modules) — WIRE the dispatch-table import or RECLASSIFY as
  dynamic-wired; one leaf per handler (or one leaf if a single dispatch edge wires all five).
- **Sub-epic: rebuild-engine-wiring** (4 modules) — WIRE from `loop.py`/reachable sibling or
  RECLASSIFY CLI-only; one leaf per module.
- **Sub-epic: narrow-fuzz-and-misc** (6 modules: narrow_fuzz/{_registry,validation}, agy_pool,
  config_loader, control_gate, planner/oracle_attach) — individual triage, one leaf each;
  REMOVE only on conclusive deadness.
- **Sub-epic: operator-tools-reclassify** (3 modules) — most likely a SINGLE leaf adding `tools/` to
  the `sweep_modules` EXCLUDE tuple (tools are operator CLIs, not live-path code), which removes all
  three from the classified set; its oracle asserts `tools/*` no longer appear in any SweepReport
  class and the guard passes with their allowlist keys removed.

Order the sub-epics by ease/safety (operator-tools-reclassify and hook-rpc first as low-risk;
overseer-wiring last as the hardest). Each leaf depends on the Wave-1 tooling (already built) and is
otherwise independent unless a single WIRE edge wires a cluster transitively (then one leaf owns the
edge and its siblings RECLASSIFY/confirm).

# Bootstrap acceptance (per sub-epic, manual)

After each sub-epic's leaves land: re-run `sweep_modules` over the live tree and
`tests/harness/test_no_source_orphans.py`; confirm every remediated module is no longer in
`.orphan ∪ .orphan_cluster` (WIRE/RECLASSIFY-to-config) OR is gone (REMOVE), and that its allowlist
key was removed. The terminal epic acceptance: the allowlist is reduced to (ideally) empty, the guard
is green, and `WIRE_UP_SWEEP_REPORT.md` regenerated shows the shrunken orphan set.

# Deliverables

A decomposed remediation tree (one `brief_hooks_<slug>.md` per leaf, optionally grouped under
per-category sub-epic briefs) plus an epic plan record, covering all 36 confirmed orphans, each
assigned one of WIRE / REMOVE / RECLASSIFY with an edge-asserting RED oracle as its
`verification_command`, each removing its module from `KNOWN_ORPHAN_ALLOWLIST`. The end state: the
orphan backlog is discharged, the regression guard passes with a strictly smaller allowlist, and no
source module is both un-allowlisted and unwired. This epic delivers the DECOMPOSITION ONLY — it
authors no oracle and builds/dispatches no leaf; the owner gate stays paused.

# Non-Goals

No reimplementation of `check_wired`, `sweep_modules`, `discover_live_roots`, or the regression guard
— remediation CONSUMES them. No new agent/model/network/subprocess in the deterministic parts. No
SPECULATIVE removals: a module is removed only on positive proof of deadness (no static OR dynamic
importer, no `__main__`, not config-referenced) and a green suite; ambiguous cases RECLASSIFY, never
REMOVE. No inert wiring: a WIRE leaf must make the feature actually run (behavior-asserting oracle),
not add a dead `import`. No silent allowlist growth: the allowlist only SHRINKS; a module is never
added, and a RECLASSIFY rewrite must carry an evidence-backed justification, not "pending Wave-2".
INTEGRATION edits preserve all existing behaviour and tests. This epic is DECOMPOSITION ONLY: it
authors no oracle and dispatches no build; the owner gate stays paused.
