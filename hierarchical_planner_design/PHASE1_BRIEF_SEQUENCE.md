# Hierarchical Planner — Phase 1 Ordered Brief Sequence

> **Compiled 2026-06-05** from a 4-area Gemini 3.5 Flash analysis panel (via `agy`)
> hardened by 4 independent Claude adversarial reviewers. Source material in this
> directory: `gemini_area_{A,B,C,D}_*.md` (raw drafts) and
> `area_{A,B,C,D}_verified.md` (adversarially corrected — **authoritative**).
> Anchors below are at branch `master`; **re-verify before dispatch** (line numbers drift).
>
> **Scope of this doc:** Phase 1 only = **Level 1** (one automated decomposition
> layer, static interfaces) plus the cheap Level-2 items worth pulling forward.
> Level 2 (runtime symbol ledger, active failure propagation, recursion) is
> deferred — see `area_D_verified.md` §10.

---

## 0. The converged design (read this first)

A brief carries `epic: true`. When the planner CLI loads an epic brief it runs a
**decomposition pipeline** (dual-model blind-draft of **child briefs** + brief-diff +
brief-reconcile + a child-brief validator) and emits:
- `plan_hooks_<epic>.json` — an **epic plan record** (lists child slugs + provenance),
- N **planless** `brief_hooks_<child>.md` files at repo root (static interfaces as
  prose, sibling order as dependency hints).

The daemon's existing `_auto_promote` → `_run_planner_subprocess` then **re-plans each
child brief through the normal LEAF pipeline** (full dual-model task synthesis), stages
its leaf tasks, and dispatches them via `orchestrator_worker`. A parent epic rolls up to
`complete` when all children complete (read-derived from `compute_brief_status`).

### Load-bearing design decisions (these resolve the drafts' open questions)
1. **Child briefs are PLANLESS markdown re-planned by the daemon** — NOT pre-synthesized
   like selfheal. The re-entry seam already exists for free (`brief_status` `unplanned`
   → `_auto_promote` → `_run_planner_subprocess`), *provided the child slug is allowlisted*.
2. **The #1 blocker (Area B):** `plan_validator.validate_plan` is a hard gate at
   `blind_draft.py:79` AND `cli.py:195` that requires the full leaf-task schema. A
   child-brief-shaped draft is silently dropped as `invalid` **before** diff/reconcile.
   "Reuse the machinery" therefore requires a **parallel child-brief validator + mode
   threading** first. Nothing decomposes until this lands.
3. **Prompts are inline f-strings**, not files (`blind_draft.py:135`, `reconciliation.py:101`).
   There is no prompt-selection seam — a tiny loader must be built before epic prompts exist.
4. **Roll-up is READ-DERIVED** from `compute_brief_status` (its 7-state ladder). Do NOT
   add a second persisted tree-state file; do NOT reuse `task_decomposer.update_parent_state`
   (it's a single global `STATE.json` with one `children` list — can't model concurrent epics).
   The `epic_complete` ledger row is **telemetry only**, never a load-bearing cache.
5. **Everything is default-OFF** behind a `hierarchical_planning.enabled` config flag,
   fail-closed (mirrors `selfheal_auto_promote` / `auto_approve_ro_gate` convention).
6. **No class-method red zone** — every target is a top-level function. BUT the hosts
   `cli.main`, `validate_plan`, `run_blind_drafts`, `run_reconciliation`, `_auto_promote`
   (~230 ln), `_auto_commit_accepted` (~988 ln!) are **large symbols that truncate under
   partial-edit**. RULE: every change is a **NEW top-level helper + a one-line call-site
   insertion**, never an in-place body rewrite of those giants.
7. **Allowlist auto-admission of child slugs is SECURITY-GATED** (the allowlist is the
   autonomy trust root). Until the owner approves automation, child slugs are appended by
   an **operator step** — fine for early dogfooding.

### "First light" marker
The first time an epic brief visibly decomposes is at **Brief 10**. Briefs 1–9 are the
substrate that makes Brief 10 possible; Briefs 11–17 complete and harden the loop.
Spend hand-effort on 1–10; from ~10 onward you can begin dogfooding (feed the new
decomposer small epics).

---

## 1. Ordered brief sequence

Legend — Viability: **GREEN** single-symbol/new-file (~80-85% pipeline), **YELLOW**
multi-symbol/large-host (split-prone, 60-70%), **HAND** config/prose/security-gated.
Every behavior brief is **oracle-first** (write the RED test first).

| # | Brief | Primary anchors (verify) | Viability | Dep | Notes / split risk |
|---|-------|--------------------------|-----------|-----|--------------------|
| **1** | `hierarchical_planning:` config block, default-off (`enabled:false, symbol_ledger:false, failure_propagation:false, max_planner_depth:4`) | `config.yaml` append (~L114) | HAND (config) | — | Land FIRST so every later piece is flag-gated. Read via `config.get('hierarchical_planning',{}).get(...)`. No dataclass. |
| **2** | `PlanningBrief.epic: bool=False` + `complexity_score: int\|None=None` fields | `brief_loader.py:28-36` | GREEN | — | Frozen dataclass; append after `working_dir` (default-arg order). Scope edit to the **field block only** (avoid whole-class patch → `to_agent_prompt` method). |
| **3** | Parse `epic`/`complexity_score` (+ `dependencies`/`interfaces` frontmatter) in `load_brief` | `brief_loader.py:158,159-163,187,202-212` | YELLOW (multi-site, 1 fn) | 2 | **Type-coercion trap:** L163 `str()`-wraps all frontmatter → must explicitly parse bool/int, not just add to `_optional`. Parsing `dependencies` frontmatter is needed so child sibling-order survives re-planning. |
| **4** | `epic_planning` meta-task-type | `taxonomies.py:1` (dict key) | GREEN | — | `META_TASK_TYPES` auto-derives. Set `bypass_fuzzer/skip_structural_decomp/skip_smoke_gates` (it emits briefs, not code). |
| **5** | `validate_child_brief_plan(plan)` — sibling validator with the *brief* schema | `plan_validator.py` new top-level fn (near `:193`) | GREEN (new fn) | 4 | The brief-schema counterpart to `check_missing_fields`. Does NOT touch the leaf required-field list (doing so breaks every existing task). |
| **6** | **[BLOCKER]** Thread a `mode`/`kind` param so `collect_agent_draft` + final `cli.main` validation use `validate_child_brief_plan` for epic drafts | `blind_draft.py:79`, `cli.py:195`, `plan_validator.py:60` | YELLOW (2 call sites) | 5 | **Make-or-break.** Without it the dual-model decomposition drafts die as `invalid` before diff/reconcile. Keep `validate_plan` default = leaf (back-compat: 5 callers — cli, auto_amend×2, blind_draft, MCP submit). |
| **7** | Extract `_planning_prompt(brief, mode)` helper + `prompts/epic_decomposition_prompt.md` | `blind_draft.py:135` (inline prompt), new `prompts/` file | GREEN (new fn + config) | 6 | Builds the prompt loader that doesn't exist today. Epic mode → child-brief drafting prompt (frontmatter `slug`/`dependencies`/`interfaces`; body Title/Scope/Non-Goals/Inputs/Deliverables). Avoids patching the large `run_blind_drafts` body. |
| **8** | Widen `FieldKind` Enum (`scope_text`/`deliverables`/`interfaces`/`inputs`) + `DiffItem` identity fallback to `slug` when `task_id` absent | `diff_model.py:14-21`, `:34-64` | YELLOW (closed enum + frozen `__post_init__`) | 6 | Enum is consumed by hashing + JSON round-trip. Without the identity fallback, empty-`task_id` child briefs hash-collide. |
| **9** | `_compare_brief_fields` helper + `child_briefs`-array path + brief match heuristic in `extract_diff` | `diff_extractor.py:19` (sibling of `_compare_fields`), `:86`, `:110` | YELLOW (multi-symbol) | 8 | Briefs have no `files_touched`; match on forced stable `slug` + scope/deliverables text ratio. |
| **10** | **[FIRST LIGHT]** `_run_epic_pipeline()` helper + epic branch in `cli.main`; writes `plan_hooks_<epic>.json` epic record + child `brief_hooks_*.md`; brief-reconcile via `_reconciliation_prompt(mode)` | `cli.py:108-199` (1-line branch), new helper; `reconciliation.py:101`; new `prompts/epic_reconciliation_prompt.md` | YELLOW (keystone) | 3,5,6,7,9 | The decomposition end-to-end. Implement as a NEW top-level helper called from ONE inserted line in `main` (do NOT rewrite `main`). Reconcile merge is artifact-opaque (degrades to `flag_for_human` tiebreaker — acceptable). May split into 10a (epic branch+pipeline) / 10b (reconcile prompt). |
| **11** | `brief_generator.serialize_child_brief_to_markdown(brief_data)->str` | new `harness/planner/brief_generator.py` | GREEN (new-file) | 10 | Output MUST pass `load_brief` (required sections + frontmatter) or the re-planned child brief exits 3. |
| **12** | `persist_plan` epic wrapper + `parent_epic_slug` provenance stamp | `cli.py:86-106` | GREEN | 10 | Mirror the existing `working_dir`/`source_brief_path` injection. `parent_epic_slug` is the key Area-C reads for depth + roll-up (M2). |
| **13** | `validate_plan` dispatch: epic plan → `validate_epic_plan`, else leaf (unchanged) | `plan_validator.py:60` (3-line dispatch at top) + new `validate_epic_plan` | YELLOW (large host) | 5,12 | Discriminate on `plan.get('plan_kind')`/`epic`. Missing key MUST mean leaf (back-compat for all 5 callers). |
| **14** | `check_brief_depth(slug, repo_root, max_depth)` walking `parent_epic_slug` + planner-time `max_planner_depth` budget | new top-level fn (near `depth_validator.py`); planner emit path | GREEN (new fn) | 1,12 | The recursing chain is *briefs*, not task JSON — `check_true_depth` can't walk it. Also add `parent_epic` to `check_true_depth`'s `p_val` lookup (`:61-65`) as a cheap belt-and-suspenders. Pulled forward from Level 2 (cheap, bounds runaway). |
| **15** | **[SECURITY-GATED]** Auto-admit child slugs to `auto_promote.allowlist` when their epic is allowlisted | `brief_status.py:106` (eligibility); allowlist file | HAND (owner decision) | 12 | The allowlist is the autonomy trust root (`_NEVER_AUTO_APPROVE` / operator-decision pattern). **Needs owner security review before automation.** Until then: operator appends child slugs manually (loop still works, just not hands-off). |
| **16** | `compute_epic_status` (read-derived roll-up over child `compute_brief_status` records) + `epic_complete` telemetry row | new top-level fn; emit near `_auto_promote` (one-line call to new helper) | GREEN (new fns) | 12 | Epic `complete` ⇔ all children `complete`; reuse existing per-brief `zombie`/`blocked` states. New `(phase=epic,event=epic_complete)` row is flat-consumer-safe (all readers filter explicit pairs). Do NOT route through `STATE.json`. |
| **17** | **[GATE]** End-to-end oracle: one allowlisted epic brief → decomposes → child briefs re-plan → leaf tasks land → epic rolls up `complete` (flag flipped on in-test) | new test file under `tests/planner/` or `tests/adversarial/` | GREEN (new-file, oracle IS the test) | all | The acceptance proof for Phase 1. Also update `tests/planner/test_cli.py:163-166` if `PIPELINE_STAGES` gains an entry (HAND, source+test transaction). |

**Side step (anytime after Brief 4):** add `epic_planning` to the autobrief META allow-list
and declare the `epic`/`complexity_score` frontmatter keys — `tools/webui_autobrief_prompt.txt:11-17,46-69`
(HAND, prose). Without the allow-list edit the autobrief endpoint 422-rejects the new type.

---

## 2. Dependency graph (build order is mostly linear)

```
1 (config gate) ─┐
2 (epic field) ─→ 3 (parse) ─────────────────────────────────────┐
4 (taxonomy) ──→ 5 (child validator) ─→ 6 [BLOCKER mode-thread] ─→ 7 (prompt loader) ─┐
                                          └→ 8 (diff_model) ─→ 9 (diff_extractor) ─────┤
                                                                                       ↓
                                          3,5,6,7,9 ───────────────→ 10 [FIRST LIGHT] ─→ 11 (serialize)
                                                                          │
                                                       12 (provenance) ←──┘
                                            12 ─→ 13 (validate dispatch)
                                            12 ─→ 14 (depth guard)
                                            12 ─→ 15 (allowlist, GATED)
                                            12 ─→ 16 (roll-up)
                                            all ─→ 17 (gate test)
```

Critical path to first light: **1 → 2 → 3 → 4 → 5 → 6 → 7 → (8 → 9) → 10**. Brief 6 is
the gate everything funnels through; do it carefully and oracle it hard.

---

## 3. Count & honest read

- **17 Phase-1 briefs** (a few — 3, 6, 8, 9, 10, 13 — are split-prone and may each become
  two single-symbol briefs, so budget **~20-24 actual pipeline dispatches**).
- This is **larger than the earlier ~7-8 "spine" estimate** — because the adversarial pass
  found two costs the first-pass estimate hid: the **`validate_plan` blocker + mode-threading**
  (Briefs 5-6) and the **diff/diff_model generalization** (Briefs 8-9). Those are unavoidable
  to make the dual-model decomposition real rather than hand-waved.
- **~10 of the 17 are GREEN** (low risk). The risk concentrates in Briefs 6, 8-9, 10, 13.
- **Brief 15 is the only owner-gated item** — everything else is default-off and reversible.
- After **Brief 16** the Level-1 loop is closed: an allowlisted epic brief autonomously
  decomposes, builds, and rolls up. **Brief 17** proves it.

---

## 4. Deferred to Level 2 (NOT in Phase 1 — see `area_D_verified.md`)

- Runtime **symbol/interface ledger** (`symbol_ledger.jsonl`) + `resolve_interfaces` at
  staging — generalizes Phase-1's *static* `spec.interfaces` prose to *actually-committed*
  signatures. Recommended **lazy-derived from existing accepted ledger rows** so the
  988-line `_auto_commit_accepted` is never edited.
- Active **failure propagation** (`mark_epic_blocked_on_failure` at `_mark_blocked` tail) —
  note: failure *containment* + sibling-non-deadlock **already exist** via `STAGING_DEP_GATE`;
  only *announcing* ancestor failure is missing (~15-line helper).
- **Arbitrary-depth** (N>1) recursion + child-plan GC.
- The over-engineered `failure_propagator.py` module from the draft was **rejected** as
  unnecessary.

---

## 5. Provenance / how to trust this

- Raw analysis: 4 Gemini 3.5 Flash agents (one per area) via `agy --model "Gemini 3.5 Flash (High)"`.
  (Note: print-mode forced sequential execution, not true parallel sub-agents — see
  `agy_run.log`.)
- Hardening: 4 independent Claude adversarial reviewers, each verifying every anchor against
  source and re-tagging viability. They caught: the phantom `PIPELINE_STAGES` stage-runner
  (Area A), the `validate_plan` blocker the drafts all missed (Area B), the misconceived
  orchestrator "interceptor" and the phantom class-method red-zone (Area C), and the
  over-built `failure_propagator.py` + wrong interface-resolution seam (Area D).
- **The `area_*_verified.md` files are authoritative**; the `gemini_*` raw drafts are kept
  only for provenance. Each verified report's §9 lists exactly what was corrected and at what
  confidence.
