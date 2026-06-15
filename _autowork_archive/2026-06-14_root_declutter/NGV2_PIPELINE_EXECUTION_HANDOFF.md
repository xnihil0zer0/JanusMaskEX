# NGv2 + JM-Hardening Pipeline Execution — Continuation Handoff

Compiled 2026-06-07 ~23:20. Mission: implement three design docs **as epic briefs,
through the JanusMaskJR gated pipeline**, in order, **one epic at a time with an owner
checkpoint between each**, and **fix the ROOT CAUSE of every blocker via the pipeline
(or config/data by hand) as it is encountered** — never paper over a blocker with a
manual workaround that leaves the harness broken for the next epic.

Order (owner-confirmed):
1. `NGV2_GAP_BRIEFS.md` — Epics 1–4 (Epic 4 == the POC writer, detailed by doc #2).
2. `NGV2_POC_WRITER_DESIGN.md` — the full design for Epic 4 (PORT + BUILD-NEW).
3. `JANUSMASK_HARDENING_REPORT.md` — harden JM itself (H1–H6).

Owner decisions already taken this session (do NOT re-litigate):
- **Cadence = one epic, then checkpoint** for owner sign-off before the next.
- **Epic 4 PORT half = DO the verbatim JM→NGv2 file copies** (owner-authorized §9), in
  addition to building the 2 BUILD-NEW pipeline leaves.

---

## §0 PASTE PROMPT

Resume the NobleGreedv2 + JM-hardening pipeline build ("JM as factory"). Read FIRST:
memory `ngv2-cleanroom-rebuild-plan`, `ngv2-epic4-run-result`,
`never-hand-edit-production-outside-pipeline`, then THIS file. JM repo
`/home/xnihil0zer0/JanusMaskJR`; external target `/home/xnihil0zer0/NobleGreedv2`
(own git+venv `.venv` py3.13, JM-owned via marker). Continue from §1 STATE: finish the
in-flight Epic-1 analytics-ingestion run, checkpoint, then build Epic-2, Epic-3, Epic-4
(+PORT), then the JM-hardening epic — each through the pipeline, each followed by a
checkpoint. Author oracles by hand (sanctioned), drive the daemon hands-off per §3, and
fix every blocker at root cause per §4.

---

## §1 EXACT STATE NOW

**JM** `/home/xnihil0zer0/JanusMaskJR`, branch master.
- HEAD `c076c59` (LOCAL cleanup commit "archive stale completed-epic briefs…", UNPUSHED).
  Parent `3d3c576` (the pre-session pushed-ish HEAD; the 4 commits `b9454b7`/`923d54f`/
  `e3a0b7b`/`3d3c576` were already UNPUSHED at session start — verify before any push).
- **UNCOMMITTED (intentional, tracked) `harness/config.yaml`** — flag changes made this
  session (see §6). Do NOT revert mid-run. Also pre-existing unstaged edits to 4 archived
  briefs + 1 deleted brief (not ours; ignore).
- Gate `state/control/orchestrator.flag` = **`run`** (NOTE: the DAEMON does NOT honor this
  flag — it honors `state/control/autowork/pause` and `.../full_stop`. Neither exists now.)
- Allowlist `state/control/autowork/auto_promote.allowlist` = `ngv2_analytics_ingestion`
  (only). Comment-only = deny-all otherwise.
- **Daemon RUNNING**, pid in `/tmp/ngv2_daemon_pid.txt` (was 3702514), log
  `/tmp/ngv2_analytics_daemon3.log`, ledger baseline in `/tmp/ngv2_ledger_base.txt`.

**Epic-1 (analytics ingestion) — IN FLIGHT, healthy.**
- 5 hand-authored RED oracles COMMITTED to NGv2 `ac1e47c`:
  `tests/test_{findings,workers,progress,rlcf,portfolio}_export.py` (hermetic, build their
  own tmp_path fixtures, each has a WIRING test against the real consumer
  analyze_repos/analyze_workers/analyze_pipeline/RLState.record_outcome/load_portfolio).
- Root epic brief `brief_hooks_ngv2_analytics_ingestion.md` (frontmatter
  `working_dir:/…/NobleGreedv2`, `epic:true`, `child_epics:false`). Offline-planned →
  `plan_hooks_ngv2_analytics_ingestion.json` (epic record, child_slugs = the 5 exports).
  VET PASSED: 5 child briefs `brief_hooks_{findings,workers,progress,rlcf,portfolio}-export.md`
  each carry working_dir + exact module name `ngv2/<name>.py` + vcmd
  `python -m pytest tests/test_<name>.py -q`. NO leaf-name drift.
- Progress at handoff: `workers-export` + `rlcf-export` PLANNED (gemini-only, accepted via
  the §4-B flag). `T1_workers_export_module` built + PASSED its oracle but **FAILED to
  commit** → reject_rollback (see ACTIVE BLOCKER below). 0 NGv2 commits, 0 selfheal.
  Expect 5 NGv2 commits total once the blocker is fixed.
- **State left at handoff:** daemon STOPPED, gate `pause`, allowlist EMPTY (deny-all),
  NGv2 clean at `ac1e47c`. To resume: re-allowlist `ngv2_analytics_ingestion`, gate `run`,
  restart daemon (§3.5/3.6) — AFTER addressing the blocker. Blocker evidence preserved at
  `_autowork_archive/2026-06-07_root_metadata_sweep/blocker_evidence_T1_workers_export/`.
  The blocked task sidecars (`state/output/T1_workers_export_module.*`,
  `state/tasks/blocked/T1_workers_export_module.*`, `state/tasks/test_results/…`) still on
  disk — CLEAN them before any re-dispatch (stale-sidecar precedence, §7).

---

## §1b ACTIVE BLOCKER — NEW-FILE-AS-SYMBOL-PATCH cannot commit to an external worktree

**Symptom:** `error: pathspec 'ngv2/workers_export.py' did not match any file(s) known to
git` → outcome `auto_commit_failed` → `reject_rollback`. The module was BUILT and PASSED its
oracle; only the COMMIT step failed, so NGv2 master never advanced.

**Root cause (confirmed by inspecting the sidecars):** the synthesis worker emitted a
`state/output/T1_workers_export_module.patches.json` with a SINGLE entry
`{file:'ngv2/workers_export.py', kind:'symbol', name:'export_workers'}` — i.e. it
represented a brand-NEW whole-file module as a symbol-PATCH (the `.py` sidecar is just the
`__JANUSMASK_PATCHES__` literal, not a whole file). `commit_accepted_output`
(`harness/git_integration.py:644`, REV26 punb2a) makes the `.patches.json` sidecar
AUTHORITATIVE, dispatching to `_commit_accepted_output_patches`. That path resolves
`target_path = worktree_root/ngv2/workers_export.py` and `read_text()`s it (line ~1400) /
expects it to exist for `git add` (line 1426) — but the fresh EXTERNAL staging worktree is a
detached checkout of NGv2 `ac1e47c`, which has NO `workers_export.py`, so the new file is
never materialized into the worktree → `git add` finds nothing → 128. The whole-file/legacy
path (`shutil.copy2(output_file → target_path)` then `git add`, ~line 800) DOES create new
files — which is why all 67 Epic-4 leaves (emitted whole-file) committed fine. **This will
recur for EVERY new NGv2 module across Epics 1–4 whenever the worker chooses a symbol-patch
representation, so it is worth a durable fix.**

**ROOT-CAUSE FIXES (pick one; all routed through the pipeline per §4):**
1. **(preferred — `orchestrator_worker.py` is NOT deny-listed → auto-commits)** Make the
   worker emit a WHOLE-FILE submission (not a symbol-patch) when the target file is NEW /
   untracked in the target tree. The brief already says "single-file, whole-file"; enforce
   it at the output-representation step.
2. **(`git_integration.py` — DENY-LISTED → needs RED oracle + operator decision file)**
   Either: (a) in `commit_accepted_output`, do NOT let `.patches.json` win precedence when
   the sole target file is new/untracked — fall back to whole-file; OR (b) make
   `_commit_accepted_output_patches` treat a missing base file as base text `""` so a single
   whole-symbol patch CREATES the module (then `git add` the freshly-written file).
   RED oracle: an external-target commit of a NEW module emitted as one symbol-patch must
   land the file on the external master (build a tmp external git repo + staging worktree,
   feed a one-entry patches.json for a non-existent file, assert committed=True and the file
   exists on the parent).

**IMMEDIATE UNBLOCK (to finish Epic-1 without the harness fix — try FIRST, it's cheap):**
clean the T1 sidecars (`rm -f state/output/T1_workers_export_module.* state/tasks/blocked/
T1_workers_export_module.* state/tasks/test_results/T1_workers_export_module_*`),
clear the plan-attempt marker, re-allowlist + restart the daemon. Synthesis is
nondeterministic — it may emit WHOLE-FILE on the retry (which commits cleanly via the legacy
path). If it re-emits a symbol-patch, do the durable fix (option 1). A more deterministic
lever: tighten the child brief / plan so the task is unambiguously a NEW whole-file module
(meta_task_type `data_model` already; ensure acceptance criteria do NOT name a single symbol
to patch, which nudges the worker toward symbol-patching).

**NGv2** `/home/xnihil0zer0/NobleGreedv2`, master HEAD `ac1e47c` (will advance), clean.
- Consumers already built (ops_analytics, portfolio_intel, rl_debate_weights, etc.).
- Legacy sources (read-only, off-tree): `/mnt/ai-data/NobleGreed-legacy/data/{findings.db,
  worker_registry.db,portfolio_review.json}`, `.../knowledge/taint_specs/training/
  taint_specs.jsonl`, golden corpus already harvested to `data/ngv2/poc_submissions/` (27 pkgs).

**Cleanup done this session** (the root was choked with ~390 stale brief/plan files): ~454
files archived to `_autowork_archive/2026-06-07_root_metadata_sweep/{brief_hooks,plan_hooks,
docs,selfheal,tracked_briefs,tracked_docs,tracked_plan_hooks}/` with manifests. Root `.md`
216→10. KEPT (verified code-referenced — never archive): `brief_hooks_smoke.md`,
`plan_hooks_smoke.json` (harness/smoke_target.py), `plan_hooks_symbol_ledger_module.json`
(tests). The planner re-clutters root because `_run_epic_pipeline` (planner/cli.py:210)
writes `brief_hooks_<child>.md` to repo_root and `compute_brief_status` globs root; nothing
cleans up post-epic. **Proper fix = a harness change (writer+reader to a subdir, OR a
post-`epic_complete` archive step) — a candidate harness_self_fix, NOT a hand-edit.**

---

## §2 THE WORK QUEUE (remaining, in order; checkpoint between each)

| # | Epic | Target | Kind | Oracles to hand-author | Notes |
|---|---|---|---|---|---|
| 1 | analytics ingestion | NGv2 | 5 NEW leaves | DONE (committed `ac1e47c`) | IN FLIGHT — finish + sweep + checkpoint |
| 2 | submission fidelity | NGv2 | **MODIFY existing** + 1 new | `golden_corpus_regression` (new) + RED for `submission_parser` empty-title fix + `huntr_form` round-trip | submission_parser/huntr_form already exist → **symbol-patch**, higher synthesis risk than whole-file |
| 3 | taint training loader | NGv2 | 2 NEW leaves + wiring | `taint_training_loader`, `cwe_index` (+ `root_cause` wiring test) | after loader lands, HARVEST validated corpus → `data/ngv2/taint_specs/training/` |
| 4 | agentic PoC writer | NGv2 runtime | **PORT (copy)** + 2 BUILD-NEW leaves | `poc_writer` (drafter/reconciler seam) + `acceptance_gate` evaluator | PORT half = verbatim/ light-adjust copies (owner-authorized); see `NGV2_POC_WRITER_DESIGN.md` |
| 5 | JM hardening | **JM itself** | config + harness_self_fix | RED oracles for H3/H4/H5(/H6) | self-target → `harness_self_fix` meta + operator DECISION FILES; H1 partly done (§6) |

Per-epic build specs in §5.

---

## §3 PROVEN RUNBOOK — run ONE epic brief through the pipeline (hands-off daemon)

This is the validated recipe (Epics 1–4 + this session). For an NGv2 epic:

1. **Author the oracles BY HAND** (sanctioned — only oracles/tests may be hand-authored).
   One `tests/test_<leaf>.py` per NEW leaf, HERMETIC (build the fixture in `tmp_path`
   mirroring the REAL legacy schema), strong assertions, and a **wiring test** that feeds
   the leaf's output into the real consumer. **De-risk first:** simulate the leaf's expected
   output and run it through the real consumer in the NGv2 venv to confirm your wiring
   asserts hold (catches wrong consumer assumptions before the blind worker builds).
2. **Commit the oracles to NGv2** (`git -C /…/NobleGreedv2 commit`). The EXTERNAL_DIRTY_GATE
   refuses a dirty external tree, and oracle-injection reads the COMMITTED oracle.
3. **Author the root epic brief** `brief_hooks_<slug>.md` in JM root. Frontmatter:
   `working_dir: "/home/xnihil0zer0/NobleGreedv2"`, `epic: true`, `child_epics: false`
   (flat epic→leaves for a small set; true only if you want sub-epics). Body = Title /
   Scope / "Your decomposition task" (state module names are FIXED by their committed
   oracle imports — "reproduce EXACTLY") / capability list (one line per leaf, each citing
   `ngv2/<name>.py`, the contract, and `tests/test_<name>.py`) / Non-Goals / Inputs /
   Deliverables. Model on `brief_hooks_ngv2_analytics_ingestion.md` (and the archived
   `brief_hooks_ngv2_epic4.md`).
4. **VET the decomposition OFFLINE** (never while the daemon runs):
   `python3 -m harness.planner.cli brief_hooks_<slug>.md --output-plan plan_hooks_<slug>.json`
   This blind-drafts (claude+gemini), reconciles, WRITES `brief_hooks_<child>.md` per leaf +
   the epic `plan_hooks_<slug>.json`. **Inspect every child brief**: working_dir present?
   module name EXACT (matches the oracle import)? vcmd = `pytest tests/test_<name>.py -q`?
   If a name drifted, fix the root brief's wording, `rm` the generated children + plan,
   re-run. Writing `plan_hooks_<slug>.json` makes `compute_brief_status` treat the epic as
   `has_plan` (daemon won't re-decompose it); the daemon then plans/builds the CHILD briefs.
5. **Pre-flight gating:** NGv2 tree clean (`git -C … status`); remove any stale 0-byte
   `state/control/autowork/git_commit.lock`; clear `state/control/autowork/plan_attempts/
   <child>.*` backoff markers; ensure NO stale `plan_hooks_<child>.json` / `state/output/
   <tid>.*` / `state/tasks/<tid>*` sidecars. Allowlist the slug:
   `printf '%s\n' <slug> >> state/control/autowork/auto_promote.allowlist`
   (transitively admits children — verify with `harness.brief_status.
   _resolve_allowlisted_child_slugs(Path('.'), {'<slug>'})`, args are (repo_root, allow)).
6. **Start the daemon by EXPLICIT PID** (never pkill — self-kills → exit 144):
   `nohup python3 -m harness.autowork_daemon --state-dir state > /tmp/<slug>_daemon.log 2>&1 &
   echo $! > /tmp/ngv2_daemon_pid.txt`
7. **MONITOR** (background wait-loop; break on N NGv2 commits OR any
   `reject_rollback|"event":"blocked"|all_gemini_no_reconciled|empty_plan` OR any
   `selfheal` OR daemon death). Ground truth of acceptance = the `auto_commit` ledger row
   AND `git -C /…/NobleGreedv2 log` advancing (ignore a spurious worker-stdout
   `{"skipped":"not_found"}`). Do NOT run a pytest sweep or `planner.cli` concurrently with
   the daemon.
8. **On a child failure:** read worker stderr (`worker_exit` ledger `stderr_tail` +
   the daemon log); STOP the daemon by PID; **diagnose + fix the ROOT CAUSE per §4**; clean
   that child's sidecars + backoff marker; restart. Re-dispatch only after the fix.
9. **Close out the epic:** all children accepted (N NGv2 commits) → run the NGv2 suite green
   (`cd /…/NobleGreedv2 && .venv/bin/python -m pytest -q`) → STOP daemon by PID → empty the
   allowlist → set gate `pause` → **CHECKPOINT to owner** with results before the next epic.

**Manual-drive fallback** (if the daemon misbehaves for a single leaf): plan one child
(`planner.cli brief_hooks_<child>.md --output-plan plan_hooks_<child>.json`), `stage_task`,
then `python -m harness.orchestrator_worker --state-dir state --task-id <tid>` with
`JANUSMASK_WORKING_DIR=/…/NobleGreedv2` exported (the env auto-set only on the daemon path).

For the **JM-hardening epic (self-target)** the flow differs: oracle is a RED test under
JM `tests/`, the brief targets JM `harness/**` with `meta_task_type: harness_self_fix`, and
acceptance to a deny-listed path requires an **operator decision file** at
`state/control/decisions/<tid>.json` (approve). Drive it MANUALLY (planner.cli → stage_task
→ orchestrator_worker); do NOT start the daemon to modify the daemon's own posture.

---

## §4 BLOCKER PLAYBOOK — fix ROOT CAUSE as encountered

The directive is to fix the harness/config so the blocker cannot recur, not to hand-patch
the artifact. Classify, then route:
- **DATA/CONFIG blocker** → fix by hand (config is pipeline-exempt). Examples below.
- **HARNESS-CODE blocker** → fix via the pipeline as `harness_self_fix` (RED oracle → brief
  → planner → worker → operator decision file). NEVER hand-edit `harness/**` production
  (rule [[never-hand-edit-production-outside-pipeline]]). Non-deny-listed harness files
  (`planner/plan_normalizer.py`, `planner/cli.py`, `orchestrator_worker.py`, `tests/**`)
  auto-commit; deny-listed (`orchestrator.py`, `autowork_daemon.py`, `git_integration.py`,
  `planner/staging.py`, `agent_jail.py`, `paths.py`, `selfheal.py`, `services/**`, …) need
  the decision file.

**Blockers already hit + their root-cause fixes (DONE this session — keep them):**
- **`all_gemini_no_reconciled` (planner hallucination discard).** Claude's blind-draft
  doesn't reconcile on simple leaves → gemini-only plan → `_check_hallucination` rejects
  (autowork_daemon.py:1290). ROOT FIX = the CLAIM-A throughput lever, config flag
  **`synthesis.accept_single_agent_leaf_plans: true`** (the committed oracle stays the real
  correctness gate, so accepting a single-agent PLAN is safe). ALREADY SET.
- **Self-heal resurrection bypassing the allowlist.** `selfheal_auto_promote: true` makes
  the daemon harvest stale `self_healing_history.jsonl` into `brief_hooks_selfheal_*.md` and
  auto-dispatch them PAST the allowlist (the `_is_selfheal_brief` fast-path). With
  `auto_approve_sensitive_harness: true` those could even auto-commit to JM. ROOT FIX =
  config **`selfheal_auto_promote: false`** (fully gates the harvest, selfheal.py:268, AND
  dispatch). ALREADY SET. (If the next session sees fresh `brief_hooks_selfheal_*.md`,
  the flag flipped back — re-disable it.)
- **Stale 0-byte `git_commit.lock` wedges the daemon.** Remove it pre-flight (done).

**Blockers to ANTICIPATE (from prior-epic memory):**
- **`meta_task_type: io_adapter` + external imports.** The diff/import fuzzer can fail to
  resolve external (ngv2.*) imports for io_adapter leaves (Epic-2 gap). The analytics
  extractors import only stdlib in the MODULE (consumers are imported by the ORACLE, run in
  the NGv2 venv), so they should pass — but if an io_adapter child fails on import
  resolution, the proven workaround is to steer `meta_task_type` to a smoke-gated type
  (`data_model`/`orchestration`) via the brief's plan-shape; the durable ROOT FIX is to
  teach the fuzzer to resolve external roots (a harness_self_fix in the fuzz layer).
- **smoke_failed retry budget = 1** (daemon `_DETERMINISTIC_OUTCOMES`) kills a flaky draft
  → re-stage after cleaning sidecars; a clean re-dispatch usually passes.
- **Modifying an EXISTING NGv2 module (Epic 2)** is a symbol-patch, not whole-file — large
  single-symbol edits truncate; keep edits < ~130 lines or split, and name the exact file +
  exact symbol in the brief. The oracle must pin the new behavior precisely.
- **vcmd self-rooting / working_dir propagation** were FIXED in prior epics
  (plan_normalizer roots vcmd at the external working_dir; daemon `_spawn_worker` sets
  `JANUSMASK_WORKING_DIR`). If an external child's vcmd resolves to a JM-rooted smoke import,
  that regressed — re-fix in plan_normalizer (non-deny-listed, auto-commits).
- **Stale-sidecar precedence:** a surviving `state/output/<tid>.patches.json`/`.files.json`
  takes precedence over the `.py` and breaks re-dispatch ("invalid syntax line 1"). Clean
  `state/output/<tid>.*` + `state/tasks/processed/<tid>.json` + `*.processing` before re-run.

---

## §5 PER-EPIC BUILD SPECS

### Epic 2 — Submission & report format fidelity (NGv2)
Mostly HARDEN existing modules to round-trip the golden corpus losslessly.
- **Known bug G1:** `submission_parser.parse_submission_file` returns an EMPTY title for the
  golden `# <ID>: <Title>` H1 + `## Huntr Form Fields` / `### N. <Field>` layout. Author a
  RED oracle that parses a representative golden file and asserts non-empty title/repo/cwe;
  the fix is a format-coverage patch to the existing `ngv2/submission_parser.py` (symbol-patch).
- New leaf **`golden_corpus_regression`**: an oracle/module that parses ALL packages under
  `data/ngv2/poc_submissions/**` and asserts each yields a complete `FindingSubmission`
  (non-empty id/title/repo/cwe). This becomes the regression gate.
- **`huntr_form` round-trip**: `parse → build_form → render` over ≥3 representative packages
  (a JS web-vuln, a Python deser, a multi-finding pkg) matches the golden `### 4.
  Vulnerability Type` / `### 5. CWE` fields. CWE→vuln-type map in `huntr_form.CWE_VULN_TYPES`.
- Non-goals: no live huntr/network; do NOT rewrite the golden files (read-only exemplars);
  no analytics-ingestion overlap. Existing oracles to mirror: `tests/test_submission_parser.py`,
  `test_huntr_form.py`, `test_submission*.py`.

### Epic 3 — Taint training-corpus loader (NGv2)
- Source (read-only): `/mnt/ai-data/NobleGreed-legacy/knowledge/taint_specs/training/
  taint_specs.jsonl` (~36KB; rows `cwe/language/api_pattern/source_spec/sink_spec/ql_snippet`).
- New leaf **`taint_training_loader`**: stdlib-only JSONL → validated typed records; reject
  malformed rows (CWE regex, non-empty source/sink, language). Mirror `taint_spec_library`'s
  manifest discipline. New leaf **`cwe_index`**: group specs by CWE for lookup. Plus a
  `root_cause` consumption/wiring test over the loaded corpus.
- After the loader lands green, HARVEST a validated copy into `data/ngv2/taint_specs/
  training/` (data step, by hand, like the original harvest).
- Non-goals: no model training / GraphMERT / RLCF / GPU / CodeQL-semgrep execution.

### Epic 4 — Agentic PoC writer (NGv2 runtime) — see `NGV2_POC_WRITER_DESIGN.md`
TWO halves:
- **PORT (do the copies — owner-authorized §9; NOT pipeline work):** into a new NGv2
  runtime layer (`ngv2/` runtime + `hooks/`):
  - COPY-VERBATIM: JM `harness/ast_retry.py`, `harness/agent_jail.py`, `harness/dbus_proxy.py`.
  - LIGHT-ADJUST: `orchestrator_worker.py` (strip git/auto-commit/ledger; wire the pluggable
    acceptance gate at the accept point), `cross_examiner.py` (swap session-namer, drop
    `JANUSMASK_TASK_ID`), `sandbox_smoke.py`, `embedded_test_runner.py`.
  - REWRITE: the Stop hook `harness/hooks/claude/stop.py` `_decide()` → acceptance =
    "detonation reproduced" (keep `stop_hook_active` escape hatch + deny-counter); repoint
    `config/claude_worker_hooks.json`.
  Keep live detonation behind an owner-gated flag; default runner = `poc_runner.
  make_scripted_runner`/`make_mock_runner`. NEVER wire a real bwrap runner in build/test.
- **BUILD-NEW (pipeline, hand-author oracles):**
  - **`poc_writer`** — the drafter/reconciler seam contract.
  - **`acceptance_gate`** evaluator — composes `DetonationChamber.detonate(...).verdict ==
    'confirmed'` + `submission_readiness.check_submission_pkg(...).exists` + CWE-match into
    one `(bool, reason)`. Drive oracles with `make_scripted_runner`.
  - e2e demo (mock only): one finding → draft → detonate(scripted) → refine → `confirmed`.
- Inputs/seams: `detonation.DetonationChamber`, `poc_runner.make_scripted_runner`,
  `contracts.PoC/Finding`, `submission_readiness.check_submission_pkg`; golden corpus +
  taint specs as drafter contract-injection (local reads, no network).

### Epic 5 — JM hardening (`JANUSMASK_HARDENING_REPORT.md`) — self-target
- **H1 (config, by hand) — PARTLY DONE.** This session already set, in `harness/config.yaml`
  (UNCOMMITTED): `selfheal_auto_promote:false`, `auto_approve_sensitive_harness:false`,
  `auto_approve_ro_gate:false`. H1 also wants `autowork.enabled:false` **at rest** (but it
  MUST stay `true` while running epics 1–4). So: leave `enabled:true` until all NGv2 epics
  are done, then flip to `false` as the final resting posture. Commit the config flip as part
  of the hardening epic (or a clearly-labelled config commit) with owner sign-off.
- **H2 (data, by hand):** `state/control/autowork/full_stop` does NOT currently exist, so
  nothing to drop; if a `full_stop` is created later as the durable daemon stop, prefer it
  over `orchestrator.flag` (the daemon ignores `orchestrator.flag` — finding #5).
- **H3 (pipeline, cleanest):** `task_id` validator — `re.fullmatch(r'[A-Za-z0-9._-]+',
  task_id)` + reject `..` at `plan_validator` and defensively in `stage_task`/
  `impl_plan_to_queue`/`enqueue_subtasks`. Closes the path-traversal + staging-worktree
  escape. Low truncation risk.
- **H4 (pipeline, long pole):** harden `ast_enforcer._check_dangerous_calls` — flag
  `ast.Attribute` calls whose attr ∈ {exec,eval,system,Popen,…}, `getattr`/`globals`/
  `__import__`/`compile` by name, aliased dangerous imports (track import bindings), and treat
  `subprocess.*` as error not warning on self-targets. Budget 2–3 synthesis rounds; the
  ORACLE is the real assurance (mind the bootstrap irony — make it strong).
- **H5 (pipeline):** wire the daemon pause — make `_decide`/`_auto_promote` also honor
  `control.pause_flag_path` (`orchestrator.flag`), or document the split loudly.
- **H6 (optional):** re-run `validate_code` on the POST-MERGE file in
  `commit_accepted_output` so the content gate inspects committed bytes, not patch fragments.
- **Design epics (do NOT pipeline):** #1 jail net-egress allowlist; **#6 self-heal
  authorization redesign — see the full investigation in §8** (self-heal is DISABLED now and
  must be redesigned, not merely re-enabled). Surface, don't auto-fix.
- All H3–H6 land via `harness_self_fix` + a RED oracle (hand-authored) + an operator decision
  file; drive MANUALLY (no daemon).

---

## §6 SAFETY POSTURE + CLOSE-OUT

**Config flags currently set (UNCOMMITTED in `harness/config.yaml`):**
- `synthesis.accept_single_agent_leaf_plans: true` — KEEP for all NGv2 epics (throughput).
- `autowork.selfheal_auto_promote: false` — KEEP (prevents selfheal resurrection).
- `autowork.auto_approve_sensitive_harness: false` — KEEP (no silent JM self-commit).
- `autowork.auto_approve_ro_gate: false` — KEEP.
- `autowork.enabled: true` — KEEP while running epics; flip to `false` at final rest (H1).
Commit these (a `chore: default-off auto-approve posture for autonomous runs` commit) with
owner sign-off; they ARE the start of H1.

**Per-epic checkpoint (owner sign-off gate):** after each epic — NGv2 suite green, daemon
stopped by PID, allowlist emptied, gate `pause` — STOP and report (modules built, NGv2
commits, any root-cause fixes landed, JM sweep delta). Get sign-off before the next epic.

**Final close-out (after Epic-5):** JM serial sweep green (`python -m pytest -q -p
no:cacheprovider`, baseline ~ from memory — 0 NEW regressions); daemon dead; allowlist empty;
gate `pause`; `autowork.enabled:false`; NGv2 not in JM venv. Push JM (cleanup `c076c59` +
config + any harness_self_fix) WITH owner sign-off; push NGv2 separately. Update memory.

**Push posture:** nothing is pushed automatically. JM has UNPUSHED commits (`b9454b7`…
`3d3c576` from prior sessions + `c076c59` cleanup). Confirm with owner before any push.

---

## §7 GOTCHAS (quick reference)
- Kill daemon/workers by EXPLICIT PID; `pkill` self-kills the issuing shell (exit 144).
- Daemon honors `autowork/pause`+`full_stop`, NOT `orchestrator.flag` (finding #5).
- `auto_commit` ledger row + NGv2 `git log` = ground truth; ignore worker-stdout
  `{"skipped":"not_found"}`.
- External oracles MUST be committed before dispatch (EXTERNAL_DIRTY_GATE).
- Never run `planner.cli` or a big pytest sweep concurrently with the daemon.
- `_auto_promote_brief_eligible` is THE allowlist gate (extract AND plan-kickoff); only
  allowlisted slugs + their transitive epic children are touched.
- NEW module = single-file whole-file; MODIFY existing = symbol-patch (< ~130 lines/symbol).
- New top-level symbol → R-ANCHOR via implementation_notes (ride as a trailing node in an
  existing symbol's patch) so it auto-commits clean.
- Root re-clutters with `brief_hooks_<child>.md` after each epic — archive post-epic (or land
  the harness fix in §1).
- Oracles/tests may be hand-authored; ALL harness/** production goes through the pipeline.

---

## §8 DESIGN INVESTIGATION — re-enable self-heal SAFELY and PRODUCTIVELY

**Status: self-heal is DISABLED** (`autowork.selfheal_auto_promote: false`; the harvest
`selfheal.py:268` is a hard no-op and the daemon fast-path `autowork_daemon.py:2464` is gated;
verified 0 selfheal events on the corrected run). This is a STOPGAP, not a design. The task
here is to investigate a redesign that keeps the productive capability and removes the danger,
then land it as its OWN epic. This subsumes hardening finding **#6** (provenance attests bytes,
not intent). Default-OFF throughout; do not flip the legacy flag back on.

**Why disabled (the incident).** As built, self-heal harvested the ENTIRE Epic-4 self-heal
history from `state/control/autowork/self_healing_history.jsonl` on daemon restart and
auto-dispatched ~33 stale rebuild briefs **bypassing the operator allowlist**; with the
(now-off) `auto_approve_sensitive_harness` it could have auto-committed to protected JM paths.
Caught with zero damage, but it proves the design is unsafe.

**Current mechanics (read FIRST):**
- `autowork_daemon._escalate_to_autobrief` (:708) — on retry-exhaustion spawns an agent that
  writes a corrective `brief_hooks_<id>_fix.md` into the worker OUTBOX. **NOT gated** by the
  flag (still fires), but its output is inert unless harvested.
- `selfheal._harvest_selfheal_briefs` (:225, flag-gated) — copies outbox fix-briefs into
  repo_root as `brief_hooks_selfheal_<id>.md`, synthesizes `plan_hooks_selfheal_<id>.json`,
  mints an HMAC-SHA256 provenance marker (`_mint_provenance`; operator-only secret at
  `~/.config/janusmask/`, outside every jail), evicts the blocked-task sidecars.
- `autowork_daemon._auto_promote_brief_eligible` (:2464) — the self-heal FAST-PATH:
  `_is_selfheal_brief(slug) and _selfheal_auto_promote_enabled(config)` admits the brief
  **bypassing the allowlist**, provenance-validated.

**The unsafe properties a redesign MUST remove:**
1. **Allowlist bypass** — self-heal admits work without the operator's scoping control (root
   of the incident). The single most important thing to fix.
2. **Intent-blind authorization (#6)** — the HMAC proves the bytes weren't forged in a jail,
   NOT that the operator wanted THIS task healed; valid-provenance ⇒ auto-authorized.
3. **Stale resurrection** — the harvest re-reads `self_healing_history.jsonl` every restart
   with no TTL and no tie to a LIVE failed task, so old work resurrects unbounded.
4. **Self-modification reach** — a self-heal brief can target a deny-listed JM path and (with
   widened auto-approve) skip the decision-file gate.
5. **No GC** — self-heal briefs/plans accumulate in repo_root (also the §1 root-clutter source).

**Investigation axes (answer each, then design):**
- **A — Authorization = INTENT, not bytes.** Admit self-heal through the SAME transitive
  allowlist as epic children: a heal is eligible **iff the failed task's parent epic/slug is on
  the operator allowlist** (reuse `harness.brief_status._resolve_allowlisted_child_slugs`).
  This deletes the bypass. Extend the HMAC to bind `slug + brief-bytes + operator-intent token`
  (e.g. the allowlisted parent slug) so provenance proves un-forged AND in-scope.
- **B — Blast radius.** A heal MUST stay within the failed task's own `working_dir` and
  `task_id` (never invent new scope), and MUST NOT commit to a deny-listed JM path without the
  normal `harness_self_fix` + operator decision-file ceremony. `auto_approve_sensitive_harness:
  false` stays a hard precondition (a heal cannot widen its own approval).
- **C — Freshness / lifecycle.** Tie a heal to a LIVE failed task in the CURRENT run with a
  TTL; do NOT harvest arbitrarily-old history. Bound attempts (escalating backoff already
  exists). GC the brief/plan/provenance once the task resolves (accepted OR abandoned) — this
  also fixes the root re-clutter from §1.
- **D — Productivity evidence (decide IF it is worth re-enabling at all).** MEASURE the legacy
  loop first: parse `self_healing_history.jsonl` (~51 entries) + the run ledger — what fraction
  of self-heal attempts produced an ACCEPTED fix vs. churned/looped/were-discarded? Define a
  success metric + a kill-switch. Only re-enable if the diagnose→fix→accept rate is positive;
  otherwise self-heal is net token-burn and should stay off.
- **E — Default posture.** Default-OFF, behind a NEW explicit flag DISTINCT from the legacy
  `selfheal_auto_promote` (so the old unsafe behavior can never be re-enabled by that name),
  and only after axes A–C hold.

**Deliverable shape:** a design doc (like `NGV2_POC_WRITER_DESIGN.md`) + RED oracles pinning
the safety invariants — (i) a self-heal brief whose parent slug is NOT allowlisted is REJECTED;
(ii) a self-heal targeting a deny-listed JM path without a decision file is REJECTED; (iii)
no harvest of a history entry past its TTL; (iv) brief/plan/provenance GC'd after resolution;
(v) provenance fails if the intent token doesn't match the allowlist — then land the harness
changes via `harness_self_fix` + decision files (`selfheal.py` / `autowork_daemon.py` are
deny-listed). Sequence it AFTER the NGv2 epics and core JM hardening (H3–H5), since it builds
on the same trust-root + decision-file plumbing. Until then, leave self-heal OFF and durably
committed off (§6).
