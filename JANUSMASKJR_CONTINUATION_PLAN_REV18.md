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
> **Read this first (state):** HEAD `e2554a2` (= `origin/master`). The 5 REV17 landings + the regression fix are
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
| **DAEMON-STARTUP-ORPHAN + PARALLEL-WORKER-WATCHDOG** (R1, R3) | MED | **PIPELINE** | **[verified-real]** Two residuals of the minimal SUSPEND-LEAK fix: (a) the parallel `_spawn_worker` branch (`autowork_daemon.py` ~:1411) has **no watchdog** — a suspended/hung parallel worker leaks its slot unbounded; (b) `_suspended_pids` is an in-memory global (~:37) — a daemon crash/restart between SIGSTOP/SIGCONT orphans the T-state pid (on restart `_reap_running`'s `waitpid(WNOHANG)` returns `(0,0)` for a stopped child → treated as live → pidfile never cleared). **Gates (ii) unattended, NOT (i) supervised.** Fix: on daemon start, scan `running/*.pid` for T-state pids and `SIGCONT`+reap (or SIGKILL over-aged); add a per-worker watchdog (or a global suspended-age sweep) to the parallel branch. §1b. Pipeline-viable; a startup-scan helper can be added via R-ANCHORED-PATCH extras. |
| **SELFHEAL-UNTRACKED-2** (`_escalate_to_autobrief`) (R3) | LOW-MED | **PIPELINE** | **[verified-real]** `autowork_daemon.py:_escalate_to_autobrief` (def `:608`) does a bare `subprocess.Popen` at `:742` with **no `_write_pidfile`** — the SAME class as the landed `_escalate_inactivity` fix but a DIFFERENT function (the `:571` docstring even admits these paths "called subprocess.Popen directly, bypassing…"). My REV17 fix only covered `_escalate_inactivity`. Fix: capture the handle + `_write_pidfile` with a distinct stem, exactly like `a4fbbab`. §1b. Easy single-symbol win. **Also fold in SELFHEAL-STEM-COLLISION** [verified]: `_escalate_inactivity`'s `task_id` resolves to the static `'daemon_inactivity_stuck'`, so the `selfheal_{agent}_daemon_inactivity_stuck.pid` stem is overwritten across repeated inactivity escalations → older self-heal orphaned. Add a uniquifier (pid/counter/timestamp passed via args — `Date.now()`-equivalent must come from the daemon clock, not a literal). |
| **PARITY-3 (credential_leak)** (R4) | MED | **PIPELINE** | **[verified-real], same class as PARITY-1/2.** Submit-time `services/neurosymbolic/ast_verifier.py:~202-208` flags ANY string literal matching `CREDENTIAL_PATTERNS` as `credential_leak` severity **ERROR**; commit-time `harness/ast_enforcer.py:~74-87` only flags `security` ERROR on an *assignment whose target variable name* matches `(?i)(password|secret|key)`. So a credential-pattern string NOT bound to a credential-named var → DENIED at submit, ALLOWED at commit → interceptor ⊄ enforcer (blocks valid submissions; can stall pipeline runs containing test fixtures/example keys). Fix: downgrade the verifier's string-literal `credential_leak` to WARNING (or align to the enforcer's variable-name test). services/+tests/, no §1b. Easy win (mirror PARITY-2). |
| **STAGING-RM-NOTIMEOUT** (R2) | LOW-MED | **PIPELINE** | **【agy-claimed; verify-first】** `git_integration.remove_staging_worktree` (anchor agy-cited `~:1420` — VERIFY) reportedly has no retry/timeout, so a jailed subprocess holding a handle → `git worktree remove`/`rmtree` `EBUSY`/hang locks future runs. Plausible reliability gap; pairs with ROLLB-D. Verify the function lacks a timeout, then add a bounded retry + sub-timeout. §1b. |
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
3. **DAEMON-STARTUP-ORPHAN + PARALLEL-WORKER-WATCHDOG** — on daemon start, sweep `running/*.pid` and
   `SIGCONT`+reap/SIGKILL any orphaned T-state pid; add a suspended-age sweep to the parallel `_spawn_worker`
   branch (~:1411). §1b. May need a small startup-scan helper → add it as an R-ANCHORED-PATCH **extra**
   (top-level qualname) in the same patch as the launch-block edit. Oracle: a seeded orphaned T-state pidfile is
   resumed/reaped on the next iteration; a suspended parallel worker past threshold is killed.
4. **STAGING-RM-NOTIMEOUT** — verify `remove_staging_worktree` lacks a timeout (agy-claimed `~:1420`), then add a
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
6. **ROLLB-D / ROLLB-E** — try/finally over `_auto_commit_accepted` (`orchestrator.py` ~`:1473-2086`, **~614
   lines**) and crash-safety over `run_pipeline`'s 13 `_mark_processed` sites (~`:2149-2479`, **~331 lines**).
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

---

## Appendix — anchors (re-verify before use; panel anchors drift)

- `services/neurosymbolic/ast_verifier.py`: `visit_ExceptHandler` (bare-except, landed) `:158-166`;
  `credential_leak` string-literal scan **~:202-208** [PARITY-3].
- `harness/ast_enforcer.py`: `bare_except` (body==Pass) `:100-103`; `security` credential-named-var **~:74-87**.
- `harness/autowork_daemon.py`: `_suspended_pids` global **~:37**; `_reap_running` **:297**; `_escalate_to_autobrief`
  def **:608**, bare Popen (no pidfile) **:742** [SELFHEAL-UNTRACKED-2]; `_write_pidfile` **:819**;
  `_escalate_inactivity` **~:1683** (static task_id `'daemon_inactivity_stuck'`) [SELFHEAL-STEM-COLLISION];
  `_iteration` watchdog SIGKILL **:1388**; sequential launch/suspend **~:1354-1409**; parallel `_spawn_worker`
  (no watchdog) **~:1411** [PARALLEL-WORKER-WATCHDOG]; `full_stop` checks **:1238 / :1517**.
- `harness/orchestrator.py`: `_build_agent_env` **:220** (env `{**os.environ}` **:260**) [SEC-ENV];
  `_auto_commit_accepted` **~:1473-2086 (~614 lines)** [ROLLB-D]; `run_pipeline` **~:2149-2479 (~331 lines)**,
  13× `_mark_processed` [ROLLB-E]; `synthesis_success = True` **:2320**; `_skip_ifz` **:2331**.
- `harness/git_integration.py`: `_SENSITIVE_APPLY_GLOBS` **:16**; `_ast_merge` **:81**; `commit_accepted_output`
  **:569** (legacy whole-file merge `:684`, WHOLE-FILE-DRIFT-GUARD just after); `_apply_symbol_patch` **:964**
  (R-ANCHORED extras logic); `remove_staging_worktree` **agy-cited ~:1420 (VERIFY)** [STAGING-RM-NOTIMEOUT].
- `harness/agent_jail.py`: XDG tmpfs + `bus`/`keyring` `--bind` **~:239-245** [SEC-1, KEYRING-UNFILTERED];
  `build_jail_argv` **:65** (SEC-1 target); `extra_ro/rw` binds **:121-133**.
- `state/control/autowork/full_stop`: **PRESENT** (`halted`).
