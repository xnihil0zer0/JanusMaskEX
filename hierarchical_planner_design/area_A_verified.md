# Area A — Brief Ingestion & Planner Front-end / Schema (VERIFIED)

> Adversarial review of `gemini_area_A_brief_planner_frontend.md`. Every anchor
> below was opened and confirmed against the working tree on branch `master`.
> Anchors are stated as `file:LINE` at the **current** file state. Viability tags
> re-derived from the actual symbol shapes (top-level function vs `Class.method`).

## 1. Summary

Area A is the planner front-end for hierarchical planning. The brief gains an
`epic` flag (and optional `complexity_score`) so a brief can declare that it
should be **decomposed into child briefs** rather than synthesized into leaf
tasks. Three substrate files carry the load:

- `harness/planner/brief_loader.py` — the `PlanningBrief` frozen dataclass and
  the `load_brief` ingest function. (Note: there is a **second** `load_brief`
  thin wrapper in `cli.py`; do not confuse the two.)
- `harness/planner/cli.py` — the `main()` driver. It is a **flat, hand-written
  call sequence**, NOT a loop over `PIPELINE_STAGES`. `PIPELINE_STAGES` is a
  *declarative manifest used only for ordering assertions in tests*; inserting
  a name into it does nothing at runtime by itself and **breaks the test
  oracle** unless `main()` is also edited and the test's hardcoded `expected`
  list is updated.
- `harness/planner/plan_validator.py` — `check_missing_fields` + `validate_plan`,
  which today validate **every** entry in `plan['tasks']` as a leaf code task.
  An epic plan that emits child-brief artifacts instead of tasks will FAIL this
  validator unless it learns to branch.

Correctness caveat vs the Gemini draft: the draft's central architectural claim
("just insert an `epic_analysis` stage after `load_brief` and the data flows")
is **wrong about the mechanism** — there is no stage-runner loop to insert into,
and the validator does not currently have any place to branch on epic vs leaf.
Both are real, larger pieces of work than the draft implies.

## 2. Existing Substrate (anchors corrected)

### `harness/planner/brief_loader.py`
- `@dataclass(frozen=True) class PlanningBrief` — **decorator+class header at
  L26–27**, field block **L28–36** (`title, scope, non_goals, inputs,
  deliverables, raw_text, source_path, sha256, working_dir`), with a
  `to_agent_prompt(self)` method at **L38–50**.
  - Gemini said `L26-36`. The dataclass *fields* end at L36, but the symbol
    (decorator L26 through method end L50) is larger. The field-add target is
    L28–36. **Confirmed it is `frozen=True`.**
  - IMPORTANT: `to_agent_prompt` is a method *inside* this dataclass. The field
    additions themselves are **module-top-level dataclass fields** (safe — see §5),
    but any edit that the symbol-patcher scopes as `PlanningBrief` (whole class)
    risks the class-method red zone. Prefer a field-list-only edit.
- `load_brief(path, max_bytes=...)` — **top-level function, L122–212.** Gemini
  said `L122-212`. **Confirmed.**
- The optional-key whitelist is `_optional = {"working_dir"}` at **L158**, and the
  frontmatter-normalization loop is **L159–163**. `REQUIRED_SECTIONS` is a
  module constant at **L67**. Gemini cited `L158` for ingest — correct line,
  but the draft's claim "add to `_optional` set" is **only half the change**
  (see §3, the field must also be threaded into the `PlanningBrief(...)`
  constructor call at L202–212 and—if it is to be a real field—handled like
  `working_dir` at L187).

### `harness/planner/cli.py`
- `PIPELINE_STAGES` — module list at **L9** (single line). Gemini said `L9`.
  **Confirmed**, but mis-characterized (see §1 / §5).
- `main()` — **top-level function L108–199.** Gemini said `L108-199`.
  **Confirmed.** It is a flat sequence of `load_brief → blind_drafts → diff →
  reconciliation → attribution_stamp → adversarial_review → auto_amend_gate →
  persist_plan → validate_plan`. **There is no loop over `PIPELINE_STAGES`.**
- `persist_plan(plan, out_path, brief_obj=None)` — **top-level function L86–106**
  (Gemini said `L86-107`; the symbol ends at L106). **Confirmed.** It already
  injects wrapper fields (`source_brief_path`, `source_brief_sha256`,
  `working_dir`) conditionally — this is the correct template for injecting an
  `epic`/`complexity_score` wrapper field.
- The thin stage wrappers `load_brief` (L44), `blind_drafts` (L50), `diff` (L56),
  etc. each call `_tracker.record(...)`. Gemini's "stage execution wrapper" at
  `cli.py:44` collides with the existing `load_brief` wrapper — `L44` is **not**
  a free insertion point; it is the body of the existing `load_brief` wrapper.

### `harness/planner/plan_validator.py`
- `check_missing_fields(task, path_prefix)` — **top-level function L19–58.**
  Gemini said `L19-58`. **Confirmed.**
- `validate_plan(plan)` — **top-level function L60–190** (Gemini said `L60-190`;
  body ends L190). **Confirmed.** It unconditionally iterates `plan['tasks']`
  and applies the full leaf-task schema (`check_missing_fields` + meta-task-type
  + priority + token-budget-ratio + test-ratio gates). There is **no** existing
  branch for plan kind.
- The required top-level field list lives **inline at L21** inside
  `check_missing_fields`: `['task_id', 'title', 'meta_task_type', 'priority',
  'dependencies', 'files_touched', 'acceptance_criteria', 'spec_author',
  'estimated_complexity', 'verification_command']`. There is **no** `parent_epic`
  or `epic_part` field anywhere today (Gemini implied these exist as keys to
  "add validation for" — they are net-new, §6).
- Bonus symbol the draft missed: `validate_plan_wrapper(plan)` — **top-level
  function L193–233** — validates `source_brief_path`/`source_brief_sha256` and
  hard-raises on bad `verification_command`. This is where epic wrapper-field
  validation most naturally lands.

### `harness/planner/taxonomies.py`
- `META_TASK_POLICY` — module-level dict literal, **single line L1** (Gemini said
  `L1`, **confirmed**). `META_TASK_TYPES = frozenset(META_TASK_POLICY.keys())`
  at **L2**. Adding a meta-task-type = adding a key to the L1 dict; the derived
  frozensets at L2–5 pick it up automatically.

### `tools/webui_autobrief_prompt.txt`
- Gemini cited `L9-18` for "YAML frontmatter and required headings." **Partially
  wrong.** The frontmatter section is **L9–17** and lists four keys
  (`freeze_lift, author, synthesis_of, relates_to`) — **NOT** the brief's
  required content sections. The required section **headings** (`# Title / #
  Scope / # Non-Goals / # Inputs / # Deliverables / # Acceptance`) are at
  **L19–29**. The META task-type allow-list (which would need a new
  `epic_planning` type added) is at **L44–69**. Gemini's anchor `L11` for "epic
  spec" points at the frontmatter key list, which is a plausible place, but the
  draft omitted that the allow-list at L46–69 **must also** be updated or the
  autobrief endpoint will reject the new meta-task-type.

## 3. Required Changes (corrected anchors + verified viability)

| # | Change | TRUE Anchor | New/Mod | Viability (verified) | Level | Notes |
|---|--------|-------------|---------|----------------------|-------|-------|
| A1 | Add `epic: bool = False`, `complexity_score: int \| None = None` fields to `PlanningBrief` | `brief_loader.py:28-36` | Modify | **GREEN** (top-level dataclass fields; append after `working_dir` to keep default-arg order) | 1 | Frozen dataclass — defaults required since they follow `working_dir` default. NOT a class-method edit. |
| A2 | Parse `epic`/`complexity_score` in `load_brief`: widen `_optional`, thread into ctor | `brief_loader.py:158` (`_optional`), `159-163` (normalize), `187` (mirror `working_dir` extract), `202-212` (ctor) | Modify | **GREEN** (top-level function `load_brief`) | 1 | Multi-site edit but all inside ONE top-level function. `str(v)` normalization at L163 forces strings; `epic`/`complexity_score` need type coercion (bool/int) — add a small typed-parse, do NOT just dump into `_optional` (Gemini's "add to `_optional`" alone yields a string `"True"`). |
| A3 | Update autobrief prompt: declare `epic`/`complexity_score` frontmatter keys + add `epic_planning` to allow-list | `webui_autobrief_prompt.txt:11-17` (frontmatter), `46-69` (allow-list) | Modify | **HAND** (prose .txt, not code) | 1 | Gemini missed the allow-list edit (L46-69). Must be a single transaction with A8 or the endpoint 422s the new type. |
| A4 | (Re)design — epic detection. NO stage-runner loop exists. Add an epic branch in `main()` after `load_brief` (L151) | `cli.py:108-199` (`main`) | Modify | **YELLOW** (top-level `main`, but it is a 92-line function; large-symbol partial-edit truncation risk per house rules — split into a NEW top-level helper called from one inserted line) | 1 | Gemini's model ("insert into PIPELINE_STAGES + a stage runner") is INVALID: `main()` is a flat call sequence, not a dispatch loop. Realistic edit = one inserted call to a new `branch_on_epic(brief_obj, config, state_dir)` helper. |
| A5 | Add `'epic_analysis'` to `PIPELINE_STAGES` AND update `_tracker` oracle | `cli.py:9` + `tests/planner/test_cli.py:163-166` | Modify | **HAND** (test oracle has a hardcoded `expected` list at test_cli.py:163 + `_tracker.verify` at :166) | 1 | Gemini tagged HAND — correct — but missed WHY: `_tracker.verify(expected)` and `assert cli._tracker.call_order == expected` enforce the exact stage list. Adding to `PIPELINE_STAGES` without recording the stage AND updating the test breaks the suite. PIPELINE_STAGES is inert at runtime; this edit is mostly for the test contract. |
| A6 | Update `persist_plan` to write `epic`/`complexity_score`/child-brief artifacts into the wrapper | `cli.py:86-106` | Modify | **GREEN** (top-level function, small) | 1 | Mirror the existing `working_dir` injection at L102-104. Confirmed correct insertion site. |
| A7 | Branch `validate_plan` on epic vs leaf plan; skip leaf-task schema for child-brief entries | `plan_validator.py:60-190` | Modify | **YELLOW** (top-level `validate_plan`, 131-line function — truncation risk; prefer adding a NEW top-level `validate_epic_plan(plan)` + a 3-line dispatch at the top of `validate_plan` rather than weaving a branch through the loop) | 1 | Gemini tagged YELLOW — correct kind, but the draft underestimates: there is currently NO plan-kind discriminator. Need a `plan.get('plan_kind')`/`plan.get('epic')` gate before the `tasks` loop at L69-75. |
| A8 | Add `epic_planning` (and optionally `sub_brief_planning`) meta-task-type | `taxonomies.py:1` (dict key) | Modify | **GREEN** (module dict literal, Assign target — symbol-patchable) | 1 | Confirmed `META_TASK_TYPES` derives from keys at L2 automatically. Pick `bypass_fuzzer: True, skip_structural_decomp: True, skip_smoke_gates: True` (it produces briefs, not code). |
| A9 | Child-brief artifact schema validator (`parent_epic`, `epic_part`, child-brief path/sha) | `plan_validator.py` (NEW top-level fn near `validate_plan_wrapper` L193) | New | **GREEN** (new top-level function) | 1 | Gemini framed this as "add `parent_epic`/`epic_part` to existing field checks" — WRONG: those keys belong to child-brief artifacts, not leaf tasks; conflating them into `check_missing_fields` (L21 list) would break every existing leaf task. Must be a SEPARATE validator. |
| A10 | Recursive re-entry + runtime symbol ledger hooks | (deferred) | New | n/a | **2** | Level-2 tier; out of scope for first decomposition. |

## 4. New Symbols / New Files (corrected)

- `harness/planner/plan_validator.py`
  - **NEW** `def validate_epic_plan(plan: dict) -> List[PlanViolation]:` (top-level)
    — validates a plan whose payload is child briefs, not leaf tasks. Dispatch
    from the top of `validate_plan`. (Replaces Gemini's idea of weaving epic
    checks into `check_missing_fields`, which would corrupt leaf validation.)
- `harness/planner/cli.py`
  - **NEW** `def branch_on_epic(brief_obj, config, state_dir):` (top-level helper)
    — the realistic substitute for Gemini's `epic_analysis` stage. Called from a
    single inserted line in `main()` (avoids the large-`main()` truncation risk).
- `harness/planner/epic_detector.py` (Gemini's optional module)
  - **OPTIONAL / Level 2.** A separate module
    `analyze_brief_hierarchy(brief) -> tuple[bool, int]` is reasonable but NOT
    required for Level 1 if the `epic` flag is brief-declared (frontmatter). For
    Level 1, epic status is a declared field (A1/A2), so heuristic detection is
    deferred to Level 2. Keep this OUT of the first cut.

## 5. Data-Flow / Sequence (corrected)

Real Level-1 flow (no stage-runner; flat `main()` sequence):

```
main(brief)                              [cli.py:108]
  └─ brief_obj = load_brief(brief)       [cli.py:151 -> wrapper L44 -> brief_loader.load_brief L122]
       PlanningBrief(epic=?, complexity_score=?)   [new fields A1/A2]
  └─ if brief_obj.epic:                   [NEW branch, inserted ~L151-155]
       branch_on_epic(brief_obj, ...)     [NEW helper A4 — drafts CHILD BRIEFS]
     else:
       blind_drafts -> diff -> reconciliation -> attribution_stamp
       -> adversarial_review -> auto_amend_gate   [existing leaf path, L156-192]
  └─ persist_plan(final_plan, ..., brief_obj)      [cli.py:193 -> L86; inject epic wrapper A6]
  └─ violations = validate_plan(final_plan)        [cli.py:195 -> L60]
       if final_plan.epic: validate_epic_plan(...)  [NEW dispatch A7/A9]
       else: <existing leaf-task validation>
```

Key correction vs Gemini's mermaid: there is no `Detector` participant in the
Level-1 path; the epic flag is read off the already-loaded `PlanningBrief`.
`validate_plan` is reached via `cli.py:195` (and also independently via
`auto_amend.py:114/166` and `blind_draft.py:79` and the MCP RPC
`submit_plan_draft.py:29`) — so an epic-aware `validate_plan` must remain
back-compatible for all those callers (a missing `epic` key must keep meaning
"leaf plan").

## 6. Dependencies & Ordering

**Level 1 (first automated decomposition):**
1. A1 (PlanningBrief fields) — no deps.
2. A2 (load_brief parse) — depends on A1.
3. A8 (taxonomy `epic_planning`) — no deps; needed before any epic plan validates.
4. A9 (`validate_epic_plan` / child-brief schema) — depends on A8.
5. A7 (validate_plan dispatch) — depends on A9.
6. A6 (persist_plan wrapper) — depends on A1.
7. A4 + A5 (main() branch + PIPELINE_STAGES/test oracle) — depends on A1, A2, and
   the child-brief drafting machinery (other Areas).
8. A3 (autobrief prompt) — depends on A8 (allow-list must include the new type).

**Level 2 (deferred):**
- A10 recursive re-entry + runtime symbol ledger.
- `epic_detector.py` heuristic scoring (replace declared `epic` flag with
  model-inferred complexity).

## 7. Risks, Red-Zones, Open Questions

- **Gemini's "no class-method edits" claim is essentially TRUE for Area A** —
  `brief_loader`, `cli`, `plan_validator`, `taxonomies` are all top-level
  functions/module constants. **One caveat:** `PlanningBrief.to_agent_prompt`
  IS a class method (L38), and `_PipelineTracker` (cli.py L14-24),
  `PlanViolation` (plan_validator L12-17), `BriefValidationError`,
  `UniqueKeyLoader` are classes — none need editing for Area A, but a
  symbol-patcher told to edit "`PlanningBrief`" (the whole class) instead of
  just its field block could stray into the red zone. Mitigation: scope A1 to
  the field lines only.
- **Large-symbol truncation:** `main()` (92 lines) and `validate_plan` (131
  lines) exceed the size where partial-edit reliably succeeds in this pipeline.
  A4 and A7 are tagged YELLOW for this reason; both are restructured here as
  "new top-level helper + 1-3 line dispatch" to dodge it.
- **Test oracle coupling:** `tests/planner/test_cli.py:163-166` hardcodes the
  full expected stage list and calls `_tracker.verify`. Any `PIPELINE_STAGES`
  change is a HAND edit spanning source + test.
- **Validator back-compat:** `validate_plan` has 5 distinct callers (cli,
  auto_amend×2, blind_draft, MCP submit_plan_draft). An epic branch must default
  to leaf behavior when no `epic` marker is present.
- **`str()` coercion trap:** `load_brief` L163 wraps every frontmatter value in
  `str(...)`. A naive "add `epic` to `_optional`" yields `"True"`/`"False"`
  strings, not booleans. A2 must parse types explicitly.
- **Open question:** what carries the child-brief payload in an epic plan — a
  new top-level key (`plan['child_briefs']`) or repurposed `plan['tasks']` with
  a `plan_kind` discriminator? §4 assumes a `plan_kind`/`epic` discriminator;
  this must be fixed across Areas before A7/A9 land.

## 8. Anchor Appendix (verified)

| Symbol | File:Line (verified) | Kind |
|--------|----------------------|------|
| `PlanningBrief` (dataclass) | `harness/planner/brief_loader.py:26-50` (fields 28-36) | frozen dataclass |
| `PlanningBrief.to_agent_prompt` | `harness/planner/brief_loader.py:38-50` | **class method (red zone — do not edit)** |
| `REQUIRED_SECTIONS` | `harness/planner/brief_loader.py:67` | module const |
| `load_brief` | `harness/planner/brief_loader.py:122-212` | top-level fn |
| `_optional` whitelist | `harness/planner/brief_loader.py:158` | local set |
| `PlanningBrief(...)` ctor call | `harness/planner/brief_loader.py:202-212` | call site |
| `PIPELINE_STAGES` | `harness/planner/cli.py:9` | module list (inert at runtime; test contract) |
| `cli.main` | `harness/planner/cli.py:108-199` | top-level fn (flat sequence) |
| `cli.persist_plan` | `harness/planner/cli.py:86-106` | top-level fn |
| `cli.load_brief` (wrapper) | `harness/planner/cli.py:44-48` | top-level fn (NOT the loader) |
| `check_missing_fields` | `harness/planner/plan_validator.py:19-58` | top-level fn |
| `top_level_reqs` field list | `harness/planner/plan_validator.py:21` | inline list |
| `validate_plan` | `harness/planner/plan_validator.py:60-190` | top-level fn |
| `validate_plan_wrapper` | `harness/planner/plan_validator.py:193-233` | top-level fn (epic-wrapper home) |
| `META_TASK_POLICY` | `harness/planner/taxonomies.py:1` | module dict (Assign target) |
| `META_TASK_TYPES` | `harness/planner/taxonomies.py:2` | derived frozenset |
| autobrief frontmatter keys | `tools/webui_autobrief_prompt.txt:11-17` | prose |
| autobrief required sections | `tools/webui_autobrief_prompt.txt:19-29` | prose |
| autobrief META allow-list | `tools/webui_autobrief_prompt.txt:46-69` | prose (must add `epic_planning`) |
| test stage oracle | `tests/planner/test_cli.py:163-166` | test (HAND-couples to PIPELINE_STAGES) |

## 9. Adversarial Review Findings

What the Gemini draft got wrong, and the confidence of each correction:

1. **Hallucinated stage-runner architecture (HIGH confidence).** Gemini's core
   model — "insert `epic_analysis` into `PIPELINE_STAGES` and a stage runner
   invokes it" — does not match the code. `main()` (cli.py:108-199) is a flat,
   hand-written call sequence; `PIPELINE_STAGES` (L9) is iterated **nowhere** in
   the harness (grep-confirmed: only referenced in cli.py:9 and test assertions).
   The real insertion point is a manual branch inside `main()`. **Corrected in
   A4/A5 and §1/§5.**

2. **`persist_plan` anchor off by one (HIGH).** Gemini said `L86-107`; the symbol
   ends at L106. Minor but corrected.

3. **`load_brief` ingest change underspecified + type bug (HIGH).** "Add to
   `_optional` set" alone is insufficient and buggy — L163 `str()`-coerces all
   frontmatter values, so `epic` would become the string `"True"`. Real change
   spans `_optional` (L158), the normalize loop (L159-163), the `working_dir`-style
   extract (L187), and the ctor (L202-212). **Corrected in A2 + §7.**

4. **`parent_epic`/`epic_part` mis-placed (HIGH).** Gemini proposed adding these
   to `check_missing_fields`/the L21 leaf-task required list. That would make
   EVERY existing leaf task fail validation. These keys belong to a SEPARATE
   child-brief artifact validator (`validate_epic_plan`). **Corrected in A9 + §4.**

5. **Validator-branch difficulty understated (MEDIUM-HIGH).** Gemini tagged A7
   YELLOW but framed it as a light conditional. There is no plan-kind
   discriminator today and `validate_plan` is a 131-line function with 5 external
   callers; a woven branch risks truncation and back-compat breakage. Restructured
   as "new top-level `validate_epic_plan` + 3-line dispatch." **Corrected in A7/§7.**

6. **Autobrief allow-list edit missed (HIGH).** Gemini's prompt change cited only
   the frontmatter block (~L11) and omitted the META task-type allow-list at
   L46-69. Without adding `epic_planning` there, the autobrief endpoint rejects
   it (per the prompt's own L69 rule). **Corrected in A3 + §2.**

7. **`webui_autobrief_prompt.txt:L9-18` anchor wrong (MEDIUM).** That range is the
   frontmatter-keys section (4 keys, none content-related); the content section
   headings are L19-29. **Corrected in §2.**

8. **Test-oracle coupling unflagged (HIGH).** Gemini tagged the PIPELINE_STAGES
   edit HAND but never noted that `tests/planner/test_cli.py:163-166`
   (`_tracker.verify` + hardcoded `expected`) enforces the exact stage list, so
   the edit is a source+test transaction. **Added in A5 + §7.**

9. **`cli.py:44` insertion point collides with existing code (MEDIUM).** Gemini's
   "stage execution wrapper at cli.py:44 & 151" lands on the existing `load_brief`
   wrapper body (L44) and the `load_brief` call (L151) — neither is a free slot.
   **Clarified in §2.**

10. **Confirmed-correct claims (for the record):** `PlanningBrief` IS
    `frozen=True` (HIGH); the "no class-method red zone" conclusion is essentially
    correct for Area A (HIGH, with the `to_agent_prompt`/whole-class caveat);
    `taxonomies.py` meta-type addition is GREEN single-symbol (HIGH);
    `META_TASK_TYPES` auto-derives from the dict keys (HIGH);
    `check_missing_fields`/`validate_plan`/`load_brief` are all top-level
    functions, not methods (HIGH).

**Net feasibility shift:** Gemini's table read as ~5 GREEN / 2 YELLOW / 2 HAND
with the heavy lifting hidden behind a non-existent stage abstraction. Verified
reality: the genuinely GREEN, low-risk Level-1 wins are A1, A6, A8 (and the new
A9). The two architecture-bearing changes (A4 main-branch, A7 validator-branch)
are real engineering, not mechanical inserts, and depend on a cross-Area decision
about how child briefs are carried in the plan payload.
