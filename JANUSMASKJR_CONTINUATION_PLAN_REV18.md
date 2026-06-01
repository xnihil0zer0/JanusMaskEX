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
> round-2 reports (ground-truth, anchored). Round-2 corrections are folded in below (ROLLB-D is **~675 lines**,
> `STAGING-RM` is `:1294`, new gap PARALLEL-WORKER-PGID; R1 regression suite **251 passed/0 fail**).
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
| **DAEMON-STARTUP-ORPHAN + PARALLEL-WORKER-WATCHDOG + PARALLEL-WORKER-PGID** (R1, R3, R2-rev18b) | MED | **PIPELINE** | **[verified-real]** Residuals of the minimal SUSPEND-LEAK fix: (a) the parallel `_spawn_worker` branch (`autowork_daemon.py` ~:1410-1417) has **no watchdog** — a suspended/hung parallel worker leaks its slot unbounded; (b) `_suspended_pids` is an in-memory global (~:37) — a daemon crash/restart between SIGSTOP/SIGCONT orphans the T-state pid (on restart `_reap_running` `:296` `waitpid(WNOHANG)` — **without `WUNTRACED`** — returns `(0,0)` for a stopped child → treated as live → pidfile never cleared); (c) **PARALLEL-WORKER-PGID [new, R2-rev18b]:** `_spawn_worker` (~:835) lacks `start_new_session=True` (the sequential launch `:1363` HAS it), so `_kill_process_group` (`:1879-1889`) cannot safely group-kill a parallel worker. **Gates (ii) unattended, NOT (i) supervised.** Fix: on daemon start, scan `running/*.pid` for T-state pids and `SIGCONT`+reap (or SIGKILL over-aged); add a suspended-age sweep + `start_new_session=True` to the parallel branch; consider `WUNTRACED` in the reap probe. §1b. Pipeline-viable; a startup-scan helper can be added via R-ANCHORED-PATCH extras. |
| **SELFHEAL-UNTRACKED-2** (`_escalate_to_autobrief`) (R3) | LOW-MED | **PIPELINE** | **[verified-real]** `autowork_daemon.py:_escalate_to_autobrief` (def `:608`) does a bare `subprocess.Popen` at `:742` with **no `_write_pidfile`** — the SAME class as the landed `_escalate_inactivity` fix but a DIFFERENT function (the `:571` docstring even admits these paths "called subprocess.Popen directly, bypassing…"). My REV17 fix only covered `_escalate_inactivity`. Fix: capture the handle + `_write_pidfile` with a distinct stem, exactly like `a4fbbab`. §1b. Easy single-symbol win. **Also fold in SELFHEAL-STEM-COLLISION** [verified]: `_escalate_inactivity`'s `task_id` resolves to the static `'daemon_inactivity_stuck'`, so the `selfheal_{agent}_daemon_inactivity_stuck.pid` stem is overwritten across repeated inactivity escalations → older self-heal orphaned. Add a uniquifier (pid/counter/timestamp passed via args — `Date.now()`-equivalent must come from the daemon clock, not a literal). |
| **PARITY-3 (credential_leak)** (R4) | MED | **PIPELINE** | **[verified-real], same class as PARITY-1/2.** Submit-time `services/neurosymbolic/ast_verifier.py:~202-208` flags ANY string literal matching `CREDENTIAL_PATTERNS` as `credential_leak` severity **ERROR**; commit-time `harness/ast_enforcer.py:~74-87` only flags `security` ERROR on an *assignment whose target variable name* matches `(?i)(password|secret|key)`. So a credential-pattern string NOT bound to a credential-named var → DENIED at submit, ALLOWED at commit → interceptor ⊄ enforcer (blocks valid submissions; can stall pipeline runs containing test fixtures/example keys). Fix: downgrade the verifier's string-literal `credential_leak` to WARNING (or align to the enforcer's variable-name test). services/+tests/, no §1b. Easy win (mirror PARITY-2). |
| **STAGING-RM-NOTIMEOUT** (R2) | LOW-MED | **PIPELINE** | **[verified] anchor corrected to `git_integration.remove_staging_worktree` `:1294`** (NOT the agy-cited `~:1420`). No retry/timeout, so a jailed subprocess holding a handle → `git worktree remove`/`rmtree` `EBUSY`/hang locks future runs. Reliability gap; pairs with ROLLB-D. Add a bounded retry + sub-timeout. §1b. |
| **SEC-ENV (host-env leak)** (R2) | MED | **PIPELINE, agy-auth-risky** | **[verified]** `orchestrator.py:_build_agent_env` (`:220`, env built at `:260`) uses `{**os.environ, …}` → copies the FULL operator environment (incl. any `GITHUB_TOKEN`/cloud creds) into the jailed agent process env. Real exposure. **But the agents need auth/HOME/PATH** → naive whitelisting can break claude/agy auth. Fix: allowlist required keys (PATH, HOME, LANG, TERM, the agent's own auth vars) + explicit JANUSMASK_*; **MUST re-run the agy/claude auth smoke after and REVERT if auth breaks.** Treat like SEC-1 (careful, smoke-gated). §1b. |
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
   `_escalate_inactivity` stem with the spawn pid). §1b. Single-symbol; mirror `a4fbbab`. Oracle: both self-heal
   spawns write a tracked, collision-free pidfile.
3. **DAEMON-STARTUP-ORPHAN + PARALLEL-WORKER-WATCHDOG + PARALLEL-WORKER-PGID** — on daemon start, sweep
   `running/*.pid` and `SIGCONT`+reap/SIGKILL any orphaned T-state pid; add a suspended-age sweep to the parallel
   `_spawn_worker` branch (~:1410-1417) **and `start_new_session=True` to `_spawn_worker` (~:835)** so
   `_kill_process_group` (`:1879-1889`) can group-kill it (sequential `:1363` already has it); consider
   `os.WUNTRACED` in the `_reap_running` (`:296`) probe so stopped children aren't read as live. §1b. May need a
   small startup-scan helper → add it as an R-ANCHORED-PATCH **extra** (top-level qualname) in the same patch as
   the launch-block edit. Oracle: a seeded orphaned T-state pidfile is resumed/reaped on the next iteration; a
   suspended parallel worker past threshold is killed; a parallel worker is spawned in its own session.
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
6. **ROLLB-D / ROLLB-E** — try/finally over `_auto_commit_accepted` (`orchestrator.py` ~`:1473-2148`, **~675
   lines** — round-2 R2 re-measured; bigger than the ~614 first cited, which *strengthens* hand-edit-first) and
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
  repo" in a SMALL ENUMERABLE set: the jail repo ro-bind (`orchestrator.py:347` passes `repo_root=PROJECT_DIR`),
  `agent_workroot()` (`paths.py:~51`), `PYTHONPATH`/`JANUSMASK_PROJECT_DIR`, config-token interpolation, and —
  **critically — the §1b sensitive-glob gate.** `_SENSITIVE_APPLY_GLOBS` (`git_integration.py:16`) are matched
  **relative to `worktree_root`** (`_enforce_apply_scope:43` — verified), so an external project that happens to
  contain a `harness/`/`config/`/`scripts/` dir would be WRONGLY blocked. That gate is the one self-guard that
  needs an explicit, **fail-safe** bypass.

**SAFETY BOUNDARY (the hinge — do not get this wrong).** The self-build gates must bypass for external targets
but stay ON for self-edits. Derive the decision from the **RESOLVED `worktree_root` vs `PROJECT_ROOT`, NOT from
the env var alone.** Add `effective_target_root()` + a fail-safe predicate `_target_is_self(root)` in `paths.py`
that returns **True (gates ON) whenever the resolved target `== PROJECT_ROOT` or `PROJECT_ROOT in
root.parents`** — mirroring the existing GAP_H3 guard at `paths.py:62`. A mis-set / relative / repo-inside target
**fail-safes to "self" (fully gated)**. Only an unambiguously-external resolved root flips gates OFF. `full_stop`
stays keyed to `state_dir` (operator control — keep it; it is not a self-build artifact).

**Phase 3B-A — scoping override (R3; PIPELINE-FIRST, §1b, serialize):**
- **T1** — add `effective_target_root()` + `_target_is_self()` to `paths.py` (resolver reads
  `JANUSMASK_TARGET_PROJECT` env / config key; fail-safe to PROJECT_ROOT). New top-level symbols in a sensitive
  file → add via **R-ANCHORED-PATCH extras** on an existing 1-part symbol, or a new-file/manifest route. Oracle:
  external dir → resolves to it; unset/relative/inside-repo → resolves to PROJECT_ROOT (gates ON).
- **T2** — gate the §1b sensitive-glob check on `_target_is_self(worktree_root)`: when the resolved target is
  external, `_enforce_apply_scope` does NOT treat `harness/**` etc. as sensitive (those globs are JM's own).
  Oracle: an external `harness/x.py` edit is allowed; a self `harness/x.py` edit still requires §1b.
- **T3** — re-point the jail bind: `build_jail_argv(..., repo_root=effective_target_root())` at
  `orchestrator.py:347` (ro-bind the TARGET, not PROJECT_DIR). Oracle: jail argv binds the external root when set.
- **T4** — re-point `agent_workroot()`/work_dir + `JANUSMASK_PROJECT_DIR` to the resolved target (keep the
  outside-repo isolation invariant relative to the TARGET). Oracle: agent cwd is outside the target repo.
  *(Each Tn is a single-symbol partial edit where possible; the `__all__` export append in `paths.py` may need a
  region/manifest route rather than a symbol patch — R3 flagged.)*

**Phase 3B-B — target bootstrap (R4; PIPELINE-FIRST then one gate-bearing hand-edit):**
- New module `harness/target_bootstrap.py` (NEW FILE → new-file commit route, not symbol-patch), decomposed into
  idempotent single-symbol functions, each with a non-vacuous oracle:
  **B0** `git init` if no repo; **B1** make an initial commit if the repo has no HEAD (worktrees REQUIRE a HEAD);
  **B2** `python -m venv .venv` **using `sys.executable`** if absent (so the jail `extra_ro=[base_prefix,
  prefix]` binds resolve) + ensure `pytest`; **B3** create the staging worktree via the existing
  `create_staging_worktree` and smoke `merge_staging_to_parent` preconditions; **B4** write/ensure a
  `.gitignore` (`state/`, `.venv/`, `*_staging/`) so the dirty-parent fail-closed merge doesn't stash-churn;
  **B5** a top-level idempotent `bootstrap_target(root)` orchestrating B0–B4 (no-op when all present).
- **Hook (HAND-EDIT, gate-bearing):** a one-time `bootstrap_target(effective_target_root())` call at daemon
  startup in `run_daemon` + an optional `--bootstrap-target <dir>` CLI flag. (Gate-bearing daemon entrypoint →
  expect §1b + a hand-edit after a pipeline attempt.)

**RISKS (carry into execution):** (1) external venv jail binds — create the venv with `sys.executable` so
`base_prefix`/`prefix` match the binds; (2) the `os.execv` blue/green re-exec keeps the HARNESS interpreter —
fine, but the re-exec'd worker must still resolve the external `state_dir`/target; (3) `merge_staging_to_parent`
fail-closes on a dirty parent (stash + drop-on-conflict) → could discard an operator's UNCOMMITTED external work
— bootstrap must `.gitignore` JM artifacts and warn on a dirty target; (4) sibling-dir writability for the
`<name>_<task_id>_staging` worktree; (5) the §1b bypass MUST fail-safe to "self" on any ambiguity. **All of 3B is
(ii)-class autonomy work and orthogonal to Phase A — it does not lift `full_stop`.**

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
  (gates ON) when the resolved target `== PROJECT_ROOT` or `PROJECT_ROOT in root.parents` (mirror
  `paths.py:62`). Editing JanusMask's own `harness/`/`config/`/`scripts/` stays §1b-gated regardless of any
  target override. A relative/unset/ambiguous target resolves to PROJECT_ROOT = fully gated.

---

## Appendix — anchors (re-verify before use; panel anchors drift)

- `services/neurosymbolic/ast_verifier.py`: `visit_ExceptHandler` (bare-except, landed) `:158-166`;
  `credential_leak` string-literal scan **~:202-208** [PARITY-3].
- `harness/ast_enforcer.py`: `bare_except` (body==Pass) `:100-103`; `security` credential-named-var **~:74-87**.
- `harness/autowork_daemon.py`: `_suspended_pids` global **~:37**; `_reap_running` **:297**; `_escalate_to_autobrief`
  def **:608**, bare Popen (no pidfile) **:742** [SELFHEAL-UNTRACKED-2]; `_write_pidfile` **:819**;
  `_escalate_inactivity` **~:1683** (static task_id `'daemon_inactivity_stuck'`) [SELFHEAL-STEM-COLLISION];
  `_iteration` watchdog SIGKILL **:1388**; sequential launch/suspend **~:1354-1409**; parallel `_spawn_worker`
  (no watchdog) **~:1410-1417**, `_spawn_worker` **~:835** (no `start_new_session=True`) [PARALLEL-WORKER-WATCHDOG/PGID];
  sequential launch `start_new_session` **:1363**; `_kill_process_group` **:1879-1889**; `_reap_running`
  **:296** (WNOHANG, no WUNTRACED); `daemon repo_root = Path.cwd()` **~:1574**; `full_stop` checks **:1238 / :1517**.
- `harness/orchestrator.py`: `_build_agent_env` **:220** (env `{**os.environ}` **:260**) [SEC-ENV]; jail bind
  `repo_root=PROJECT_DIR` **:347** [external-target re-point T3]; staging path `<name>_<task_id>_staging` **~:1710**,
  `.venv` symlink into staging **~:1721-1728**, `os.execv` blue/green re-exec **~:1411-1452**;
  `_auto_commit_accepted` **~:1473-2148 (~675 lines, round-2)** [ROLLB-D]; `run_pipeline` **~:2149-2479 (~331 lines)**,
  13× `_mark_processed` [ROLLB-E]; `synthesis_success = True` **:2320**; `_skip_ifz` **:2331**.
- `harness/git_integration.py`: `_SENSITIVE_APPLY_GLOBS` **:16**; `_enforce_apply_scope` glob-match-vs-worktree_root
  **:43**; `_ast_merge` **:81**; `commit_accepted_output` **:569** (legacy whole-file merge `:684`,
  WHOLE-FILE-DRIFT-GUARD just after); `_apply_symbol_patch` **:964** (R-ANCHORED extras logic);
  `create/remove/merge_staging_to_parent` **~:1245-1423** (`remove_staging_worktree` **:1294**
  [STAGING-RM-NOTIMEOUT]; merge fail-closed on dirty parent).
- `harness/agent_jail.py`: XDG tmpfs + `bus`/`keyring` `--bind` **~:239-245** [SEC-1, KEYRING-UNFILTERED];
  `build_jail_argv` **:65** (SEC-1 target); `extra_ro/rw` binds **:121-133**.
- `harness/paths.py`: `PROJECT_ROOT = HARNESS_DIR.parent` **:17**; GAP_H3 inside-repo fail-safe **:62**
  (pattern for `_target_is_self`); `agent_workroot()` **~:51** [external-target T1/T4].
- `state/control/autowork/full_stop`: **PRESENT** (`halted`).
