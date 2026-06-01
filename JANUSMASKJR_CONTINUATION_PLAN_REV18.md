# JanusMaskJR — Continuation Plan (2026-06-01, rev 18)

> **rev 18 — written after the REV17 pipeline scope was executed (5 dual-agent landings + 1 hand-edit regression
> fix, master `8ce100c..e2554a2`, PUSHED to `origin/master`) and then adversarially re-reviewed by a 4-agent
> Antigravity/Gemini panel (reports in `~/janusmask_briefs/review_rev18/R{1..4}_*.md`).** Supersedes
> `JANUSMASKJR_CONTINUATION_PLAN_REV17.md`. **Governing rule (owner directive, carried):** use the PIPELINE for
> every change wherever possible; HAND-EDIT only after a pipeline attempt FAILS with a permanent/structural
> blocker (never a timeout, never a re-groundable mis-render that a re-dispatch would fix).
>
> **Verification discipline:** the rev-18 Gemini panel over-states in places (a known agy pattern); every panel
> claim below was cross-checked by the overseer against live code at HEAD `e2554a2` and is marked **[verified]**,
> **[verified-real]**, or **【agy-claimed; verify-first】**. Re-verify each `file:line` anchor before action — the
> panel's anchors drift. **This plan will be adversarially re-reviewed by Claude agents next session; trust the
> verdicts only after that re-verification**, exactly as rev-16/rev-17 did.
>
> **Round-2 update (same day):** a SECOND 4-agent review (reports `~/janusmask_briefs/review_rev18b/R{1..4}_*.md`)
> re-checked this plan AND researched **external-project capability restoration** (owner-requested — see new §3B).
> agy went rogue that round (ignored the SEED, edited a test, wrote no reports), so 4 **Opus** agents produced the
> round-2 reports (ground-truth, anchored). Round-2 corrections are folded in below (ROLLB-D `_auto_commit_accepted`
> is **613 lines, `:1473-2085`** — the earlier "~675" over-count was wrong; `_promote_fuzz_failures_to_tests`
> starts at `:2087`), `STAGING-RM` is `:1294`, new gap PARALLEL-WORKER-PGID; R1 regression suite **251 passed/0 fail**).
>
> **Round-3 update (2026-06-01) — Claude 5-agent adversarial re-review of §3B (THIS revision).** 4 Opus reviewers +
> the overseer (R5) re-audited the external-project restoration plan against live code @ HEAD. Six corrections
> reached ≥3/5 consensus and are folded into §3B / §4 / Appendix below, marked **[R3-CONSENSUS]**. The core false
> assumption corrected: the "SMALL ENUMERABLE self-pin set" is larger than listed AND it conflates two distinct
> roles — bindings that must **FOLLOW the target** (jail `repo_root`, agent cwd/`agent_workroot()`, `state_dir`,
> §1b relativity) vs. anchors that must **STAY SELF** (`JANUSMASK_PROJECT_DIR`, `${PROJECT_ROOT}` config tokens,
> vendored `.agents/` binaries, harness `import`/`PYTHONPATH`). T4's plan to re-point `JANUSMASK_PROJECT_DIR` was
> the most dangerous error (it would break harness imports + weaken 3 landed containment tests).
>
> **Round-4 update (2026-06-01) — Claude 5-agent adversarial re-review of §3B (THIS revision, focused on external-
> project restoration).** 4 Opus reviewers + the overseer (R5, who independently re-verified the disputed anchors
> against live code) re-audited §3B. The T1-T4 scoping-override anchors and the §3B-B bootstrap mechanics were
> found **unusually accurate** (every checked `file:line` exact or within `~`-tolerance); no FALSE-ASSUMPTION in the
> core safety-boundary/predicate logic. **Seven corrections reached ≥3/5 consensus** and are folded in below, marked
> **[…-CONSENSUS]**: (1) RISK (6) ELEVATED from 2/5 minority to an actionable item — mechanism corrected
> (`_watch_rebuild_jobs` does NOT consume `repo_root`, struck; the real hazard is a SELF/EXTERNAL split that could
> `git push` the JM repo under an external `state_dir`); (2) **new T5** gates `_auto_promote`/`_maybe_push_and_rebase_pin`
> to no-op when external; (3) the `embedded_test_runner` accept-reject gate (`repo_root=PROJECT_ROOT`) upgraded from
> "verify-first" to an OPEN PREREQ (it may validate the JM tree, not the target); (4) `interceptors.py:96` scoped to
> the Bash-command-validation workspace (Bash disallowed for both workers → near-inert; real write-scope is
> `pre_tool.py`), and the new override must be `JANUSMASK_TARGET_PROJECT` NOT the already-existing `JANUSMASK_WORK_DIR`;
> (5) `full_stop` external-mode note strengthened (silent kill-switch loss + supervisor `--state-dir` consistency);
> (6) RISK (3) scoped (discard only on stash-pop conflict; B1 `.gitignore` does not protect operator SOURCE); (7)
> `paths.py:53`→`:55` resolve anchor. REJECTED <3/5: `gemini/session_start.py:79`-is-docstring (R2 only), the
> coupling-assert implementation-site prescription (R1 only), the B3 `.venv`-symlink-must-be-real caveat (R3 only).
> **Round-4b (same day) — comprehensiveness trace:** a follow-up 3-agent full-lifecycle trace (owner asked "does
> §3B cover ALL the pieces?") found §3B handles the bind/commit/jail/bootstrap half well but leaves THREE whole
> stages unaddressed — task-origination, validation-content policy, and target test-execution. Folded into the new
> **§3B-C "Known coverage gaps"** below (G1/G2/G3). Net: as written, §3B would let JM spin up + commit into an
> external repo but have nothing to work on, reject most external code at the submit gate, and fail verification on
> any project with deps. G1+G2 are prerequisites; G2 includes an owner design decision (which AST rules stay-self vs
> relax-external).
>
> **Round-5 update (2026-06-01) — Claude 5-agent adversarial re-review of §3B, focused on external-project
> restoration.** 4 Opus reviewers + the overseer (R5, who independently grep-verified the two headline claims against
> live code). Anchors re-confirmed remarkably accurate (R4: ~95 claims checked, 0 WRONG, 2 OFF). **Five corrections
> reached ≥3/5 consensus and are folded in below, marked [R5-CONSENSUS]:** (1) **[HEADLINE — safety inversion]** T2's
> "compute `_target_is_self(worktree_root)` in `commit_accepted_output`" keys the decision off the WRONG root — the
> `worktree_root` PASSED there is the STAGING SIBLING (`orchestrator.py:1710` builds
> `worktree_root.parent/'<name>_<task>_staging'`, passed at `:1743`), which fails ALL THREE `_target_is_self` clauses
> → returns "external" → would **disable §1b for JanusMask's OWN self-builds**. The decision MUST derive from
> `state_dir`'s resolved git toplevel / `effective_target_root()` (both available in `commit_accepted_output`), never
> the staging `worktree_root` arg. (2) `JANUSMASK_TARGET_PROJECT` (T1) must be EXPORTED into the jailed agent env AND
> threaded through the daemon `_spawn_worker` Popen `env=` + the wrapper export, or the submit hook (no `worktree_root`)
> and the re-exec'd worker cannot see it. (3) T3's embedded-runner OPEN-PREREQ is RESOLVED: `run_embedded_tests` IS on
> the live accept/reject path (`orchestrator.py:2343`, `orchestrator_worker.py:332`) — it runs agent-submitted
> (external) code bound to the JM prefix and rejects on failure → must re-point + bind the target `.venv`. (4) T5 must
> gate the WHOLE `_auto_promote` body (EXTRACT loop + dry-run enumerate), not just push + planner-kickoff (consistent
> with G1). (5) anchor fixes: `decide_submission` def is `harness/hooks/_decide_common.py:80` (`:105` = the
> `rpc_submit_code.validate` RPC hop); `oracle_attach.py` → `harness/planner/oracle_attach.py`; `_spawn_worker` def is
> `:827` (not `~:835`). **Minority findings NOT applied (<3/5; flagged for owner):** G1 may overstate "no
> task-injection entry point" — the `state_dir/tasks/<id>.json` operator-staging path already dispatches with no brief
> (R3, verified `autowork_daemon.py:166/179-200`, `_decide` calls it with `state_dir`); `oracle_attach` mis-classify
> SKIPS oracle attachment rather than blocking (R3); RISK(6) consumer list omits `_autowork_watch_mtime:1435` (R3);
> `full_stop` loss also affects the `:1055` auto-promote pause (R1); `verify_extra_ro` config is an interim venv-bind
> stopgap (R2); `merge_staging_to_parent`'s `--ff-only` hard-fails on a diverged external parent (R2).
>
> **Round-6 update (2026-06-01) — owner design dialogue → new §3B-D "brief-driven external targeting" (REVIEW
> PENDING).** Following the Round-5 review, an owner design conversation produced a materially cleaner external-mode
> architecture, folded in as the new **§3B-D**: the target becomes a REQUIRED `working_dir` field on each brief (carried
> as trusted DATA brief→plan→task→binds), briefs move to a dedicated CONFIGURABLE directory with an internal/external
> **git-tracking split** keyed on `_target_is_self(working_dir)`, and the webUI authoring route (`webui/app.py:759`)
> classifies + places each brief server-side at creation. §3B-D **supersedes T1 + the COUPLING INVARIANT + G1's "required
> add"**, re-keys T2–T5 onto the brief field (the headline T2 staging-sibling bug cannot arise under it), and leaves
> G2/G3 orthogonal. **§3B-D is owner-proposed, NOT consensus-verified — the owner will run the 4-agent adversarial review
> next session.** Code seams cited were grep-verified this session; the design itself is unreviewed.
>
> **Round-7 update (2026-06-01) — Claude 5-agent adversarial review of §3B-D + §3B external-restoration coverage
> (THIS revision).** 4 Opus reviewers + the overseer (R5, who independently grep-verified the contested anchors against
> live code @ HEAD `4f6406e`) audited §3B-D (the previously-PENDING owner design) plus the full external-work lifecycle.
> Anchor accuracy was again high; §3B-D's safety/trust *intent* is sound, but **five corrections reached ≥3/5 consensus**
> and are folded in below, marked **[R7-CONSENSUS]**: (1) **[HEADLINE — §3B-D data-flow premise is FALSE]** `working_dir`
> does NOT ride the existing pipeline as trusted data — `brief_loader.py:66/160` keeps only `REQUIRED_SECTIONS` and
> SILENTLY DROPS `working_dir`; `PlanningBrief`/`blind_draft.py:128` don't carry it; `stage_task` (`staging.py:16`) reads
> only the plan JSON and can't stamp it → §3B-D needs NEW plumbing at ~5 seams PLUS a **trust fork** (the gate-selecting
> `working_dir` must be sourced from the operator BRIEF and stamped by trusted code, NEVER read from the agent-authored
> `plan_draft.json`, since the plan is drafted by the jailed agents). (2) the target-interpreter binding gap is BROADER
> than G3's four accept-gate spawns — the differential-fuzzer sandbox (`sandbox.py:1358/1543/1666`, all `sys.executable`)
> and the oracle/mutation gate (`test_author.py:70`, default `sys.executable`) ALSO run external code on the JM
> interpreter; **B3 + the G3 venv-bind are one atomic deliverable** (B3's installed deps are unreachable until the
> target venv prefix/bin is added to the verify-spawn `extra_ro`). (3) T1's env-threading note is WRONG — `_spawn_worker`
> (`:835`) is `Popen(cmd)` with NO `env=` (it INHERITS `os.environ`, so a `run-autowork.sh` export suffices; no Popen
> `env=` edit), and `decide_submission` does NOT make the §1b self/external decision (that is `commit_accepted_output`,
> a trusted process) — prefer reading `task.working_dir` from the inbox task (`_decide_common.py:86`) as the in-jail
> signal. (4) under §3B-D (`state_dir` stays self), the R1/R4 `full_stop` external-mode kill-switch loss is ELIMINATED —
> it applied ONLY to the original state_dir-external §3B. (5) G1's headline "no task-injection entry point" is overstated:
> the operator-staged `state_dir/tasks/<id>.json` path (`collect_dispatchable_tasks`/`_decide`, `:166`/`:1230`/`:1235`
> — passed `state_dir`, NOT `repo_root`; external-ready) already dispatches with no brief. **REJECTED / not-applied
> (<3/5):** R2's claim that `collect_dispatchable_tasks` is a "stays-self repo_root consumer" (it is `state_dir`-driven,
> CORRECTED here); the G3 "workroot reader/writer split" reframe (R3 only — `agent_workroot()` is zero-arg/single-env,
> no divergence; flagged for owner); the `--logs-dir`-already-exists relabel (R3 only). §3B-D STATUS upgraded from
> PENDING to REVIEWED below.
>
> **Read this first (state):** code-HEAD `e2554a2`; this plan was committed on top as `573cf6c` (= current
> `origin/master`) — production code is byte-identical between them (the commit adds only this `.md`), so every
> code anchor is checkable at the live HEAD. The 5 REV17 landings + the regression fix are
> in history `8ce100c..e2554a2`. Hard invariants re-verified intact (R4, per-file greps, §4): `synthesis_success
> = True` ×1 each; `skip_interface_fuzz` on `test_authoring` only (×1 each in 3 files); `_SENSITIVE_APPLY_GLOBS =
> ('harness/**','config/**','scripts/**')`; `BYPASS_FUZZER_TYPES` unnarrowed; `verify_extra_ro/rw` absent in
> `harness/config.yaml`; **`full_stop` PRESENT**. Phase A (lift `full_stop`) remains **OWNER-ONLY**.

---

## 0. Landed this session — VERIFIED (do not re-do)

All dual-agent via the pipeline except the final regression fix (hand-edit). Panel R1 confirmed integrate-diff
integrity + oracle non-vacuity on all 5 landings; R4 confirmed invariants intact and broad regression suites
green (114 + 192 passed). Anchors re-verified @ `e2554a2`.

| Commit | Item | Note (verified) |
|--------|------|-----------------|
| `592c77d` (oracle `99c1e7c`) | PARITY-2 | `ast_verifier.py:visit_ExceptHandler` bare-`except:` → ERROR only when body==`[Pass]`, else WARNING (aligns enforcer). submit ⊆ commit preserved (R1: no under-report). services/, no §1b. |
| `a4fbbab` (oracle `b2a6d58`) | DAEMON-SELFHEAL-UNTRACKED | `autowork_daemon.py:_escalate_inactivity` (~:1683) self-heal `Popen` → `_write_pidfile(state_dir,f'selfheal_{agent}_{task_id}',proc.pid)`. §1b. |
| `a93f6bd` (oracle `dbc270d`) | DAEMON-SUSPEND-LEAK | `_iteration` watchdog `:1388` `SIGTERM`→`SIGKILL` + tag `watchdog_kill` (SIGTERM deferred for T-state pid, then dropped from `_suspended_pids`). §1b. **Scoped to the minimal SIGKILL fix — startup/parallel residuals deferred (see §1 DAEMON-STARTUP-ORPHAN).** |
| `862f329` (oracle `1d226e3`) | WHOLE-FILE-DRIFT-GUARD | `git_integration.py:commit_accepted_output` legacy whole-file merge branch (post-`_ast_merge`) rejects when **>1 modified-EXISTING** top-level symbol (`set(before)&set(after)` differing `ast.dump`). Attempt-2 after the union→intersection re-ground. §1b. **Narrow by design — see §1 WFDG-2 for known coverage limits.** |
| `eda9e27` (oracle `fc911c6`) | R-ANCHORED-PATCH (keystone) | `git_integration.py:_apply_symbol_patch` allows bounded extra nodes (Import/ImportFrom/Func/AsyncFunc/ClassDef) alongside the single primary def, **1-part qualname only**, extras unparsed at col-0 before the splice; no-extras path byte-identical (R1 proved). Landed VIA PIPELINE (no hand-edit). Broad sweep 164 passed. §1b. **Makes "add a module-level import/symbol" pipeline-viable.** |
| `e2554a2` (hand-edit) | SUSPMGR-TESTFIX | `tests/unit/test_suspension_manager.py::test_watchdog_timeout` assertion `SIGTERM`→`SIGKILL`. Surfaced by R4 (the SUSPEND-LEAK verification_command omitted this file → it was RED in master). **Hand-edit justified:** pipeline attempt 1 `auto_commit_failed` — agents could not faithfully round-trip the **9-decorator `@patch` stack** on a whole-symbol replacement (pytest fixture-collection error) = structural blocker for this symbol shape, not a timeout. tests/, no §1b. |

**SKIPPED as empirical no-ops (R1 concurred):** MUT-HARNESS-ISO (`test_P2_mutation_kill.py` already restores the
tree byte-clean — premise false), BWRAP-PATH residual (all bwrap oracles pass on this host). Re-challenge only if
a non-standard host shows RED.

---

## 1. Panel findings — NEW / residual items (verify-first; agy over-claims corrected)

| Finding | Sev | Route | Overseer cross-check verdict |
|---------|-----|-------|------------------------------|
| **DAEMON-STARTUP-ORPHAN + PARALLEL-WORKER-WATCHDOG + PARALLEL-WORKER-PGID** (R1, R3, R2-rev18b) | MED | **PIPELINE** | **[verified-real]** Residuals of the minimal SUSPEND-LEAK fix: (a) the parallel `_spawn_worker` branch (`autowork_daemon.py` ~:1410-1417) has **no watchdog** — a suspended/hung parallel worker leaks its slot unbounded; (b) `_suspended_pids` is an in-memory global (~:37) — a daemon crash/restart between SIGSTOP/SIGCONT orphans the T-state pid (on restart, `_reap_running` `:296` `waitpid(WNOHANG)` raises `ChildProcessError` for non-children → treated as live since `os.kill(pid, 0)` succeeds → pidfile never cleared); (c) **PARALLEL-WORKER-PGID [new, R2-rev18b]:** `_spawn_worker` (def `:827` [R5 anchor fix, was `~:835`]) lacks `start_new_session=True` (the sequential launch `:1363` HAS it), so `_kill_process_group` (`:1879-1889`) cannot safely group-kill a parallel worker. **Gates (ii) unattended, NOT (i) supervised.** Fix: on daemon start, scan `_running_dir(state_dir)` for T-state/zombie pids and resume/kill them (cannot use `waitpid` for inherited orphans); align all `state_dir / 'running'` paths to `_running_dir(state_dir)` (fixes directory mismatch bug); add a hung-parallel watchdog checking pidfile mtime; add `start_new_session=True` to the parallel branch. §1b. |
| **SELFHEAL-UNTRACKED-2** (`_escalate_to_autobrief`) (R3) | LOW-MED | **PIPELINE** | **[verified-real]** `autowork_daemon.py:_escalate_to_autobrief` (def `:608`) does a bare `subprocess.Popen` at `:742` with **no `_write_pidfile`** — the SAME class as the landed `_escalate_inactivity` fix but a DIFFERENT function (the `:571` docstring even admits these paths "called subprocess.Popen directly, bypassing…"). My REV17 fix only covered `_escalate_inactivity`. Fix: capture the handle + `_write_pidfile` with a distinct stem, exactly like `a4fbbab`. §1b. Easy single-symbol win. **Also fold in SELFHEAL-STEM-COLLISION** [verified]: `_escalate_inactivity`'s `task_id` resolves to the static `'daemon_inactivity_stuck'`, so the `selfheal_{agent}_daemon_inactivity_stuck.pid` stem is overwritten across repeated inactivity escalations → older self-heal orphaned. Add a uniquifier using the spawned process PID (`proc.pid`) to avoid violating AST enforcer non-determinism checks with clock time. |
| **PARITY-3 (credential_leak)** (R4) | MED | **PIPELINE** | **[verified-real], same class as PARITY-1/2.** Submit-time `services/neurosymbolic/ast_verifier.py:~202-208` flags ANY string literal matching `CREDENTIAL_PATTERNS` as `credential_leak` severity **ERROR**; commit-time `harness/ast_enforcer.py:~74-87` only flags `security` ERROR on an *assignment whose target variable name* matches `(?i)(password|secret|key)`. So a credential-pattern string NOT bound to a credential-named var → DENIED at submit, ALLOWED at commit → interceptor ⊄ enforcer (blocks valid submissions; can stall pipeline runs containing test fixtures/example keys). Fix: downgrade the verifier's string-literal `credential_leak` to WARNING (or align to the enforcer's variable-name test). services/+tests/, no §1b. Easy win (mirror PARITY-2). |
| **STAGING-RM-NOTIMEOUT** (R2) | LOW-MED | **PIPELINE** | **[verified] anchor corrected to `git_integration.remove_staging_worktree` `:1294`** (NOT the agy-cited `~:1420`). No retry/timeout, so a jailed subprocess holding a handle → `git worktree remove`/`rmtree` `EBUSY`/hang locks future runs. Reliability gap; pairs with ROLLB-D. Add a bounded retry + sub-timeout. §1b. |
| **SEC-ENV (host-env leak)** (R2) | MED | **PIPELINE, agy-auth-risky** | **[verified]** `orchestrator.py:_build_agent_env` (`:220`, env built at `:260`) uses `{**os.environ, …}` → copies the FULL operator environment (incl. any `GITHUB_TOKEN`/cloud creds) into the jailed agent process env. Real exposure. **But the agents need auth/HOME/PATH** → naive whitelisting can break claude/agy auth. Fix: allowlist required keys (PATH, HOME, LANG, TERM, the agent's own auth vars) + explicit JANUSMASK_* in `_build_agent_env` and scrub/allowlist environment in `autowork_daemon.py` self-healing spawns (`_escalate_to_autobrief`/`_escalate_inactivity`); **MUST re-run the agy/claude auth smoke after and REVERT if auth breaks.** Treat like SEC-1 (careful, smoke-gated). §1b. |
| **KEYRING-UNFILTERED** (R2, R3) | LOW-MED | observe / pair-with-SEC-1 | **[verified] the keyring socket IS RW-bound** (`agent_jail.py:~242-245` binds `<XDG>/keyring`). An agent could query gnome-keyring secret collections. **Direct tension with SEC-1/agy auth** (agy needs the secret service). Do NOT blindly restrict — design jointly with SEC-1's xdg-dbus-proxy (a mock/throwaway keyring backend), behind the same auth-smoke gate. |
| **WFDG-2 (drift-guard coverage limits)** (R1, R4) | LOW | **PIPELINE (optional, caution)** | **[verified-real but low value].** The landed WHOLE-FILE-DRIFT-GUARD only counts modified-existing top-level **named** nodes, so it does NOT catch: module-level `Assign`/`Import` changes (no `.name`), renames (intersection empty), nested-symbol edits (only the parent counts as 1), or comment-loss (ast.dump-identical); and it is absent from the multi-file/patches dispatch paths. **CAUTION:** broadening risks false-trips on legitimate multi-symbol whole-file merges, and the patches/multi-file paths have their OWN scope gates (`_enforce_apply_scope`, `_apply_symbol_patch` shape). This is defense-in-depth on a rarely-used legacy path — only harden if a concrete abuse appears; do NOT over-engineer. |
| **R-ANCHORED forward-ref hazard** (R1) | LOW | optional hardening | **[verified-real, minor].** Extras are inserted IMMEDIATELY BEFORE the primary; an extra `class X(Primary)` would reference `Primary` before its (later) definition → `NameError` at import. The intended SEC-1 use is imports + standalone helpers (no such dependency), so low impact. Optional: insert extras AFTER the primary, or skip — revisit only if a real case needs it. |
| 【SEC-1 still live】 (R3) | HIGH | **PIPELINE (was hand-edit)** | **[verified-real].** D-Bus/systemd escape persists at HEAD (`agent_jail.py:~239-245` binds `<XDG>/bus`; shared IPC/PID ns → jailed agent calls `org.freedesktop.systemd1.StartTransientUnit` to spawn un-jailed host procs). See §3 item 5. |

---

## 2. Phase-A / daemon-enable gating (re-evaluated @ `e2554a2`)

- **(i) OWNER-SUPERVISED single foreground run:** minimal gating set remains **COMPLETE** (SEC-3, MUT-MASK,
  ATEST-STDERR, C2/ROLLB-A, C5/AGY2D, KILL-REAP all landed; R3 concurs). No new blockers from this session.
- **(ii) UNMONITORED autonomous daemon operation — remaining gating items:** **SEC-1** (D-Bus escape) +
  **DAEMON-STARTUP-ORPHAN / PARALLEL-WORKER-WATCHDOG** (the residual daemon-stability gap SUSPEND-LEAK's minimal
  fix left). SELFHEAL-UNTRACKED-2 + SELFHEAL-STEM-COLLISION + STAGING-RM-NOTIMEOUT are recommended hygiene.
- **Phase A itself (OWNER-ONLY, unchanged):** `pytest
  tests/adversarial/test_phase_a_selfheal_jail_writedenial.py -v`; confirm the bwrap-flip mutant (`agent_sandbox:
  bwrap:false` in `harness/config.yaml`) → **failures, not skips**; owner 8-pt review (tree clean, allowlist
  audited, never add `*_fix`); then `rm state/control/autowork/full_stop`. **Do NOT automate.**

---

## 3. Ordered next steps — PIPELINE-FIRST

Each pipeline item: Gemini drafts brief (`agy` — abs paths + `--add-dir`; FLAKY this session: timeouts /
stale-context / hard-resets, so an Opus sub-agent authored the fallback for ~half the briefs and ALWAYS reverts
agy tree drift before ingest) → Opus sub-agent adversarially reviews/corrects vs live code, proves oracle RED on
HEAD, confirms tree CLEAN → overseer ingests (`cp` taskspec→`state/tasks/<ID>.json` (state/ is gitignored),
oracle→`tests/`, §1b decision `state/control/decisions/<ID>.json` if `harness/**`, commit oracle RED-first, run
`.venv/bin/python -m harness.orchestrator_worker --state-dir state --task-id <ID>`, Monitor PID, verify
`{"skipped":"not_found"}`+HEAD-advance + scope + both submissions + targeted suite + invariants + tree clean,
push). **Apply PATCH_CONVENTIONS #1-#7. #8 is MOOT (VALIDATOR-SIG landed).** **NEW lesson (R-ANCHORED-PATCH):**
multi-symbol "add an import + helper alongside a single def" edits are now pipeline-viable for **1-part
qualnames** — but a whole-symbol replacement of a HEAVILY-DECORATED function (e.g. 9× `@patch`) or a
function-local target remains a structural blocker → hand-edit. Always include EVERY test that exercises a
changed code path in the `verification_command` (the SUSPMGR regression came from omitting one).

**Phase 1 — pipeline-viable easy/independent wins (do first; ordered):**
1. **PARITY-3 (credential_leak)** — downgrade `ast_verifier.py:~202-208` string-literal `credential_leak` to
   WARNING / align to enforcer's variable-name test, restoring submit ⊆ commit. services/+tests/, no §1b.
   Oracle: a submission with a credential-pattern string in a non-credential-named var clears submit-time.
   Mirror PARITY-2.
2. **SELFHEAL-UNTRACKED-2** — `_escalate_to_autobrief` (`autowork_daemon.py:608`, Popen `:742`): capture the
   handle + `_write_pidfile` with a distinct stem; **fold in SELFHEAL-STEM-COLLISION** (uniquify the
   `_escalate_inactivity` stem with the process PID `proc.pid` deterministically). §1b. Single-symbol; mirror `a4fbbab`. Oracle: both self-heal
   spawns write a tracked, collision-free pidfile.
3. **DAEMON-STARTUP-ORPHAN + PARALLEL-WORKER-WATCHDOG + PARALLEL-WORKER-PGID** — on daemon start, sweep
   `_running_dir(state_dir)` and resume/SIGKILL any orphaned process (waitpid raises `ChildProcessError` for non-children on restart); align `state_dir / 'running'` paths to `_running_dir(state_dir)` in `suspend_parallel_workers` and sequential worker cleanup; add a hung parallel worker watchdog checking pidfile mtime (suspension-age sweep in the parallel branch is a no-op); add `start_new_session=True` to `_spawn_worker` (def `:827`) so `_kill_process_group` (`:1879-1889`) can group-kill it. §1b. May need a startup-scan helper via R-ANCHORED-PATCH. Oracle: orphaned/hung parallel workers reaped; directory paths match; parallel sessions isolated.
4. **STAGING-RM-NOTIMEOUT** — `remove_staging_worktree` (`git_integration.py:1294`) has no timeout/retry; add a
   bounded retry + sub-timeout around `git worktree remove`/`rmtree`. §1b. Oracle: a busy/locked worktree removal
   fails fast (bounded) instead of hanging.

**Phase 2 — larger / security-critical (pipeline-attempt; hand-edit ONLY on a permanent/structural blocker):**
5. **SEC-1** — `xdg-dbus-proxy` sidecar filtering the session bus to `org.freedesktop.secrets`, blocking
   `org.freedesktop.systemd1.StartTransientUnit` (`agent_jail.py:~239-245`). **NOW PIPELINE-VIABLE** (R-ANCHORED
   lets the patch add imports; R2's concrete shape keeps all lifecycle logic nested INSIDE `build_jail_argv` —
   a single-symbol replacement, ~226 lines → **moderate gemini-truncation risk; if it truncates, re-ground once,
   then hand-edit**). **MUST ship a negated-PoC `tests/security/test_sec1_dbus_escape.py`** (jailed
   `StartTransientUnit` REFUSED; control with unfiltered bus succeeds). **MUST re-run the agy-auth smoke
   (`~/janusmask_briefs/agy_jail_smoke.py`) after and REVERT if agy/claude auth breaks** (the proxy filter can
   starve gnome-keyring/portal names). Pair the KEYRING-UNFILTERED decision here. §1b. HIGH security; deserves
   focused care.
6. **ROLLB-D / ROLLB-E** — try/finally over `_auto_commit_accepted` (`orchestrator.py` ~`:1473-2085`, **~613
   lines** — ends at line 2085; the remaining lines belong to `_promote_fuzz_failures_to_tests` which is a separate top-level function) and
   crash-safety over `run_pipeline`'s 13 `_mark_processed` sites (~`:2149-2479`, **~331 lines**).
   R2 proposes decomposing each via R-ANCHORED extras (thin wrapper + a new top-level helper). **Correction
   (over-claim):** the EXTRACTION patch still emits the full ~590-line body in one `new_block` → gemini
   truncation is NOT eliminated, only relocated. Pragmatic route: **(a)** attempt the whole-symbol/decompose
   patch via pipeline; **(b)** on truncation (permanent for this size) HAND-EDIT the mechanical
   extraction/try-finally (AST-equivalence-verifiable), then **(c)** pipeline the small subsequent
   try/finally additions on the now-small helper. §1b.

**Optional hardening (verify-first; only if a concrete need appears — do NOT over-engineer):** WFDG-2,
R-ANCHORED forward-ref ordering, SEC-ENV env allowlist (agy-auth-risky → smoke-gated).

**Phase A (OWNER-ONLY):** see §2.

> **Sequencing note:** items 2+3 edit `autowork_daemon.py`; item 6 edits `orchestrator.py`; items 1 (verifier),
> 4 (git_integration), 5 (agent_jail) are independent files. Run serially; re-ground each against the prior HEAD.
> Do SEC-1 (5) and SEC-ENV in dedicated, smoke-gated steps. Always serialize repo-touching work; never run
> agy/a sub-agent during a worker run; revert any agy `config.yaml` comment-strip.

---

## 3B. External-project capability restoration — PIPELINE-FIRST (NEW, owner-requested)

> **Goal:** restore JanusMask to a mode where it autonomously works INSIDE an EXTERNAL project (not its own
> repo). The strict gates today exist ONLY for self-build / self-replication safety; when a caller sets an
> external **target project directory**, those self-protection gates must NOT restrict work on that external
> project — they stay active ONLY when the target IS the JanusMask repo. For whatever project is targeted, JM
> should bootstrap (idempotently): a primary **git repo**, a **staging worktree** (for the blue/green
> `os.execv` handoff), and a **`.venv`**. (Round-2 R3+R4, Opus ground-truth, anchors verified.)

**Architecture (verified @ HEAD).** The harness has TWO root anchors:
- **Dynamic `state_dir` anchor — already external-ready.** Every live-tree git op derives `repo_root` from `git
  rev-parse --show-toplevel` with `cwd=state_dir`/`state_dir.parent` (`orchestrator.py:~1700`,
  `git_integration.py:~600`, `orchestrator_worker.py:93`). So **placing `state_dir` inside an external repo
  already makes commits/worktrees land there** — no change needed for the commit path itself.
- **Static `PROJECT_ROOT` anchor (`paths.py:17`, from `__file__`) — the self-pin.** It hardcodes "project == own
  repo" in a set that is **NOT as small as rev-18-round-1 claimed [R3-CONSENSUS]** and that splits into two roles
  the override MUST keep distinct:
  - **FOLLOWS-TARGET (re-point for external mode):** (a) the jail repo ro-bind — **TWO** agent-spawn sites, NOT
    one: `orchestrator.py:347` (`repo_root=PROJECT_DIR`, the foreground agent) **and `autowork_daemon.py:604`
    (`repo_root=PROJECT_ROOT_STR`, the daemon self-heal/spawn — the (ii)-unattended path §3B is actually about)**;
    the verify spawns (`orchestrator.py:1834/1959/1983/1997`) already use `repo_root=worktree_root` and are
    external-ready. (b) `agent_workroot()` (`paths.py:27` — NOT `~:51`) / agent cwd / `CLAUDE_PROJECT_DIR`. (c)
    the §1b sensitive-glob gate (below).
  - **STAYS-SELF (never re-point):** `JANUSMASK_PROJECT_DIR` + `PYTHONPATH` (the trusted-hook read-root + harness
    `import` anchor — consumed by `hooks_equivalence.py:74`, `interceptors.py:96`, `hooks/_paths.py:23`,
    `gemini/session_start.py:79`; asserted `== PROJECT_ROOT` by `test_agent_env_no_repo_leak.py:44`,
    `test_replication_clean_room_static.py:309`, `test_daemon_control_isolation_hooks.py:405`); `${PROJECT_ROOT}`
    config-token interpolation (`config.yaml:9/35/43/48` → vendored `.agents/agy`,`.agents/claude-code/…/claude`
    binaries; resolved `orchestrator.py:108`, `autowork_daemon.py:696/1754`) — re-pointing it would break agent
    launch. (`PROJECT_DIR` is NOT a `paths.py` symbol — it is an `orchestrator.py:42` alias for `PROJECT_ROOT`.)
  - **Critically — the §1b sensitive-glob gate** is the one self-guard whose suppression is the POINT of §3B.
    `_SENSITIVE_APPLY_GLOBS` (`git_integration.py:16`) are matched **relative to `worktree_root`** — but the
    relativization is done by the THREE CALLERS (`:665/:853/:1183`) before they invoke `_enforce_apply_scope`
    (`:43`), which itself takes already-relativized `rel_strs` and a `sensitive_globs=` kwarg and has **no
    `worktree_root` parameter [R3-CONSENSUS]**. An external project containing a `harness/`/`config/`/`scripts/`
    dir would be WRONGLY blocked. That gate needs an explicit, **fail-safe** bypass threaded through all 3 callers.

**SAFETY BOUNDARY (the hinge — do not get this wrong).** The self-build gates must bypass for external targets
but stay ON for self-edits. Derive the decision from the **RESOLVED `worktree_root` vs `PROJECT_ROOT`, NOT from
the env var alone.** Add `effective_target_root()` + a fail-safe predicate `_target_is_self(root)` in `paths.py`
that **`Path(raw).resolve()`-es** `root` first (matching `paths.py:55`; resolve BEFORE the `.parents` tests so a
symlink/relative path that lands inside the repo cannot defeat them) and returns **True (gates ON) whenever the
resolved target `== PROJECT_ROOT`, `PROJECT_ROOT in root.parents`, OR `root in PROJECT_ROOT.parents`** (the third
clause closes the ancestor/overlap loophole — pointing the target at a dir that CONTAINS the repo). **[R3-CONSENSUS]
This three-clause predicate EXTENDS the GAP_H3 pattern at `paths.py:62`; it does NOT "mirror" it — `:62` has only
the first TWO clauses and it `raise`s rather than returning a bool. Consider hardening `:62` itself with the
symmetric third clause for consistency.** A mis-set / relative / repo-inside / repo-ancestor target
**fail-safes to "self" (fully gated)**. Only an unambiguously-external resolved root flips gates OFF.
**[R5] COUPLING INVARIANT:** **[§3B-D RETIRES this — review both: under §3B-D the commit target comes from the brief
`working_dir` field, so `state_dir` stays self (daemon control plane) and need NOT live inside the external repo, which
also fixes the `full_stop` external-mode loss.]** because the §1b decision is derived from the git toplevel of `state_dir` (`git rev-parse
--show-toplevel` `cwd=state_dir`) — **NOT from the staging `worktree_root` arg threaded into `commit_accepted_output`,
which is always a `*_staging` sibling that fails the predicate [R5-CONSENSUS]** — when `effective_target_root() !=
PROJECT_ROOT` the `state_dir` MUST also resolve
inside the external target — assert this and fail-safe to "self" otherwise, so the env-var selector can never drive
the jail/workroot binds external while `state_dir` (hence the commit/§1b target) stays self. `full_stop`
stays keyed to `state_dir` (operator control — keep it; it is not a self-build artifact). **NOTE [R1/R4-CONSENSUS — safety-relevant]:** because
`full_stop` is per-`state_dir` (checked at `autowork_daemon.py:1238/:1517` against the passed `state_dir`), the
current JM-repo sentinel does NOT halt an external-mode daemon whose `state_dir` is the external repo — i.e. the
existing kill-switch silently stops protecting in external mode. The operator MUST place a `full_stop` under the
external `state_dir`. **And** the supervisor wrapper `scripts/run-autowork.sh:62` derives its own
`FULL_STOP_SENTINEL` from the wrapper's `--state-dir` arg, so the operator must pass the SAME external `--state-dir`
to BOTH the wrapper and the daemon — otherwise the supervisor re-spawns a daemon the external `full_stop` halted.
**[R7-CONSENSUS] This entire kill-switch hazard applies ONLY to the original state_dir-external §3B; under §3B-D
`state_dir` STAYS SELF (the commit target comes from the brief `working_dir` field), so the existing JM-repo `full_stop`
sentinel keeps protecting and the supervisor `--state-dir` consistency burden disappears. Prefer the §3B-D framing.**

**Phase 3B-A — scoping override (R3; PIPELINE-FIRST, §1b, serialize):**
- **T1** — **[§3B-D SUPERSEDES this env-var selector — review both: §3B-D carries the target as a brief `working_dir`
  field instead. The `_target_is_self()` predicate below is RETAINED by §3B-D; only the SOURCE of the root changes.]**
  add `effective_target_root()` + `_target_is_self()` to `paths.py` (resolver reads the
  **`JANUSMASK_TARGET_PROJECT` env var** — PREFER env over a config key so it survives `os.execv` re-exec +
  `_spawn_worker` Popen, neither of which is CWD-dependent; fail-safe `.resolve()` to PROJECT_ROOT on
  unset/empty/relative). **[R7-CONSENSUS — CORRECTS the prior R5 env-threading note, two factual errors]** `os.execv`
  preserves env only if the var is in the process `os.environ`, so it MUST be **(a) exported by
  `scripts/run-autowork.sh`** — and that is SUFFICIENT for the worker: `_spawn_worker` (def `:827`, Popen `:835`) is
  `subprocess.Popen(cmd)` with **NO `env=` argument → it INHERITS the daemon `os.environ`** (the prior "fresh dict, not
  inherited" claim was WRONG; no Popen `env=` edit is needed). Likewise `_build_agent_env` (`orchestrator.py:261`) is
  `{**os.environ, …}`, so the var reaches the jailed agent automatically as long as it is not scrubbed (it is not).
  **The prior justification "the submit hook `decide_submission` must read the self/external decision from this var" is
  ALSO WRONG:** `decide_submission` (`harness/hooks/_decide_common.py:80`) does AST validation + inbox write only — it
  makes NO §1b self/external decision; that decision is made exclusively in the TRUSTED `commit_accepted_output`
  (`git_integration.py`), never in-jail. Under §3B-D the cleaner in-jail signal (if one is ever needed for the G2
  content-policy split) is **`task.working_dir` already loaded from the inbox task at `_decide_common.py:86`** — no env
  propagation. New top-level
  symbols in a sensitive file → add via **R-ANCHORED-PATCH extras** on an
  existing 1-part symbol (extras are `ast.unparse`d → keep their bodies comment-free, or use a whole-file route).
  **[R3-CONSENSUS] Do NOT try to append the two new names to `__all__` via the extras route — `__all__` is a
  module-level `ast.Assign` (`paths.py:78`) and `Assign` is NOT an allowed R-ANCHORED extra kind (only
  Import/ImportFrom/Func/AsyncFunc/ClassDef) → it would `ValueError`. Either omit them from `__all__` (callers
  import by explicit name; `__all__` only governs `import *`) or take the whole-file route for paths.py.** Oracle:
  external dir → resolves to it; unset/relative/inside-repo/repo-ancestor → resolves to PROJECT_ROOT (gates ON).
  **[R3-CONSENSUS] Config-path fix is a SEPARATE edit, mis-located in round-1:** `orchestrator.py:47` is ALREADY
  absolute (`HARNESS_DIR / 'config.yaml'`) — leave it. The CWD-relative defaults that break when the daemon CWD is
  an external repo are `orchestrator_worker.py:28` (`Path('harness/config.yaml')`) and the daemon `--config`
  default `autowork_daemon.py:1571` (also the `:635`/`:1720` inline loaders, which have a `state_dir.parent`
  fallback). Anchor each on `HARNESS_DIR` so JM's own config loads regardless of CWD.
- **T2** — gate the §1b sensitive-glob check on `_target_is_self(...)`. **[R3-CONSENSUS] This is a
  MULTI-SITE change, not a single-symbol edit:** `_enforce_apply_scope` (`git_integration.py:43`) has **no
  `worktree_root` param** — it already accepts `sensitive_globs=`. **[R5-CONSENSUS — keys off the WRONG root, VERIFIED]
  Do NOT compute `_target_is_self` from the `worktree_root` PASSED to `commit_accepted_output`:** that arg is the
  STAGING SIBLING (`orchestrator.py:1710` `worktree_root.parent/'<name>_<task>_staging'`, passed at `:1743`), which
  fails all three predicate clauses → always returns "external" → would **disable §1b for JM's own self-builds** (the
  exact inversion the hinge exists to prevent). Instead compute the decision from **`state_dir`'s resolved git toplevel**
  (`git rev-parse --show-toplevel` `cwd=state_dir` — the same value §1b/commit already targets) **or
  `effective_target_root()`** — both available inside `commit_accepted_output` (`:569`) — once, plus its multi/patches
  subroutines, then pass `sensitive_globs=()` (external) at **ALL THREE** call sites `:665` (singular), `:853`
  (multi-file), `:1183` (patches) — uniformly, or an external `harness/x.py` edit is allowed via one path and blocked
  via another. Oracle (per path): an external `harness/x.py` edit is allowed; a self `harness/x.py` edit still requires
  §1b — **including a self-build whose commit runs inside a `*_staging` sibling.**
- **T3** — re-point the jail `repo_root` bind to `effective_target_root()`. **[R3-CONSENSUS] re-point ALL
  agent-spawn binds, not just one:** `orchestrator.py:347` (`repo_root=PROJECT_DIR`) **AND `autowork_daemon.py:604`
  (`repo_root=PROJECT_ROOT_STR` — the daemon (ii) path, the primary autonomy path §3B targets)**; the verify
  spawns (`:1834/1959/1983/1997`) already use `worktree_root`. **[R5-CONSENSUS — OPEN PREREQ now RESOLVED, VERIFIED]**
  `embedded_test_runner.py:161/206` hardcode `repo_root=PROJECT_ROOT` (+ `state_dir=STATE_DIR` `:163/208`); this runner
  backs the embedded **accept-reject gate** and **IS on the live accept/reject path** — `run_embedded_tests` is invoked
  at `orchestrator.py:2343` AND `orchestrator_worker.py:332` and REJECTS the task on failure. For an external task it
  runs the agent-submitted (external) module bound to the **JM interpreter prefix**, so any external module importing
  third-party deps fails with ImportError → spurious reject. It MUST therefore be re-pointed:
  `repo_root`→`effective_target_root()`, `state_dir`→the external state_dir, and the target `.venv` prefix/bin added to
  its `extra_ro` + jailed PATH (the same venv-bind fix G3 prescribes for the verify spawns). (External-CORRECTNESS
  blocker, not a deferrable footnote.)
  **MUST also add `PROJECT_DIR` (the JanusMask root) to the `extra_ro` list at each re-pointed site
  when `effective_target_root() != PROJECT_ROOT` so the jailed agent can still `import harness`.** Oracle: jail
  argv binds the external root, ro-binds JM's tree, and allows importing harness.
- **T4** — re-point `agent_workroot()`/work_dir/cwd to the resolved target (keep the outside-repo isolation
  invariant relative to the TARGET). **[R3-CONSENSUS — REVERSED FROM ROUND-1] Do NOT re-point
  `JANUSMASK_PROJECT_DIR`, and do NOT edit `tests/adversarial/test_agent_env_no_repo_leak.py:44`.**
  `JANUSMASK_PROJECT_DIR`+`PYTHONPATH` are JM's trusted-hook read-root and harness-`import` anchor (consumed by
  `hooks_equivalence.py`, `interceptors.py:96`, `hooks/_paths.py`, gemini session_start; set at `orchestrator.py:260`
  and `autowork_daemon.py:584`); 3 landed containment tests assert `== PROJECT_ROOT`. Re-pointing it breaks
  `import harness` (contradicts T3's own `extra_ro` add) and weakens those invariants. The target follows via the
  **separate `JANUSMASK_TARGET_PROJECT` var (T1)** + the jail `repo_root` (T3) + `state_dir`.
  **[R3/R4-CONSENSUS, scope corrected]** `interceptors.py:96` reads `JANUSMASK_PROJECT_DIR` as the
  **Bash-command-validation** workspace (`validate_command`), NOT the agent's file-write scope — and Bash is
  disallowed for both vendored workers (`autowork_daemon.py:688` `--disallowedTools Bash,…`), so it is near-inert in
  the worker path. The authoritative agent write-scope is the PreToolUse hook (`hooks/claude/pre_tool.py`, rooted on
  `JANUSMASK_WORK_DIR`+`$STATE_DIR`+docs), which is ALREADY target-agnostic / external-ready. If a future
  Bash-enabled mode needs that validation workspace to follow the target, give it the **new `JANUSMASK_TARGET_PROJECT`**
  var (T1) — **NOT `JANUSMASK_WORK_DIR`, which already denotes the per-spawn outside-repo scratch dir** (set
  `autowork_daemon.py:721/1775`, authoritative in `hooks/_env.py:54`) and would conflate the two roles. Do not move
  the shared `JANUSMASK_PROJECT_DIR`. Oracle: agent cwd is outside the target repo; `import harness` still works; the
  3 leak/replication tests still pass UNCHANGED; a NEW test asserts the workspace var follows the target.
- **T5** — **[R3-CONSENSUS, new]** gate the daemon's self-build/promotion machinery on `_target_is_self(repo_root)`.
  §3B-A's T1-T4 re-point the binds but leave the daemon's own `repo_root = Path.cwd()` (`autowork_daemon.py:1574`)
  untouched — the root of the SELF/EXTERNAL split in §3B RISK (6). When `not _target_is_self(repo_root)`, NO-OP
  `_maybe_push_and_rebase_pin` (`:1447` — the JM-only `git push origin main` + `scripts/impl_rebase_drift_pin.py`)
  and **the WHOLE `_auto_promote` body** (`:1041`, reads `brief_hooks_*.md`/`plan_*.json` from `repo_root`).
  **[R5-CONSENSUS — broadened from kickoff-only, aligns with G1]** no-op is NOT just the planner-kickoff: short-circuit
  `_auto_promote` at entry when `not _target_is_self(repo_root)`, so the **EXTRACT loop** (`:1084-1112`, `plan_path =
  repo_root / plan_filename` `:1096` → `stage_task`, which would otherwise stage JM's own plan tasks with JM-relative
  `files_touched` into the external `state_dir`) and the **dry-run enumerate** (`:1057-1071`) are gated too.
  Keep `repo_root` self-anchored for the self-build machinery; the external target is carried by
  `state_dir`+`JANUSMASK_TARGET_PROJECT`+the jail bind. (`_watch_rebuild_jobs` `:882` does NOT consume `repo_root`
  — no change needed there.) §1b + gate-bearing daemon entrypoint → expect a hand-edit after a pipeline attempt;
  sequence with the §3B-B daemon-startup hook and re-run the (ii)-gating. Oracle: in external mode the daemon does
  not `git push` or stage JM's own briefs.
  *(Each Tn is a single-symbol partial edit where possible EXCEPT T2 (3-site thread), T5 (multi-site daemon gate),
  and the paths.py `__all__` caveat above.)*

**Phase 3B-B — target bootstrap (R4; PIPELINE-FIRST then one gate-bearing hand-edit):**
- New module `harness/target_bootstrap.py` (NEW FILE → new-file commit route, not symbol-patch), decomposed into
  idempotent single-symbol functions, each with a non-vacuous oracle:
  **B0** `git init` if no repo; **B1** write/ensure a `.gitignore` (`state/`, `.venv/`, `*_staging/`) so the dirty-parent fail-closed merge doesn't stash-churn; **B2** make an initial commit if the repo has no HEAD (worktrees REQUIRE a HEAD; must execute B1 before this to avoid staging untracked workspace files);
  **B3** `python -m venv .venv` **using `sys.executable`** if absent + install the **target project's OWN deps**
  (`pip install -e .` / `-r requirements.txt` when present), not merely `pytest` — else the project's tests fail to
  import. **[R5 clarification of the bind claim]** the jail `extra_ro=[sys.base_prefix, sys.prefix]` binds are
  derived from the **orchestrator/worker interpreter** (hardcoded at the verify spawns `orchestrator.py:1834` etc.,
  and at `embedded_test_runner.py:161/206`), NOT from the target `.venv`; the staging `.venv` resolves because it is
  a symlink into `worktree_root/.venv` which is ro-bound as `repo_root`. The real rule is therefore: build the
  target `.venv` from the SAME `sys.executable` the worker runs under (so its `base_prefix` matches the bound one),
  and smoke-verify `.venv/bin/python` resolves under the jail. **[R7-CONSENSUS — B3 is INERT without the G3 venv-bind;
  treat as ONE atomic deliverable]** building the venv from `sys.executable` aligns only `base_prefix` (stdlib); the
  venv's own `prefix` (its `.venv/…/site-packages`, where the deps B3 installs live) is STILL not in the verify-spawn
  `extra_ro` lists (`orchestrator.py:1834/1959/1983/1997`) and jailed `python` resolves from JM's `sys.prefix`, so the
  deps are unreachable until G3's venv-bind lands. Do NOT land B3 separately from the G3 venv-bind, and key B5
  idempotency on a recorded bootstrap-marker (e.g. `state/.bootstrap_done`) — NOT "files present", since a partial B3
  leaves `.venv` present but deps missing. **B4** create the staging worktree via the existing
  `create_staging_worktree(staging_path, parent_root=effective_target_root())` — pass `parent_root` EXPLICITLY (its
  `None` fallback does `git rev-parse --show-toplevel` from CWD → wrong repo under external CWD) and pre-check that
  `<target>.parent` is writable (staging MUST be a sibling: `create_staging_worktree` raises otherwise); smoke
  `merge_staging_to_parent(..., parent_root=effective_target_root())` preconditions;
  **B5** a top-level idempotent `bootstrap_target(root)` orchestrating B0–B4 (no-op when all present).
- **Hook (HAND-EDIT, gate-bearing):** a one-time `bootstrap_target(effective_target_root())` call at daemon
  startup in `run_daemon` + an optional `--bootstrap-target <dir>` CLI flag. (Gate-bearing daemon entrypoint →
  expect §1b + a hand-edit after a pipeline attempt.)

**RISKS (carry into execution):** (1) external venv jail binds — create the venv with `sys.executable` so
`base_prefix`/`prefix` match the binds; (2) the `os.execv` blue/green re-exec keeps the HARNESS interpreter —
fine, but the re-exec'd worker must still resolve the external `state_dir`/target; (3) **[R1/R3-CONSENSUS, scope corrected]** `merge_staging_to_parent`
fail-closes on a dirty parent: it `git stash push -u`es the whole tree, FF-merges, then pops — and discards
uncommitted external work **only on a stash-pop CONFLICT after the FF merge** (`git_integration.py:~1397-1419`:
`reset --hard` + `stash drop`), not on every dirty merge. The bootstrap B1 `.gitignore` mitigates JM's OWN
artifacts (`state/`, `.venv/`, `*_staging/`) but does **NOT** protect the operator's own uncommitted SOURCE from
that conflict-path discard → bootstrap must additionally warn (and ideally refuse) on a dirty target tree; (4) sibling-dir writability for the
`<name>_<task_id>_staging` worktree; (5) the §1b bypass MUST fail-safe to "self" on any ambiguity.
**[ROUND-3 CONSENSUS — ELEVATED from 2/5 minority; mechanism corrected & re-verified @ HEAD]** (6) the daemon's
`repo_root = pathlib.Path.cwd()` (`autowork_daemon.py:1574`) is pinned to the **JM repo** by the launcher
(`scripts/run-autowork.sh:33` `cd "${PROJECT_DIR}"`, default = the JM repo), while §3B re-points only
`state_dir`/`JANUSMASK_TARGET_PROJECT`/the jail bind — NOT this `repo_root`. This creates a SELF/EXTERNAL **split**
across the two genuine `repo_root` consumers: (a) `_auto_promote` (`:1041`) reads `brief_hooks_*.md`/`plan_*.json`
from `repo_root` (`compute_brief_status`) while staging tasks into the *external* `state_dir` → it enumerates JM's
own briefs into the external run; (b) `_maybe_push_and_rebase_pin` (`:1447`) does `git push origin main`
(`:1476/:1487`, `cwd=repo_root`) + runs the JM-only `scripts/impl_rebase_drift_pin.py` (`:1482`), gated only by
`push.enabled` under `state_dir` → an external-mode `state_dir` with `push.enabled` would **push the JM repo**.
**Correction (verified @ HEAD):** `_watch_rebuild_jobs` (`:882`) does NOT consume `repo_root` (the parameter
appears only in its signature, unused in the body; it is fully `state_dir`-driven) — STRIKE it from this list. Fix
in external mode (see new **T5**): no-op `_auto_promote`'s planner-kickoff and `_maybe_push_and_rebase_pin` when
`not _target_is_self(repo_root)` (an external project has no JM `impl_rebase_drift_pin.py`/`brief_hooks_*.md`
convention). **Preferred shape [R3]:** keep the daemon `repo_root` self-anchored for the self-build machinery and
route the target solely via `state_dir`+`JANUSMASK_TARGET_PROJECT`+the jail bind, gating the self-build paths to
no-op when the target is external — consistent with the COUPLING INVARIANT. (7) Per the **COUPLING INVARIANT** in §3B's safety boundary,
`state_dir` must resolve inside the external target so `worktree_root` (and thus the §1b/commit target) tracks the
override rather than the env var alone. **[R5 jail-integrity note — confirms NO silent weakening]** the bwrap
write-boundary, SEC-1 bus/keyring binds, and the operator-config/memory overlays are HOME/XDG-keyed, NOT
repo-keyed, so re-pointing `repo_root` (T3) does NOT drop them; the JM tree stays ro-bound via T3's `extra_ro`. The
ONLY protection §3B intentionally drops is the §1b self-glob gate (T2), and only on a verified-external resolved
root — so residual risk is concentrated entirely in the correctness of `_target_is_self`. **All of 3B is
(ii)-class autonomy work; it does not lift `full_stop` — but the §3B-B daemon-startup hand-edit shares the
`run_daemon` entrypoint with (ii)-gating, so sequence it AFTER DAEMON-STARTUP-ORPHAN and re-run the daemon-enable
gating checks (it is not fully orthogonal to the (ii) path).**

---

## 3B-C. Known coverage gaps — §3B is NOT yet comprehensive (Round-4 lifecycle trace; MUST resolve before execution)

> **Round-4 finding (2026-06-01, 3 Opus tracing agents, full external-work lifecycle trace @ HEAD).** §3B-A/-B
> comprehensively handle the **bind/commit/jail/bootstrap** half (where commits land, the §1b path bypass, jail
> binds, the daemon self-build no-op, venv/worktree provisioning) and *correctly protect* the self-build machinery.
> But §3B treats `_target_is_self()` purely as a **file-location / bind** bypass. Three whole lifecycle stages are
> unaddressed or only partial — **as written, §3B would let JM spin up + commit into an external repo but it would
> have nothing to work on, would reject most legitimate external code at the submit gate, and would fail
> verification on any project with dependencies.** Each gap below is anchored to live code; resolve (or consciously
> de-scope) before attempting external mode. Corroboration noted per item (which of the 3 tracers found it).

**G1 — TASK ORIGINATION / WORK-DISCOVERY: there is NO external task source (biggest hole; tracer-1).**
The ONLY task source in the entire pipeline is `compute_brief_status` globbing `brief_hooks_*.md` / `plan_hooks_*.json`
from `repo_root` (`brief_status.py:23/31`), and T5 deliberately keeps `repo_root` self-pinned. Consequences:
- **No external BRIEF/PLAN-convention source** — bootstrap (B0–B5) provisions infra but the only brief/plan discovery
  is `repo_root`-pinned, and the daemon CLI exposes only `--state-dir/--once/--dry-run/--config`
  (`autowork_daemon.py:1568-1571`) + §3B-B's infra-only `--bootstrap-target`. **[R7-CONSENSUS — the "no task-injection
  entry point" framing is OVERSTATED]** one target-agnostic injection path ALREADY exists: an operator-staged
  `state_dir/tasks/<id>.json` is dispatched with no brief and no plan by `collect_dispatchable_tasks` →`_decide`
  (`:166`/`:1230`; called with `state_dir` at `:1235` — its `repo_root`-named param resolves `<state_dir>/tasks/`, so
  it is `state_dir`-driven / external-ready, NOT `repo_root`-self). G1 is therefore a gap in *documentation +
  `working_dir`/`files_touched` semantics for external targets*, not a *missing capability* — document this path as the
  lower-level external entry (consistent with §3B-D, which makes the brief the higher-level origination unit).
- **T5's no-op is incomplete + the EXTRACT half is a CORRECTNESS hazard:** T5's wording no-ops only the planner-
  *kickoff*; the `_auto_promote` **EXTRACT loop** (`autowork_daemon.py:1084-1112`, `plan_path = repo_root /
  plan_filename` `:1096` → `stage_task`) keeps running against the self-pinned `repo_root` and would stage **JM's own
  plan tasks** (with JM-relative `files_touched`) into the external `state_dir`. Broaden T5 to gate the EXTRACT loop
  too (no-op when `not _target_is_self(repo_root)`), and the downstream `_decide`/`collect_dispatchable_tasks`
  consumers are already `state_dir`-anchored (external-ready) so they are fine once a real external source exists.
- **REQUIRED ADD:** **[§3B-D SUPERSEDES this framing — review both: under §3B-D the brief IS the origination unit
  (an external brief is just one whose `working_dir` is external), read from a dedicated CONFIGURABLE briefs dir
  decoupled from `repo_root`; the `state_dir/tasks/` operator-staging path remains as a manual lower-level injection.]**
  an external task-origination mechanism — minimally a `--inject-task <plan.json>` / external-brief
  glob root (decoupled from `repo_root`), or an operator-staged `state_dir/tasks/` convention documented as the
  external entry. Until this exists, external mode is non-functional regardless of T1–T5.

**G2 — VALIDATION-GATE CONTENT POLICY: `_target_is_self` is a path bypass only, never a content bypass (tracer-2;
embedded-runner corroborated by all 3). OWNER DESIGN DECISION REQUIRED.**
Three independent gates apply JM-self code policy UNCONDITIONALLY with zero target-awareness; none consults
`_target_is_self`:
- **Authoritative worker submit gate** `decide_submission → rpc_submit_code.validate → validate_code`
  (**[R5-CONSENSUS anchor fix]** def at `harness/hooks/_decide_common.py:80`; the `validate` RPC hop is `:105`)
  runs with **NO baseline** and a narrow `allow_nondet` set (`io_adapter`, `logging_observability`, `test_*`). Routed
  from both `claude/pre_tool.py` and `gemini/pre_tool.py`. → legitimate external `import uuid`/`random`, `os.system`,
  `eval`, `except: pass`, or an API-key-shaped string literal is **DENIED at submit time**, trapping the agent in the
  AST-retry loop **before** the orchestrator's baseline-aware path is ever reached. This is the dominant external-code
  blocker.
- **Submit interceptor** `ASTVerificationInterceptor` (`interceptors.py:54` → `services/neurosymbolic/ast_verifier.py`)
  and **commit enforcer** `validate_code` (`ast_enforcer.py:187-230`) repeat the same policy
  (`nondeterminism`/`security`/`os_system`/bare-except). The orchestrator's `_compute_target_baseline_violations`
  (`orchestrator.py:2904-2943`) only suppresses **pre-existing** violations, not new ones — and reads `Path(rel)`
  CWD-relative (`:2932`), colliding with the RISK(6) `repo_root=cwd()` JM pin (may read the wrong file / empty
  baseline → external code blocked *harder*).
- **`oracle_attach._target_is_self_modification` (`harness/planner/oracle_attach.py:30`)** detects "self" by the `harness/`
  **path-prefix** — exactly the JM-layout assumption §3B's resolved-root predicate is meant to retire, but §3B never
  lists it among the sites to re-base on `_target_is_self`. An external repo with its own `harness/` dir mis-classifies.
- **`taxonomies.py` `META_TASK_POLICY`** mixes generic types with JM-harness-only types; `bypass_fuzzer`/`allow_nondet`
  consequences are JM-tuned, so a generically-typed external task gets JM's full determinism + dual-agent-equivalence
  strictness. (The fuzzer ENGINE `diff_fuzzer.py` is target-agnostic — verified.)
- **DECISION (owner):** which rules INTENTIONALLY-STAY-SELF for ALL targets (e.g. `credential_leak` arguably should)
  vs. RELAX-EXTERNAL (`nondeterminism`, `os_system`, `eval`, bare-except). Then thread the self/external decision
  — **[R7-CONSENSUS, supersedes the R5 env-var note here] prefer `task.working_dir` read from the inbox task (already
  loaded in `decide_submission` at `_decide_common.py:86`) as the self/external signal — it is operator-trusted
  (brief-sourced) and needs NO env propagation; the `JANUSMASK_STATE_DIR`/`JANUSMASK_TARGET_PROJECT` env variant is the
  fallback only** — into `decide_submission` (`harness/hooks/_decide_common.py:80`), the interceptor
  (`interceptors.py:54`), and the enforcer caller. **Any external relax MUST be applied IDENTICALLY across all three
  (submit `validate`/interceptor/commit enforcer) to preserve the submit⊆commit PARITY invariant — relaxing one alone
  trades a submit-trap for a commit-trap.** **[R7-CONSENSUS] DROP `oracle_attach.py:30` from this list:** `attach_oracle`
  is UNWIRED on every production dispatch path (3 test callers only; the rebuild loop calls `author_oracle` directly),
  and its `harness/`-prefix mis-classify SKIPS oracle attachment (does not block) — re-base it only if/when it is wired
  into dispatch. **Until this split is decided + wired, the agent cannot get most real external changes past submit.**

**G3 — TEST EXECUTION AGAINST THE TARGET: the primary accept gate can't pass for real external projects (tracer-3;
venv-binding corroborated by tracer-2).**
- **TARGET VENV NOT BOUND ON THE ACCEPT GATE (highest impact in this stage).** The four verify spawns that decide
  accept/reject (`orchestrator.py:1834/1959/1983/1997`) — which §3B-A calls "already external-ready" — bind
  `extra_ro=[sys.base_prefix, sys.prefix]` = the **JM interpreter's** prefix, never the target `.venv`'s prefix/bin,
  and jailed `python`/`pytest` resolve from JM's prefix. B3 builds the target venv + relies on a `worktree_root/.venv`
  symlink ro-bound under `repo_root`, but never threads the target venv into these `extra_ro` lists or onto the jailed
  PATH. → any external project with third-party deps fails verification (ImportError) unless its `verification_command`
  hard-codes `.venv/bin/python -m pytest`. **FIX:** add the target `.venv` prefix/bin to `extra_ro` + prepend to PATH
  at all four sites, and make the unscoped-pytest rewrite invoke the target interpreter.
- **[R7-CONSENSUS — the target-interpreter gap is BROADER than these four spawns] TWO more execution stages run external
  code on the JM interpreter and are NOT covered by the accept-gate fix:**
  - **Differential-fuzzer dual-agent equivalence gate (HIGH).** Both candidate impls execute via `Sandbox.execute`
    (`diff_fuzzer.py:474` `sandbox_from_config(config)`), and the sandbox launches `[sys.executable, …]`
    (`sandbox.py:1358/1543/1666`) = the JM interpreter, never the target `.venv`. Any external task on a
    `bypass_fuzzer:False` type (`cli_tooling`/`refactor`/`io_adapter`/`test_authoring`/…) whose function imports a
    third-party dep makes BOTH fuzzer subprocesses ImportError → the equivalence gate fails BEFORE the accept gate is
    reached. FIX: thread a target interpreter/`sys.path` into `SandboxConfig`/`sandbox_from_config`, or restrict
    external fuzzer-eligible tasks to dep-free function bodies.
  - **Oracle / mutation non-vacuity gate (MED).** `test_author.run_oracle_against`/`oracle_is_non_vacuous`
    (`:58/:101`) default `python_exe=sys.executable` (`:70`); only the rebuild path threads a target venv
    (`rebuild/loop.py:369`). The moment external-brief oracle generation is wired (§3B-D OPEN-item a), `python_exe`
    must be derived from the target `.venv` or non-vacuity fails on target deps.
  **Net: "external mode is non-functional until G1+G2" must be strengthened — for any DEPENDENCY-BEARING target ALL
  execute-target stages (the four accept spawns + the fuzzer sandbox + the oracle gate) must bind the target interpreter.**
- **TEST DISCOVERY HARDCODED to `tests/` + `tests/test_import.py` fallback** (`orchestrator.py:1796-1803`,
  `test_scoper.py:16-17`): `get_relevant_test_files(staging_path, files_touched)` uses `tests_subdir="tests"`,
  `fallback="tests/test_import.py"`; the orchestrator caller never threads a target-specific value. → projects with
  `test/`, `src/tests/`, `pkg/tests/`, or no `tests/test_import.py` get mis-scoped / "file not found". `test_scoper`
  IS parameterized — thread a target `tests_subdir`/`fallback` (or derive from pytest rootdir).
- **`embedded_test_runner.py` SECOND static anchor T3 omits:** besides `repo_root=PROJECT_ROOT`, it passes
  `state_dir=STATE_DIR` at `:163/:208` (static). (This runner is the DD6 embedded-test canary for agent-submitted
  modules carrying `test_*`, NOT the target-test gate — so re-point only matters for that narrow case; document it.)
- **LOGGING lands in the JM repo:** `_configure_logging` defaults to `PROJECT_DIR/'logs'` (`orchestrator.py:78`) →
  harness logs write into JM's tree, inconsistent with the daemon's worker logs (`autowork_daemon.py:503`, which use
  `state_dir.parent/'logs'`, external-ready). `run-autowork.sh:35-36` also defaults `LOGS_DIR=logs` CWD-relative;
  §3B flags `--state-dir` for `full_stop` but never `--logs-dir`.
- **WORKROOT READER/WRITER SPLIT:** T4 re-points the workroot *writer* but four direct `agent_workroot()` *readers*
  (`autowork_daemon.py:542-543` `_get_errors_for_task`, `planner/blind_draft.py:32`, `scripts/impl_outbox_watcher.py:209`)
  must compute the SAME re-pointed root or they read drafts/error-reports from the wrong (JM-sibling) location.
  Enumerate these in T4's oracle.
- **MINOR:** `orchestrator.py:2726` last-resort ledger write to static `DEFAULT_STATE_DIR` (fallback-only; would write
  telemetry into JM state if `state_dir` ever unresolved in external mode).

**Correctly OUT of scope / external-ready (verified, no action):** the agent prompt body (`prepare_task_prompt`
`orchestrator.py:896-943`) is task-data-driven with no JM-self framing; the hook write-SCOPE (`pre_tool.py`,
WORK_DIR/STATE_DIR-rooted); `harness/rebuild/discover.py` (self-rebuild only); codebase-memory (no runtime coupling,
self-analysis tooling only); the `os.execv` re-exec (argv/env-preserving). These were checked and need no change.

**Sequencing:** G1 (task origination) and G2 (content-policy decision) are PREREQUISITES — without them external mode
does nothing useful and rejects most changes. G3 is required for any dependency-bearing target. Resolve G1+G2 design
first, then treat G3 as part of (or immediately after) §3B-B execution.

---

## 3B-D. Brief-driven external targeting (NEW — owner design, 2026-06-01; supersedes T1 + COUPLING INVARIANT + G1's "required add")

> **STATUS — ADVERSARIAL REVIEW DONE (Round-7, 4 Opus + overseer, 3/5).** The owner design is sound in INTENT
> (the brief `working_dir` field is the right trust-boundary home for the gate selector) but the Round-7 review found
> its central "flows as DATA, no new plumbing" claim FALSE (see **[R7-CONSENSUS]** in D1/the OPEN list): `working_dir`
> is dropped by the brief loader and not carried by any downstream struct, so §3B-D is a DESIGN that still needs ~5
> plumbing seams + a brief-vs-plan trust fork built before it is real. Where it conflicts with the env-var approach in
> §3B-A **T1** / the **COUPLING INVARIANT** / §3B-C **G1's "REQUIRED ADD"**, §3B-D is the intended replacement. **T2–T5,
> G2, G3 remain** — re-keyed onto the brief field as noted below. Code seams cited here were grep-verified @ HEAD.

**Core idea.** Make the target project a **REQUIRED `working_dir` field on every brief**, carried as trusted DATA from
authoring all the way to the commit gate — instead of the three disconnected operator knobs (`JANUSMASK_TARGET_PROJECT`
env + external `--state-dir` placement + `--bootstrap-target`) glued by the COUPLING INVARIANT. The target becomes a
property of the trusted instruction unit (the brief), not an out-of-band process selector.

**Why it is structurally better than T1's env var (seams verified):**
- The brief FILE is an operator-authored, **agent-unforgeable** artifact: agents can only `Write` under
  `JANUSMASK_WORK_DIR`/`$STATE_DIR`/whitelisted docs (`harness/hooks/claude/pre_tool.py:7-13`), never the brief glob
  root. So a `working_dir` IN THE BRIEF is operator-trusted input — the correct trust boundary for a gate selector.
  **[R7-CONSENSUS — CRITICAL TRUST FORK]** but the PLAN is drafted BY THE JAILED AGENTS (`blind_draft.py:135` spawns
  claude+gemini in planning mode to author `plan_draft.json`); the hooks gate the agent's write LOCATION, not the
  CONTENT of a plan field. So the gate-selecting `working_dir` MUST be sourced from the BRIEF and stamped onto tasks by
  trusted code, and any `working_dir` an agent emits into the plan draft MUST be discarded — the agent-unforgeable
  property holds for the brief FILE, NOT for plan-task fields.
- **[R7-CONSENSUS — the "flows as DATA, no new plumbing" claim is FALSE]** `working_dir` does NOT ride the existing
  pipeline today: `harness/planner/brief_loader.py:66/160` keeps ONLY `REQUIRED_SECTIONS`
  ({title,scope,non_goals,inputs,deliverables}) and SILENTLY DROPS any `working_dir` frontmatter key; `PlanningBrief`
  has no such field and `blind_draft.py:128` serializes a fixed field list without it; and `stage_task`
  (`planner/staging.py:16`) reads only the PLAN JSON (`:43`) and writes the task verbatim (`:58`) — it has no brief
  access and no `working_dir` param. So §3B-D requires NEW plumbing at ~5 seams — (1) stop dropping it in
  `brief_loader.py:66/160`, (2) carry it on `PlanningBrief` + `blind_draft.py:128`, (3) a planner/`stage_task`-side
  STAMP that writes the BRIEF's `working_dir` onto each task object (fed from the daemon at `autowork_daemon.py:1093`,
  NOT read from the LLM plan draft per the trust fork above), after which (4) `stage_task`'s verbatim copy carries it
  and (5) the worker/binds read it. This is LESS env-fragile than T1 but it is NOT zero-plumbing — the coupling work
  T1's COUPLING INVARIANT tracked is RELOCATED into the field + this plumbing, not eliminated.
- It **DECOUPLES `state_dir`** (the daemon's own control plane — keep self) **from the commit target** (per-task, from
  `working_dir`). This **fixes the `full_stop` external-mode kill-switch loss** (state_dir stays self → the sentinel keeps
  protecting) and **retires the COUPLING INVARIANT** (state_dir no longer has to live inside the external repo).

**D1 — `working_dir` brief field (REQUIRED; the single source of truth).** Every brief declares its target project root.
Self-rebuild briefs declare self (or omit → **fail-safe to self**). The field threads brief → plan (planner passthrough)
→ task json (`stage_task`) → dispatch → binds. The §1b / jail / commit decision keys off `_target_is_self(task.working_dir)`
— the SAME fail-safe 3-clause predicate (T1), now applied to an explicit trusted field rather than inferred from
`git rev-parse` of `state_dir`. This is the cleaner form of the T2 fix: the headline T2 bug (keying off the staging-sibling
`worktree_root`) **does not even arise**, because the decision comes from task data, not a path inference.

**D2 — dedicated configurable briefs directory (replaces repo-root scatter).** Briefs move off the JanusMask repo root
(today `brief_status.py:23` globs `repo_root.glob('brief_hooks_*.md')`; the root holds 11 `brief_hooks_*.md` + dozens of
scratch files; `_archive/` is already special-cased) into a dedicated dir. **THREE consumers must rebase onto the new
root** (leave none pinned to `repo_root`): the glob (`brief_status.py:23`), `_auto_promote`'s `plan_path = repo_root /
plan_filename` (`autowork_daemon.py:1096`), and `_autowork_watch_mtime`'s wake-signal glob (`:1435` — this also resolves
the R3 minority finding). Making the brief source CONFIGURABLE is what breaks G1's coupling (brief source == self-pinned
`repo_root`): the external brief root can then be operator-located independently of the self repo.

**D3 — internal/external tracking split (keyed on `_target_is_self(working_dir)`).**
```
briefs/
  internal/    ← git-tracked      (working_dir = self/JanusMask: self-rebuild briefs)
  external/    ← gitignored        (working_dir = some other project)
```
Add `briefs/external/` to `.gitignore` (which already carries `_archive/`, `_abandoned/`, `state/`). `git log
briefs/internal/` becomes JanusMask's self-development audit trail; external work leaves **zero trace in JM's history**
(its trail lands in the external repo, where it belongs). This makes principled the split that is ACCIDENTAL today (3 of
11 `brief_hooks_*.md` happen to be tracked, with no rule).
- **CRITICAL distinction (do not conflate):** GATING (self-protection) follows `_target_is_self(working_dir)` — the
  predicate, ALWAYS. TRACKING (git) follows the DIRECTORY — `.gitignore`. They are enforced by different mechanisms and
  should stay consistent, but if they diverge it is a **HYGIENE/HISTORY problem, NOT a safety hole** — safety never keys
  off the directory. (External brief mis-tracked → pollutes JM history; internal brief mis-ignored → lost self-history;
  neither relaxes self-protection.) A load-time consistency check (brief's dir matches its `working_dir` classification;
  fail-safe to internal) is recommended but NOT security-load-bearing.

**D4 — webUI placement at authoring (`webui/app.py:759` `action_submit_brief`).** The webUI brief-submit route is the
authoring write seam (today it writes `BASE/state/tasks/queued/<name>.md` — a THIRD scattered location; consolidate it
onto D2/D3). Change the single computed `target_path`: parse `working_dir` from the posted brief, classify **server-side**
via `_target_is_self(working_dir)`, route to `briefs/internal/` or `briefs/external/`, fail-safe to `internal`. Why here:
(a) **decide-at-authoring** → the brief lands in the correct dir (hence the correct tracking + gating class) the FIRST
time, no re-filing; (b) **server-side classification preserves the trust boundary** — placement is DERIVED from
`working_dir` by the predicate, never a directory the client picks, so the UI cannot be tricked into filing an
external-targeting brief into the self-gated `internal/` dir; (c) the webUI runs operator-side and is **unreachable by
jailed agents**, so a brief authored through it is trusted. The autocomplete form must carry a `working_dir` field
(default = self for the common self-rebuild case; an LLM-assisted autocomplete may PROPOSE it, but the server predicate
makes the final placement call). Other brief writers re-route identically: `harness/rebuild/job.py:155` and
`harness/planner/blind_draft.py:121`.

**Net data flow:** autocomplete form (`working_dir`, default self) → `action_submit_brief` parses + classifies server-side
→ writes `briefs/internal|external/` → `.gitignore` tracks internal, ignores external → daemon globs the configurable
briefs dir → `working_dir` flows plan→task→binds → `_target_is_self(working_dir)` drives §1b/jail/commit. **One field, set
once at authoring, drives placement, tracking, AND runtime self/external gating.**

**What §3B-D supersedes vs. keeps:**
- **SUPERSEDES:** §3B-A **T1** (env-var selector → the brief `working_dir` field); the **COUPLING INVARIANT** (state_dir
  no longer needs to live in the external repo; commit target comes from the field); §3B-C **G1's "REQUIRED ADD"** (the
  brief IS the origination unit; an external brief is just a brief with an external `working_dir`; the `state_dir/tasks/`
  operator-staging path remains a manual lower-level injection).
- **RE-KEYS (still required):** **T2** (§1b decision now from `task.working_dir` — cleaner, the staging-sibling bug cannot
  arise); **T3** (jail `repo_root`/embedded-runner re-point — bind the target from the field); **T4** (workroot follows the
  field; `JANUSMASK_PROJECT_DIR` STILL stays self); **T5** (daemon self-build no-op when `not _target_is_self(working_dir)`;
  daemon `repo_root=cwd()` stays self for the self-build machinery).
- **ORTHOGONAL (unchanged):** **G2** content-policy stay-self/relax-external decision; **G3** target-`.venv` binding on the
  accept gate **AND (per R7-CONSENSUS) the differential-fuzzer sandbox + the oracle/mutation gate, which also execute
  external code on the JM interpreter — see the expanded G3.** §3B-D solves target SELECTION + G1 + the `full_stop` loss +
  gives the safety boundary a real code home (the field), but does NOT decide which AST rules relax or bind the target
  venv across the (now three) execute-target stages.

**OPEN for next-session adversarial review:** (a) brief frontmatter schema for `working_dir` + planner/`stage_task`
passthrough surface; (b) per-target bootstrap timing (B0–B5 triggered on first sighting of a new `working_dir` in
`_auto_promote`/`_decide` pre-dispatch, vs. the §3B-B daemon-startup hook); (c) confirm the brief glob root is unreachable
by EVERY agent write path (the whole trust model rests on it); (d) the D2/D3 fork — is `briefs/internal/` a FIXED in-repo
tracked path while the external briefs dir is the configurable/out-of-repo one, or one dir with two subdirs; (e) migration
of the 11 existing repo-root `brief_hooks_*.md` + paired `plan_hooks_*.json`.

**[R7-CONSENSUS] REQUIRED BUILD WORK before §3B-D is real (the "flows as DATA" premise is false — see D1):**
1. **Plumb `working_dir` through 5 seams** — (i) stop dropping it in `harness/planner/brief_loader.py:66/160`
   (add to an optional-fields allowlist); (ii) add it to the `PlanningBrief` struct + `blind_draft.py:128` serialization;
   (iii) a planner/`stage_task` STAMP onto each task object, fed from the brief by the daemon at `autowork_daemon.py:1093`
   (or give `stage_task` (`staging.py:16`) a `working_dir` param — it reads only the plan JSON today, no brief access);
   (iv) verify `stage_task`'s verbatim copy then carries it into the staged task JSON and (v) the inbox task the submit
   hook loads (`_decide_common.py:86`) and the worker/binds.
2. **Enforce the TRUST FORK** — the gate-selecting `working_dir` MUST come from the operator BRIEF, stamped by trusted
   code; DISCARD any `working_dir` the jailed planning agents (`blind_draft.py:135`) write into `plan_draft.json`.
3. **D2 path-rebase ≠ propagation** — rebasing the brief glob/`plan_path` onto the new dir (`brief_status.py:23/31`,
   `autowork_daemon.py:1096`, `_autowork_watch_mtime:1435`) only changes WHERE briefs are found; surfacing each brief's
   `working_dir` into the dispatch record (`rec`/`_auto_promote`) is the SEPARATE propagation step above.
4. **webUI seam** — the write is at `webui/app.py:770` (route `:759`), which today reads only `brief_name`/`brief_content`
   and writes `state/tasks/queued/<name>.md`; D4 must additionally PARSE `working_dir`, import the (unbuilt)
   `_target_is_self`, and confirm whether those `state/tasks/queued/*.md` briefs are even ingested by the brief→plan
   pipeline today (if not, D4 also WIRES a currently-separate surface, not merely relocates it).

---

## 4. Invariants carried through EVERY phase (do-NOT) — per-file grep checklist

- Never single-agent acceptance: `grep -c "synthesis_success = True"` **==1** in EACH of
  `harness/orchestrator.py` (`:2320`) and `harness/orchestrator_worker.py` (`:309`). HALT on mismatch.
- Never narrow `BYPASS_FUZZER_TYPES`; `test_authoring` stays `bypass_fuzzer:False`; `grep -c
  "skip_interface_fuzz"` **==1** in EACH of `harness/planner/taxonomies.py`, `harness/orchestrator.py` (`:2331`),
  `harness/orchestrator_worker.py` (`:320`) — and ONLY on `test_authoring`. (Per-file greps; tree-wide 3 is fine.)
- `_SENSITIVE_APPLY_GLOBS == ('harness/**','config/**','scripts/**')` at `git_integration.py:16` — unchanged.
- `verify_extra_ro`/`verify_extra_rw` ABSENT/empty in `harness/config.yaml` (binds at `agent_jail.py:121-133`).
- Keep submit-time AST interceptor ⊆ commit-time enforcer (the PARITY class): the verifier
  (`services/neurosymbolic/ast_verifier.py`) must not ERROR on anything the enforcer (`harness/ast_enforcer.py`)
  ACCEPTS. **PARITY-3 (credential_leak) is the current live violation to fix; do not introduce new ones.**
- **WHOLE-FILE-DRIFT-GUARD** (`commit_accepted_output`, legacy whole-file branch only): keep the
  modified-existing-symbol intersection semantics; do NOT switch to a line-diff/size threshold or to a
  union-count (the union counts additions and breaks `_ast_merge` add/preserve regression tests).
- **R-ANCHORED-PATCH** (`_apply_symbol_patch`): keep the no-extras path byte-identical; extras only for 1-part
  qualnames, bounded to Import/ImportFrom/Func/AsyncFunc/ClassDef, name-collision-rejected.
- agy is NOT tree-isolated → after ANY agy run: verify byte-identical + revert drift (esp. the benign
  `harness/config.yaml` comment-strip: `git checkout HEAD -- harness/config.yaml`). agy did a `git reset`/`git
  checkout` in prior runs — ALWAYS confirm HEAD unchanged after agy.
- Never add `*_fix`/any `<task>_fix` to the allowlist. `full_stop` stays present until owner-gated Phase A. §1b
  (`_apply_approval_granted`) is the autonomous-commit boundary. Agents tree-isolated ONLY via the bwrap jail.
- **External-target safety boundary (§3B):** any self-build-gate bypass for an external target MUST be derived
  from the RESOLVED `worktree_root` vs `PROJECT_ROOT` (never the env var alone) and MUST fail-safe to "self"
  (gates ON) when the resolved target `== PROJECT_ROOT`, `PROJECT_ROOT in root.parents`, **OR `root in
  PROJECT_ROOT.parents`** (the third/ancestor clause — **[R3-CONSENSUS] EXTENDS `paths.py:62`, which has only the
  first two clauses; not a verbatim mirror**). `JANUSMASK_PROJECT_DIR`/`PYTHONPATH` and `${PROJECT_ROOT}` config
  tokens STAY pinned to JM's own repo (harness import + vendored `.agents/` binaries) regardless of any target
  override; only the jail `repo_root`, agent cwd/`agent_workroot()`, `state_dir`, and the §1b relativity follow the
  target. Editing JanusMask's own `harness/`/`config/`/`scripts/` stays §1b-gated regardless of any target
  override. A relative/unset/ambiguous/repo-overlapping target resolves to PROJECT_ROOT = fully gated.

---

## Appendix — anchors (re-verify before use; panel anchors drift)

- `services/neurosymbolic/ast_verifier.py`: `visit_ExceptHandler` (bare-except, landed) `:158-166`;
  `credential_leak` string-literal scan **~:202-208** [PARITY-3].
- `harness/ast_enforcer.py`: `bare_except` (body==Pass) `:100-103`; `security` credential-named-var **~:74-87**.
- `harness/autowork_daemon.py`: `_suspended_pids` global **~:37**; `_reap_running` **:297** (raises `ChildProcessError` for non-children on restart); `_escalate_to_autobrief`
  def **:608** (env built at **:713** [SEC-ENV]), bare Popen (no pidfile) **:742** [SELFHEAL-UNTRACKED-2]; `_write_pidfile` **:819**;
  `_escalate_inactivity` **~:1683** (static task_id `'daemon_inactivity_stuck'`, env built at **:1767** [SEC-ENV], `proc.pid` uniquifier at **:1821**) [SELFHEAL-STEM-COLLISION];
  `_iteration` watchdog SIGKILL **:1388**; sequential launch/suspend **~:1354-1409**; parallel `_spawn_worker`
  (no watchdog) **~:1410-1417**, `_spawn_worker` **def :827** (no `start_new_session=True`) [PARALLEL-WORKER-WATCHDOG/PGID];
  sequential launch `start_new_session` **:1363**; `_kill_process_group` **:1879-1889**; `_reap_running`
  **:296** (no WUNTRACED; raises ChildProcessError on restart); `daemon repo_root = Path.cwd()` **~:1574** (launcher `run-autowork.sh:33` pins CWD to the JM repo — see §3B T5 / RISK 6); `full_stop` checks **:1238 / :1517**; self-build/promotion consumers of `repo_root`: `_auto_promote` **:1041** (briefs/plans from `repo_root`), `_maybe_push_and_rebase_pin` **:1447** (`git push origin main` **:1476/:1487** + `scripts/impl_rebase_drift_pin.py` **:1482**) — `_watch_rebuild_jobs` **:882** does NOT consume `repo_root` (param unused, `state_dir`-driven).
- `harness/orchestrator.py`: `_build_agent_env` **:220** (env `{**os.environ}` **:260**) [SEC-ENV]; jail bind
  `repo_root=PROJECT_DIR` **:347** [external-target re-point T3]; staging path `<name>_<task_id>_staging` **~:1710**,
  `.venv` symlink into staging **~:1721-1728**, `os.execv` blue/green re-exec **~:1411-1452**;
  `_auto_commit_accepted` **~:1473-2085 (~613 lines, round-2)** [ROLLB-D]; `run_pipeline` **~:2149-2479 (~331 lines)**,
  13× `_mark_processed` [ROLLB-E]; `synthesis_success = True` **:2320**; `_skip_ifz` **:2331**.
- `harness/git_integration.py`: `_SENSITIVE_APPLY_GLOBS` **:16**; `_enforce_apply_scope` glob-match-vs-worktree_root
  **:43**; `_ast_merge` **:81**; `commit_accepted_output` **:569** (legacy whole-file merge `:684`,
  WHOLE-FILE-DRIFT-GUARD just after); `_apply_symbol_patch` **:964** (R-ANCHORED extras logic);
  `create/remove/merge_staging_to_parent` **~:1245-1423** (`remove_staging_worktree` **:1294**
  [STAGING-RM-NOTIMEOUT]; merge fail-closed on dirty parent).
- `harness/agent_jail.py`: XDG tmpfs + `bus`/`keyring` `--bind` **~:239-245** [SEC-1, KEYRING-UNFILTERED];
  `build_jail_argv` **:65** (SEC-1 target); `extra_ro/rw` binds **:121-133**.
- `harness/paths.py`: `PROJECT_ROOT = HARNESS_DIR.parent` **:17** (no `PROJECT_DIR` symbol here — that is an
  `orchestrator.py:42` alias); GAP_H3 inside-repo fail-safe **:62** (2-clause `resolved == PROJECT_ROOT or
  PROJECT_ROOT in resolved.parents`, `raise`s — `_target_is_self` EXTENDS it with a 3rd ancestor clause);
  `agent_workroot()` def **:27** (NOT `~:51`) [external-target T1/T4]; `__all__` `ast.Assign` **:78** (NOT
  R-ANCHORED-extra-eligible — Assign is a disallowed extra kind).
- jail `repo_root` self-pin sites [T3]: `orchestrator.py:347` (`PROJECT_DIR`), **`autowork_daemon.py:604`
  (`PROJECT_ROOT_STR`)**, `embedded_test_runner.py:161/206` (`PROJECT_ROOT`); already-dynamic: `orchestrator.py:1834/1959/1983/1997` (`worktree_root`).
- `JANUSMASK_PROJECT_DIR` (STAYS-SELF) set at `orchestrator.py:260`, `autowork_daemon.py:584`; consumed by
  `hooks_equivalence.py:74`, `interceptors.py:96`, `hooks/_paths.py:23`, `gemini/session_start.py:79`; asserted
  `== PROJECT_ROOT` by `test_agent_env_no_repo_leak.py:44`, `test_replication_clean_room_static.py:309`,
  `test_daemon_control_isolation_hooks.py:405`.
- config-path (external CWD breakage) [T1]: relative `orchestrator_worker.py:28` + daemon `--config` default
  `autowork_daemon.py:1571` (inline `:635`/`:1720` w/ `state_dir.parent` fallback); `orchestrator.py:47` already absolute.
- `_enforce_apply_scope` **:43** (no `worktree_root` param; `sensitive_globs=` kwarg); 3 callers `:665`/`:853`/`:1183` [T2].
- `state/control/autowork/full_stop`: **PRESENT** (`halted`).
