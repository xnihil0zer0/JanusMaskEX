# Wire-Up Phase Research #1 — Integration Chokepoints

Goal: map the EXACT seams where a "WIRE-UP PHASE" (reachability/importer verification)
would slot into JanusMaskJR's build pipeline, to fix the "IMPLEMENTATION ≠ WIRED"
orphaned-module defect. All citations are `file:line` against the working tree at
research time.

---

## 1. Full path: worker completion → staged → accepted → committed

The pipeline is two processes: the **planner** (decomposes a brief into a plan of
tasks/leaves) and the **orchestrator worker** (`harness/orchestrator_worker.py`,
one subprocess per task). The worker is the integration engine.

### 1a. Worker control flow (`harness/orchestrator_worker.py::main`, line 152)

1. Claim the task: rename `tasks/<id>.json` → `.json.processing` (`:168`).
2. Run the two synthesis agents, AST-validate, synthesize (`:~200-465`).
3. **Branch on `meta_task_type` (mtt)** read at `:470`:
   - `META_TASK_POLICY[mtt].stateful_fuzz` → stateful-fuzz path (`:472`).
   - `mtt in BYPASS_FUZZER_TYPES or _skip_ifz` → smoke/embedded/narrow gates then accept (`:507-585`).
   - else → differential `fuzz_from_task` (`:586`), cross-examination rounds, or `decompose` (`:685-714`).
4. **Every accept branch funnels through the SAME 4-call chokepoint** (appears
   identically at `:484-505`, `:561-585`, `:599-623`, `:658-682`):
   ```
   _detect_and_append_untracked_tests(...)            # appends untracked test files
   orch._save_final_output(state_dir, task_id, code)  # writes state/output/<id>.py
   auto_commit_ok = orch._auto_commit_accepted(state_dir, task, task_id)   # ← THE chokepoint
   no_diff = not auto_commit_ok and _consume_no_diff_marker(...)
   if auto_commit_ok or no_diff: orch._mark_processed(...)   # DONE class
   else:                         orch._mark_blocked(...)
   ... set_phase('accepted') / _print_json_line({'outcome':'accepted'|'no_diff'|'rejected'})
   ```
5. **Terminal accounting** is `_print_json_line` (`harness/orchestrator_worker.py:73`).
   It writes the JSON outcome to stdout, flushes, THEN calls
   `_reap_spent_briefs_safe(payload)` (`:45`) which — behind the default-off
   `autowork.archive_spent_briefs` config flag — archives the spent brief/plan via
   `tools/brief_reaper.py::reap_for_task` (`:69`). This is the *post-accept* hook the
   memory note references, but it is **paperwork only** (moves `brief_*.md`/`plan_*.json`
   to `_autowork_archive/`); it does NOT touch code and is NOT a verification seam.

### 1b. The accept-and-commit chokepoint: `_auto_commit_accepted`
`harness/orchestrator.py:2342` (body runs ~2611-3331). This is where a candidate
becomes a real commit. Sequence inside it:

1. Resolve `files_touched` (`:2644`, via `_resolve_files_touched` at `orchestrator.py:1966`)
   and the target path; bail if empty/non-string (`:2645-2651`).
2. Resolve `worktree_root` + a **task-scoped staging worktree** `staging_path`
   (`:2670-2691`). SELF builds stage as a sibling `<repo>_<id>_staging`; EXTERNAL
   builds stage under `external_staging_root()`.
3. Auto-approve eligibility + content gate + TOCTOU pin (`:2788-2890`, only on the
   widened auto-approve path).
4. **Apply the candidate into staging**:
   `git_integration.commit_accepted_output(...)` at `orchestrator.py:2892`, INSIDE the
   `git_commit.lock` flock. This routes by artifact-form (see §4).
5. **Run the oracle (verification_command)** in the staging worktree:
   `vcmd = _resolve_verification_command(...)` (`:2915`, helper at `orchestrator.py:1996`);
   missing/empty vcmd → `verification_missing` rollback + `return False` (`:2916-2924`);
   the actual `subprocess.run(... vcmd ...)` is at `:3026`/`:3036`; non-zero exit →
   `verification_failed` rollback + `return False` (`:3062-3077`).
6. **Mutation gate** (re-run vcmd against mutants in a throwaway copy) `:3085-3262`.
7. Ledger `auto_commit` row (`:3264`).
8. **`merge_staging_to_parent(staging_path, worktree_root, ...)`** (`orchestrator.py:3271`)
   — this is the ff-merge that lands the commit on the real branch. Merge failure →
   `_mark_blocked('merge_failed')` + `return False` (`:3273-3279`).
9. **`_mark_processed(state_dir, task_id)`** (`:3285`) — the last durable DONE step.
10. `perform_process_handover` (`:3293`, skipped under pytest at `:3288`) then
    `return True` (`:3290`/`:3294`).

### 1c. The patches-path (`git_integration.py:1400` neighborhood)
`commit_accepted_output` (`git_integration.py:591`) dispatches by artifact sidecar
(precedence: `.patches.json` > `.files.json` > whole-file `.py`):
- `.patches.json` present → `_commit_accepted_output_patches` (`git_integration.py:697-698`,
  fn at `:1290`). It writes each rel target, enforces apply scope at `:1391`, and at
  **`git_integration.py:1429`** rejects a byte-identical patch as `no_diff`. **This is the
  partial-edit path that CANNOT create new files** — the gotcha in MEMORY: a NEW-file +
  `__JANUSMASK_PATCHES__` symbol → `auto_commit_failed`. Around line 1400 is the
  per-target worktree-write loop inside this function.
- `.files.json` present → `_commit_accepted_output_multi` (`:884`).
- else → whole-file AST-merge path (`:761-796`), which only MODIFIES ≤1 existing symbol.

**KEY OBSERVATION for wire-up:** the ONLY post-apply verification today is the leaf's
OWN `verification_command` (its isolated oracle) + the mutation gate. There is NO check
that any *live* module imports the new symbol/file. A leaf whose oracle is a standalone
`tests/.../test_<leaf>.py` passes step 5, merges at step 8, and is marked DONE at step 9
**while remaining an orphan** — exactly the documented defect. (`grep` confirms: no
existing importer/reachability/wire-up logic anywhere in `harness/`.)

---

## 2. Brief decomposition + oracle injection (`harness/planner/`)

### 2a. `_inject_oracle_sources` — `harness/planner/plan_normalizer.py:279`
For every non-`test_authoring` task with a dict `spec` and a non-empty
`verification_command`, it tokenizes the vcmd, resolves each `*.py` token under
`repo_root` (`:317-330`), and appends the committed oracle's VERBATIM source to
`task['spec']['implementation_notes']` under the literal marker
`COMMITTED ORACLE CONTRACT` (`:333-339`). Pure, idempotent, no-op when
`repo_root is None`. This is how the blind jailed worker "sees" the contract it must
satisfy — it never reads the oracle file directly.

Called from `normalize_plan` (`plan_normalizer.py:538`), which runs a fixed pass chain
(`:557-564`):
```
_dedupe_oracles → _enforce_module_first → _correct_meta_task_type_by_target
→ _sanitize_impl_verification_commands → _force_smoke_gated_leaf_impl
→ _inject_credential_naming_constraint → _inject_oracle_sources
```

### 2b. Brief → leaves (planner stages)
`harness/planner/cli.py` runs the leaf pipeline (`PIPELINE_STAGES`, `cli.py:9`):
`load_brief → blind_drafts → diff → reconciliation → attribution_stamp →
adversarial_review → auto_amend_gate → persist_plan`. Two synthesis drafts
(Claude+Gemini) are diffed/reconciled into a task list, then `normalize_plan` is applied,
then persisted to a plan JSON. An **epic** brief (`_should_run_epic`, `cli.py:117`;
`plan_kind=='epic'` carries `child_slugs`) instead emits child-epic/leaf slugs that the
daemon kicks off recursively (`autowork_daemon.py:1318-1319` reads `child_slugs`; the
auto-promote pass `_auto_promote` runs the planner on unplanned briefs, `autowork_daemon.py:~1377-1632`).

**Wire-up implication:** the plan/spec is where a leaf's *intended integration site*
could be declared (e.g. a new `wire_target` field naming the live module + symbol that
must import the leaf). `_inject_oracle_sources` is the natural template for a sibling
pass that injects a wire-up contract into the spec.

---

## 3. RECOMMENDED INSERTION POINT (wire-up verification, post-oracle / pre-DONE)

There is exactly ONE convergent seam and it is inside `_auto_commit_accepted`
(`harness/orchestrator.py:2342`). Every accept branch of the worker funnels here, and
within it the artifact is ALREADY applied into the isolated `staging_path` worktree and
has ALREADY passed its own oracle. This is the precise "AFTER it passes its oracle but
BEFORE it is marked DONE/committed" window.

### Primary insertion point
**`harness/orchestrator.py`, between line 3262 (end of the mutation gate, all gates
green) and line 3269 (the `merge_staging_to_parent` call at line 3271).**

Insert a `_wire_up_gate(staging_path, task, task_id, files_touched, worktree_root)` call
here. At this point:
- the new code is committed in `staging_path` but NOT yet merged to the parent branch,
- so a wire-up check can run statically/dynamically against the staged tree and, on
  failure, reuse the existing rejection machinery verbatim:
  `_rollback_rejected_commit(staging_path, result.get('sha'), target_rel, task_id, 'wire_up_failed')`
  + `git_integration.remove_staging_worktree(...)` + a `wire_up_failed` ledger row +
  `return False`. The worker then sees `auto_commit_ok == False` and routes the task to
  `_mark_blocked(...)` (orchestrator_worker.py `:491`/`:568`/etc.), making it
  re-claimable with the retry sidecar — identical to a `verification_failed` outcome.

This placement guarantees: (a) one site covers ALL accept paths (stateful/bypass/round1/
cross-exam); (b) failure cleanly rolls back with zero new commit on the real branch;
(c) no change to `orchestrator_worker.py` at all.

### What the gate would check (design space, not yet built)
- **Static reachability:** parse the new/changed symbols in `files_touched`, then grep
  the live tree (excluding `tests/`, the leaf's own oracle, and `venv/`) for an
  `import`/call referencing them; fail if zero live importers. Mirror the existing
  module-ordering importer walk already present at `harness/rebuild/discover.py:158`
  ("order modules so a callee precedes its importer") — that file proves the codebase
  already has import-graph tooling to borrow.
- **Spec-declared wire target:** if the plan/spec carries a `wire_target` (see §2b),
  assert that the named live module now imports the leaf symbol after the staged commit.

### Secondary (defense-in-depth) insertion point
`_resolve_verification_command` (`orchestrator.py:1996`) / the planner's
`_inject_oracle_sources` (`plan_normalizer.py:279`): inject a wire-up assertion into the
leaf's `verification_command` itself at plan time, so the EXISTING verify run (`:3026`)
also fails an orphan. This needs no orchestrator change but requires every leaf brief to
declare its integration site and is weaker (agent could satisfy a trivial import). Prefer
the primary seam; use this only as a planner-side complement.

---

## 4. meta_task_type routing — where dispatch lives, and where wire_up could fit

### 4a. Policy table
`harness/planner/taxonomies.py:1` — `META_TASK_POLICY` maps each mtt to
`{bypass_fuzzer, skip_structural_decomp, skip_smoke_gates, stateful_fuzz, ...}`.
Derived frozensets at `:2-5`: `BYPASS_FUZZER_TYPES`, `SKIP_SMOKE_GATE_TYPES`,
`SIDE_EFFECT_META_TYPES`. (e.g. `harness_self_fix`, `data_model`, `orchestration` are
bypass+skip-smoke.)

### 4b. Artifact-form dispatch (patches / whole-file / multi-file)
- **Prompt side:** `prepare_task_prompt` (`orchestrator.py:1479`) chooses the submission
  format using `_requires_verbatim_manifest(files_touched)` (`orchestrator.py:1461`):
  returns True (→ `__JANUSMASK_MANIFEST__` whole-file multi dispatch, `:1523-1525`) when
  >1 file OR any non-`.py` target; else for `partial_edit`/`BYPASS_FUZZER_TYPES` it emits
  the `__JANUSMASK_PATCHES__` partial-edit block (`:1519-1522`); single `.py` → whole-file.
  `test_authoring` adds an oracle-authoring block (`:1526-1527`).
- **Commit side:** `commit_accepted_output` (`git_integration.py:591`) routes by sidecar
  precedence `.patches.json` (`:697`) > `.files.json` (`:884`) > whole-file AST-merge
  (`:761`). See §1c.

### 4c. Gate dispatch (smoke / embedded / narrow / fuzz / stateful)
In `orchestrator_worker.py::main`: `META_TASK_POLICY[mtt].stateful_fuzz` (`:472`) →
stateful path; `mtt in BYPASS_FUZZER_TYPES or _skip_ifz` (`:507`) → smoke (`:509`),
embedded (`:532`), narrow (`:551`) gates (each skipped if `mtt in SKIP_SMOKE_GATE_TYPES`,
`:508`); else differential fuzz (`:588`). (A parallel copy of this dispatch also lives in
`orchestrator.py` ~`:3429-3433`/`:3624-3677` for the in-process path.)

### 4d. Could a `wire_up` meta-type / post-accept gate fit?
- A **new gate at the convergent accept seam (§3 primary)** is the cleanest fit: it is
  mtt-agnostic and runs for EVERY accepted leaf regardless of routing. Recommended.
- A **`wire_up` meta-type** could be added to `META_TASK_POLICY` to model an explicit
  *integration leaf* (a task whose job is to add the importer/call into a live module).
  This is orthogonal to the gate: the gate enforces "no orphans"; a `wire_up` leaf is how
  the pipeline *produces* the wiring when a build legitimately needs a separate
  integration step. If added, give it `bypass_fuzzer:True, skip_structural_decomp:True`
  (it edits an existing live file in place via the patches path) and ensure the gate does
  NOT recurse on the wire_up leaf itself (the wire_up leaf's "target" IS the live
  importer, so its own reachability is the human-declared site).

---

## 5. `make_seams` + SETTINGS_FRAGMENT + JANUSMASK_PROCEDURE_PHASE (phase hooks)

`overseer/turn_runner.py::make_seams` (`:99`) builds the four seams for
`overseer.driver.run_turn` (binary resolver, jail wrapper, env builder, runner). Relevant
to phase hooks:

- **Hook registration:** it writes `procedure_hook.SETTINGS_FRAGMENT`
  (`overseer/procedure_hook.py:175` =
  `{'hooks':{'PreToolUse':[{'matcher':'*','hooks':[{'type':'command','command':'python -m overseer.procedure_hook'}]}]}}`)
  to `work_dir/.claude/settings.json` (`turn_runner.py:137-139`). Because the spawn sets
  `CLAUDE_PROJECT_DIR = work_dir` (`_build_overseer_env`, used at `:88`) and runs with
  `cwd=work_dir` (`runner`, `:230`), Claude Code **auto-discovers** this project
  settings.json — so the PreToolUse hook fires with **NO jail-argv / bind change**.

- **Phase export:** the `env_builder` closure (`turn_runner.py:218`) reads
  `conversation['procedure_phase']` and, when present, exports it as
  `env['JANUSMASK_PROCEDURE_PHASE'] = str(phase)` (`:220-222`). Observe / non-procedure
  modes carry no phase → the env var is absent → hook stays inert.

- **Enforcement:** `procedure_hook.decide(event)` (`overseer/procedure_hook.py:150`)
  resolves the active phase from the event first, else falls back to
  `os.environ['JANUSMASK_PROCEDURE_PHASE']` (`:170`), computes a verdict via `_verdict`,
  and returns a Claude-Code PreToolUse decision dict — `permissionDecision:'deny'`
  (hard block, rc=2 to the agent) when out-of-phase (`:172-174`), else `allow`.

**Relevance to a wire-up phase:** this is the model for a *deterministic, hard-blocking,
phase-gated* discipline that JanusMaskJR already trusts. A wire-up phase in the
overseer/procedure FSM could add a `wire_up` phase whose `_verdict` permits only the
edit-the-live-importer action and refuses to mark the procedure COMPLETE until a wiring
assertion passes — the FSM analogue of the §3 build-pipeline gate. The env-var +
auto-discovered settings.json mechanism needs no change to carry a new phase value.

---

## Summary of load-bearing citations

| Concern | Location |
|---|---|
| Worker accept funnel (4-call) | `harness/orchestrator_worker.py:484,561,599,658` |
| Terminal accounting + brief reap | `harness/orchestrator_worker.py:73,45` |
| **THE commit chokepoint** | `harness/orchestrator.py:2342` (`_auto_commit_accepted`) |
| Apply into staging | `harness/orchestrator.py:2892` → `git_integration.py:591` |
| Oracle (verify) run | `harness/orchestrator.py:2915,3026,3062` |
| Mutation gate end | `harness/orchestrator.py:3262` |
| **Merge-back (→ pre-DONE seam)** | `harness/orchestrator.py:3271` |
| Mark DONE | `harness/orchestrator.py:3285` |
| **RECOMMENDED wire-up insert** | `harness/orchestrator.py:3263` (between 3262 and 3269) |
| Patches path (no-new-file) | `git_integration.py:1290,1391,1429` |
| Oracle injection into spec | `harness/planner/plan_normalizer.py:279` |
| normalize_plan pass chain | `harness/planner/plan_normalizer.py:538-564` |
| Planner leaf stages | `harness/planner/cli.py:9` |
| mtt policy table | `harness/planner/taxonomies.py:1-5` |
| Artifact-form prompt dispatch | `harness/orchestrator.py:1461,1479,1519-1525` |
| Commit-side dispatch | `harness/git_integration.py:591,697,884,761` |
| Gate dispatch (worker) | `harness/orchestrator_worker.py:472,507,508` |
| Existing import-graph tooling | `harness/rebuild/discover.py:158` |
| make_seams hook registration | `overseer/turn_runner.py:99,137-139` |
| Phase env export | `overseer/turn_runner.py:218-222` |
| Hook decision | `overseer/procedure_hook.py:150,170,175` |
