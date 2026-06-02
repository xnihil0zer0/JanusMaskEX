# JanusMaskJR — Continuation Plan (2026-06-02, rev 24) — DRAFT

> **rev 24 — DRAFT.** Compiled by the overseer/compiler from a 4-area **cross-vendor `agy` (Antigravity
> Gemini 3.5 Flash)** adversarial panel (reports `~/janusmask_briefs/review_rev24/R{1..4}_*.md`; `agy` ran
> READ-ONLY — repo tracked tree verified byte-UNCHANGED @ `8f4fd5b` post-run). Supersedes
> `JANUSMASKJR_CONTINUATION_PLAN_REV23.md`. HEAD at compile time = `8f4fd5b` (last REV23-exec landing). Every
> code anchor is @ `8f4fd5b`; **re-grep at the EXECUTE session's HEAD.**
>
> **CADENCE.** Per owner cadence this DRAFT is **adversarially Claude-reviewed NEXT session** (worktree
> sub-agents + compiler, codebase-memory-mcp grounded, every `[agy R#]` anchor re-grepped) and **EXECUTED the
> session AFTER.** `agy` is a known anchor/severity/COUNT hallucinator — every finding below carries the
> compiler's cross-check verdict **[CONFIRMED @live]**, **[REFUTED @live]**, or **[UNVERIFIED]**; the Claude
> review must re-verify all three classes.
>
> **STRATEGIC THRUST (owner directive):** move toward **long-horizon autonomy — one operator brief →
> JanusMask's planner auto-generates a LONG multi-task plan → the daemon executes it to COMPLETION
> unattended.** The first feature to be delivered this way is **Method D** (stateful/rule-based differential
> PBT, `method_d_report.md`). §3 below is the set of autonomy ENABLERS that must land before a long self-build
> plan can run to completion; §4 is Method D itself + the blockers that gate building it autonomously.
>
> **Governing rule (owner, carried verbatim):** use the JanusMaskJR PIPELINE for every change wherever
> possible; HAND-EDIT only AFTER a pipeline attempt FAILS with a PERMANENT/structural blocker (never a
> timeout/re-groundable stale-ground). Brief authoring delegated to `agy` + an independent Opus worktree
> sub-agent review; agents MUST use **codebase-memory-mcp** (`home-xnihil0zer0-JanusMaskJR`). `agy` is NOT
> tree-isolated → audit byte-clean + revert drift after EVERY run. QUOTE EACH pytest path SEPARATELY.
>
> **CARRIED PIPELINE-VIABILITY LESSONS (REV22+REV23 — violating these = guaranteed reject/regression):**
> - **NEVER edit a class method (2-part qualname)** via partial_edit — gemini deterministically emits
>   "SyntaxError: unexpected indent" (3/3). Restructure to top-level, or HAND-EDIT (e.g. MCP_RELAX `89d4d87`).
> - **A NEW top-level symbol must RIDE as an extra node in an EXISTING symbol's patch block** (paths.py
>   `relax_external_for` rode in `effective_target_root`). No new module-level Assign/import in a partial_edit.
> - **Large-symbol partial_edit can SILENTLY TRUNCATE the body** (syntactically valid but incomplete; AST gate
>   + narrow verification both miss it). MANDATORY: post-check the edited function's AST line-count vs baseline
>   after EVERY dispatch (STAGING_REROOT truncated 741→565 on attempt 1, caught by the guard, re-dispatched
>   clean). Truncation is NONDETERMINISTIC.
> - **A function with deeply nested try/except is gemini-untreproducible** (commit_accepted_output 191ln 3/3
>   "expected except/finally"). PERMANENT blocker → hand-land via a **worktree Opus IMPLEMENTER that proves
>   GREEN + returns `git diff` of prod files; overseer `git apply` + verify + commit** (COMMIT_REROOT `57ae36d`).
> - **Multi-file (2+ prod) tasks depend on agents emitting `__JANUSMASK_MANIFEST__` — NONDETERMINISTIC**
>   (worked 4×, missed 1× → only file[0] committed → verification_failed). Prefer SINGLE-FILE tasks or the
>   implementer-diff for multi-prod-file changes.
> - **`agy` mis-counts** (claimed `_exec_module` has 1 `build_jail_argv`; live AST has 6). Verify oracle
>   negative-controls against HEAD reality before dispatch.
> - A NEW module = a SINGLE-file task (`partial_edit:False`, embed reference source in implementation_notes).

---

## 0. Landed in the REV23-exec session — VERIFIED @ `8f4fd5b` (do not re-do) [agy R1 §5: invariants hold]
14 commits, 0 regressions, final sweep 1209 passed; §5 invariants confirmed @ HEAD (`synthesis_success`==1;
`_SENSITIVE_APPLY_GLOBS` incl `services/**`; `verify_extra_ro/rw` absent in `harness/config.yaml`; `full_stop`
absent; `relax_external_for` present). RELAX_PREDICATE `61a87e8`, BRIEF_ZOMBIE_RECLAMATION `f96944e`,
FLAG2_EMBEDDED_FUZZ `e1649e9`, EXTERNAL_ROOTS_ALLOWLIST `416caa7`, MCP_RELAX `89d4d87` (hand), BRIEF_LOAD_GUARD
`211fcaa`, STAGING_REROOT `0e351b4`, EXTERNAL_DIRTY_GATE `6c82828`, COMMIT_REROOT `57ae36d` (hand), MERGE_REROOT
`1fe5252`, G3_VENV(orch) `3b4c431`, T_RETARGET `c0056e1`, INTEGRATION_TEST `8ccbc8f`, WORKINGDIR_ENV_STAMP
`8f4fd5b`. External-targeting machinery COMPLETE but **INERT** (no external brief originated; `working_dir`
stays self / fail-safe).

---

## 1. Defects the REV23 landings INTRODUCED — fix EARLY (pipeline-viable) [agy R1]

**(1a) COMMIT_REROOT containment crash — `relative_to(worktree_root)` unconditional. [agy R1#1, CONFIRMED @live].**
In `harness/git_integration.py::_commit_accepted_output_multi` (`_contained` guard ~`:899-910`, then
`rel_str = str(target_path.relative_to(worktree_root))` `:915`) AND `_commit_accepted_output_patches`
(~`:1249-1256`): when containment is satisfied via the EXTERNAL `effective_target_root` branch (path under the
external root but NOT under `worktree_root`/staging), `_contained=True` passes the guard, but the UNCONDITIONAL
`relative_to(worktree_root)` then raises an unhandled `ValueError` → orchestrator crash. (Latent: external is
inert; the §3-9 integration test exercised the reject path, not this contained-but-not-under-worktree edge.)
- **Fix (pipeline):** compute `rel_str` against whichever root contained the path (worktree_root for the
  normal staging case; otherwise the external root), or reject cleanly — never call `relative_to(worktree_root)`
  unconditionally after the union containment passed. Same pattern at the singular path (`:707/:767`) — audit all 3.
- Oracle: external target_path under `effective_target_root` but not under `worktree_root` → clean rel/scoped
  reject (NOT ValueError); self path byte-identical.

**(1b) Bootstrap allowlist checked AFTER `mkdir`. [agy R1#2, CONFIRMED @live].** In
`harness/target_bootstrap.py::bootstrap_target`, `root.mkdir(parents=True, exist_ok=True)` runs `:202`
(when the path doesn't exist) BEFORE `_working_dir_allowed(root)` `:214` (which lives only in the `not has_git`
branch). So an unauthorized non-existent path gets its directory TREE created before the allowlist refuses
(git-init/marker ARE still blocked). LOW-MED (empty-dir takeover only), but the allowlist must gate `mkdir` too.
- **Fix (pipeline, single file):** call `_working_dir_allowed(root)` at function ENTRY (right after
  `root = Path(working_dir).resolve()`), before any `mkdir`. Re-validate the existing marker/dirty/foreign
  branches still behave. Oracle: unauthorized non-existent path → BootstrapRefused AND directory NOT created.

**(1c) G3_VENV unjailed-PATH "gap" — [agy R1#3, REFUTED @live].** agy claimed the sandbox-off external verify
runs unjailed without the target `.venv` on PATH. FALSE: `orchestrator.py:2086` already REFUSES (RuntimeError)
external + sandbox-off (FLAG2_ORCH); the `_vcmd_scrubbed_env()`-without-venv path at `:2087` runs ONLY for
SELF (correct — self needs no target venv). No action.

---

## 2. Deferred REV23 completion (pipeline-viable)

**(2a) G3_VENV_RUNNERS (§3-5 embedded/fuzz half) — re-author. [agy R2#1/#2; counts CORRECTED @live].**
agy R2 mis-counted (`_exec_module` "1 build_jail_argv"); **live AST: `narrow_fuzz/validation.py::_exec_module`
has 6 `build_jail_argv` refs + 2 `bind_credentials=False`; `embedded_test_runner.py::run_embedded_tests` has
2 + 2 (`:183/:231`, `:191/:239`).** Re-author as TWO SINGLE-FILE tasks (avoid the multi-file manifest issue):
- G3_VENV_RUNNERS_EMBEDDED (`run_embedded_tests`): for external (read `os.environ['JANUSMASK_WORKING_DIR']`,
  fail-safe-to-self), add `<root>/.venv` to `extra_ro` + prepend `<root>/.venv/bin` to `env['PATH']` at BOTH
  jail-build sites; REFUSE if `.venv` absent. Keep `bind_credentials=False` + net/IPC unshare + .venv-only bind.
- G3_VENV_RUNNERS_FUZZ (`_exec_module`): FIRST identify WHICH of the 6 `build_jail_argv` sites are the jailed
  CANDIDATE-execution paths (vs collection/metadata) needing the target venv; apply the same bind/PATH/refuse.
- Oracle: BEHAVIORAL (a test importing a lib present only in the target `.venv` passes jailed; fails-closed when
  absent), NOT a naive `bind_credentials=False` source-count (which broke the prior attempt).

**(2b) FLAG2 defense-in-depth INSIDE the runners — [agy R4#5, UNVERIFIED/optional].** The FLAG2 sandbox-off
external refusal is gated at the orchestrator CALL SITES (run_pipeline / orchestrator_worker.main), not inside
the runners. Add an in-runner guard (`refuse if not _target_is_self(working_dir) and not sandbox_enabled()`) as
belt-and-suspenders. Low priority; fold into (2a) if cheap.

---

## 3. LONG-HORIZON AUTONOMY ENABLERS — REQUIRED before a long self-build plan runs to completion [agy R2/R3/R4]

> These are the structural blockers to "one brief → long plan → execute to completion." Method D (§4) cannot be
> built autonomously until these land. Each is pipeline-viable (top-level symbols).

**(3a) Dependency success enforcement — `get_next_task` keys on `processed/` not `accepted`. [agy R2#4/R3#2/R4#1,
CONFIRMED @live `orchestrator.py:926`].** `unmet = [d for d in deps if f'{d}.json' not in processed_names]` —
`processed_names` (`:912`) includes REJECTED/rolled-back tasks. So a downstream task runs even when its
dependency FAILED → cascade failures + credit-burn across a multi-task plan. **Fix:** a dependency is "met"
only if ACCEPTED (present in the accepted ledger — `impl_progress.jsonl` `event=auto_commit` / the accepted
map), not merely in `processed/`. Block (don't stage/run) downstream tasks of a failed dependency. Oracle:
plan A→B; A rejected → B is NOT selected by get_next_task; A accepted → B selected.

**(3b) Staging dependency enforcement — `_auto_promote` stages downstream regardless of upstream failure.
[agy R4#2, CONFIRMED @live `autowork_daemon.py` `_auto_promote` staging loop].** Pairs with (3a) at the staging
layer: do not `stage_task` a task whose dependency is processed-but-not-accepted, so a failed upstream makes the
brief reach zombie state promptly (feeding the landed `_reclaim_zombie_briefs`). Oracle: failed-upstream brief →
downstream never staged → brief recognized zombie → quarantined.

**(3c) Unattended self-build APPROVAL channel — THE key blocker. [agy R3#4/R4#3, CONFIRMED @live
`git_integration.py:73` `_enforce_apply_scope`].** Every `harness/**` commit requires
`meta_task_type=='harness_self_fix' AND approval_ok`, where `approval_ok` comes from an operator-written
`state/control/decisions/<task_id>.json`. Under unattended execution NO operator writes these → a long
self-build plan stalls at the first auto-commit. (This session the overseer wrote all 15 decision files by
hand.) **Fix (DESIGN-GATED — owner must approve the trust model):** a TRUSTED-SELF-BUILD-PLAN mode where a
single operator-signed plan-level token (e.g. a signed marker the planner/daemon stamps onto a plan the
operator authored) auto-grants per-task approvals for `harness/**` tasks BELONGING TO THAT PLAN — never a
blanket bypass; scope strictly to the plan's task IDs + files_touched; fail-closed if the token/scope is
absent or mismatched. **This is a SECURITY-SENSITIVE relaxation → owner Phase-A re-review + Claude adversarial
review REQUIRED before it lands.** Until it lands, long self-build plans need the overseer-operator to sign
approvals (semi-attended), OR target NON-sensitive paths only.

**(3d) Fuzzer self-reference safety. [agy R3#5, UNVERIFIED/architectural].** The orchestrator uses
`harness/diff_fuzzer.py` (and sandbox/embedded) to VALIDATE submissions; a multi-task plan that EDITS those
very modules could wedge the validator mid-plan (import/syntax error breaks all subsequent tasks). **Fix:**
land fuzzer/validator changes ADDITIVELY (new functions, backward-compatible), and/or run validator-self-edits
through a pinned/snapshotted validator; sequence Method D tasks so the validator is never in a broken
intermediate state. Verify whether a broken `diff_fuzzer` import actually halts the orchestrator (UNVERIFIED).

**(3e) Planner depth + completion detection — VERIFY-FIRST.** Confirm the planner (`_run_planner_subprocess` →
`plan_hooks_*.json`) actually produces LONG (many-task) plans with correct `dependencies` for a feature brief
the size of Method D, and that brief COMPLETION is detected (all tasks accepted → brief done, distinct from
zombie). If the planner caps task count or omits dependencies, that is an additional blocker-task. (No
confirmed defect yet — scope a verification task + a multi-task fixture brief.)

---

## 4. METHOD D — first long-horizon feature (single brief → long plan → execute) [agy R3]

**Anchor corrections to `method_d_report.md` (CONFIRMED @live by agy R3#1/#2 — re-verify at review):**
`Sandbox`/`BatchRunner` are in **`harness/sandbox.py`** (NOT `diff_fuzzer.py`). There is **no `stateful_fuzz`
key** in `harness/planner/taxonomies.py`; `state_machine` currently has `'bypass_fuzzer': True` hardcoded — the
`stateful_fuzz` policy must be ADDED.

**Implementation tasks (the planner should decompose the operator brief into ≈these; each pipeline-viable):**
1. `extract_class_interface(code, class_name)` in `harness/diff_fuzzer.py` — AST-parse constructor + public
   method signatures (reuse the existing annotation parser).
2. `build_stateful_strategy(interface)` in `harness/diff_fuzzer.py` — Hypothesis strategy yielding
   `(init_args, [(method, args), ...])` action sequences (reuse `_strategy_for_annotation`).
3. Sandboxed trace executor `execute_stateful_trace(...)` — a driver run INSIDE the existing jail
   (`harness/sandbox.py` Sandbox/BatchRunner) that instantiates the class and replays the action sequence,
   returning a serialized result/exception trace per step.
4. `stateful_differential_fuzz(code_a, code_b, class_name, config, session_id)` in `harness/orchestrator.py` —
   generate sequences, run on both sandboxed instances, compare step-by-step via `outputs_match`/`_deep_compare`,
   shrink the failing trace.
5. Taxonomy flip in `harness/planner/taxonomies.py` — `state_machine`: `bypass_fuzzer: False` +
   `stateful_fuzz: True`; route stateful tasks to the new path instead of bypassing.
6. Equivalence + counterexample-shrinking + cross-examination prompt wiring (feed the shrunk trace to agents).
- **`_class_is_stateful` (`harness/rebuild/harvest.py`)** already detects stateful classes (currently routed to
  class-granular reconstruction + fuzzer bypass) — reuse it to gate stateful-fuzz eligibility.

**Blockers gating AUTONOMOUS Method D delivery (must land FIRST):** §3a+§3b (dependency correctness — Method D
is a dependent multi-task plan), §3c (unattended approval — every task edits `harness/**`), §3d (fuzzer
self-reference — Method D EDITS the fuzzer/orchestrator that validate it → highest self-reference risk; land
additively). §3e (planner produces a deep enough plan). Method D is the **acceptance test** for the
long-horizon-autonomy capability: a SINGLE operator brief (`method_d_report.md` distilled into a brief with a
`working_dir`-absent self target) → planner emits the ≈6-task plan → daemon drives all to accepted → Method D live.

---

## 5. Owner Phase-A 8-pt readiness (carried from REV23 §4) — OWNER-ONLY
(1) full unit-suite green; (2) jail write-denial + bwrap-flip mutant (failures-not-skips); (3) live self-synth
no-regression under jail; (4) §4-8 integration A–K green sandboxed AND sandbox-off — **agy R2#3 flags D/K not
fully satisfied until G3_VENV_RUNNERS (§2a) lands**; (5) AST scoping (creds/os_system/bare_except never bypassed
+ §1a JM-target never relaxed); (6) staging worktrees under `external_staging/` destroyed on success+failure;
(7) daemon restart clean; (8) allowlist integrity — **agy R2#3/R1#2: blocked by §1b bootstrap mkdir-order until
fixed.** THEN go/no-go on keeping `full_stop` removed. Note: §3c (unattended approval) is a NEW Phase-A-class
security decision — review it together with the above.

---

## 6. Invariants carried through EVERY phase (do-NOT) — re-verify @ HEAD
Carry ALL REV23 §5 invariants (synthesis_success==1; `_SENSITIVE_APPLY_GLOBS` incl `services/**`;
`verify_extra_*` absent/empty; SEC-1 fail-closed; CRED-EXFIL binds; FLAG2 refusal in all 3 execute families;
M2 self auto-allow / external `untracked_files=[]`; predicates fail-safe-to-self; `working_dir` STRIPPED at
`stage_task`/`impl_plan_to_queue` and only trusted via `persist_plan`→daemon→`stage_task`; JANUSMASK_WORKING_DIR
SET-OR-CLEAR per task; `JANUSMASK_PROJECT_DIR`/`PYTHONPATH` stay self; G2 relax NEVER applies to a target within
PROJECT_ROOT; one shared `relax_external_for`; external staging only under `external_staging/`; external accept
only on `janusmask/work` via ref-update; `bootstrap_target` external-roots allowlist; `brief_loader` rejects
in-PROJECT_ROOT non-self `working_dir`; `full_stop` REMOVED — Phase A active; `agy` not tree-isolated →
audit+revert). **ADD (rev24):**
- **Dependency tasks are "met" ONLY when ACCEPTED, never merely processed** (§3a/§3b).
- **No unattended `harness/**` commit without a SCOPED, plan-bound, operator-signed approval** — the
  trusted-self-build token grants approval ONLY for its plan's task IDs + files_touched, fail-closed (§3c).
- **Validator/fuzzer self-edits land additively** (never leave `diff_fuzzer`/sandbox/orchestrator in a broken
  intermediate that wedges the running validator) (§3d).
- **`bootstrap_target` enforces the external-roots allowlist BEFORE any `mkdir`** (§1b).
- **Commit-path `rel_str` is computed against the containing root, never an unconditional
  `relative_to(worktree_root)` after union containment** (§1a).

---

## Appendix — anchors (@ `8f4fd5b`; re-grep before use) + compiler cross-check log [agy R1-R4]
- `harness/git_integration.py`: `_enforce_apply_scope` `:43`/scope-gate `:73`; `commit_accepted_output` `:569`
  (union escape guard `:697-703`, singular `rel_str` `:707`/`:767`); `_commit_accepted_output_multi` `:851`
  (`_contained` `:899-910`, unconditional `rel_str` **`:915`** — §1a); `_commit_accepted_output_patches` `:1177`
  (`_contained` `:1249-1256` — §1a); `merge_staging_to_parent` (external ref-update onto `janusmask/work`).
- `harness/orchestrator.py`: `get_next_task` `:879` (dep check `:926` — §3a CONFIRMED); `_auto_commit_accepted`
  (working_dir reader, `_venv_jail_env` `:1893`, FLAG2 refusal `:2086`, verify spawn `:2081/:2087`).
- `harness/autowork_daemon.py`: `_auto_promote` staging loop (§3b); `_reclaim_zombie_briefs` (landed `f96944e`);
  `_runaway_counter_bump` `:622` / `_retry_blocked_tasks` `:867` (loop protections CONFIRMED working, agy R4#4).
- `harness/target_bootstrap.py`: `bootstrap_target` `:192` (`root.mkdir` **`:202`** BEFORE `_working_dir_allowed`
  **`:214`** — §1b CONFIRMED); `_working_dir_allowed` `:77`; `external_staging_root` `:86`.
- `harness/narrow_fuzz/validation.py`: `_exec_module` — **6 `build_jail_argv` + 2 `bind_credentials=False`**
  (agy's "1" REFUTED @live; §2a). `harness/embedded_test_runner.py`: `run_embedded_tests` build_jail_argv
  `:183`/`:231`, bind_credentials `:191`/`:239` (§2a).
- Method D: `harness/diff_fuzzer.py` (`_strategy_for_annotation`, `outputs_match`, `_deep_compare`);
  `harness/sandbox.py` (Sandbox/BatchRunner — NOT diff_fuzzer, agy R3#1 CONFIRMED); `harness/rebuild/harvest.py`
  `_class_is_stateful`; `harness/planner/taxonomies.py` `state_machine` (no `stateful_fuzz` key — agy R3#2
  CONFIRMED); tests `test_P5_orchestrator_stateful.py` / `test_P2_persist_gate_hypothesis.py`.
- **Compiler cross-check verdicts:** CONFIRMED @live — §1a, §1b, §3a, agy count-refutation of `_exec_module`,
  Method D anchor corrections. REFUTED @live — §1c (FLAG2 already refuses external+sandbox-off). UNVERIFIED
  (Claude review must check) — §3b exact staging anchor, §3d fuzzer-wedge mechanism, §3e planner depth.
- Panel reports: `~/janusmask_briefs/review_rev24/R{1..4}_*.md` (`agy`); `method_d_report.md`.
