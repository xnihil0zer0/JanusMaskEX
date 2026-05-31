# JanusMaskJR — Continuation Plan (2026-05-31, rev 12)

> **rev 12 — written after a 9-agent independent and adversarial review of rev 11 findings and consensus.**
> Supersedes `JANUSMASKJR_CONTINUATION_PLAN_REV11.md`. Governing rule (owner directive):
> **use the PIPELINE for every change wherever possible; HAND-EDIT only after a pipeline attempt fails
> with a PERMANENT blocker (never a timeout).**
>
> **Read this first (one-paragraph state):** **HEAD `be4b100`, pushed to `origin/master`.** This session
> landed, in order: **H1** (mutation-gate `try/except` + copytree hardening, pipeline `3266b2f`), **A.3**
> (interface-fuzz + smoke/embedded decouple for `test_authoring`, oracle `0183b24` + hand-edit `d2f8710`
> after a *real* demonstrated permanent blocker), **AGY-FIX** (route agy-backed agents via stdin/stdout in
> `spawn_agent`, pipeline `2fb7535`), and a **synthesis-window widen** 1200→1800s (`be4b100`). A 4-agent
> ground-truth re-audit at `be4b100` confirms **all four landings SOUND** (four-gate invariant `== 1` per
> file, `skip_interface_fuzz` pinned to `test_authoring`, 16 + 82 targeted tests green, claude path
> byte-identical, jail intact). **The A-TEST (`PHASE_A_JAIL_WRITEDENIAL_REGRESSION`) is NOT landed**, blocked
> on a newly-found bug: the submission-time **`ASTVerificationInterceptor` is stricter than the real
> acceptance gate** (`subprocess_no_check` = ERROR in `services/neurosymbolic/ast_verifier.py:127` but only
> WARNING in `harness/ast_enforcer.py:125`), and the A-TEST legitimately needs `subprocess.run(...)` without
> `check=True` to assert `returncode != 0` (write-denial) → both agents' valid grounded submissions are denied
> → recorded as `both_agents_timed_out`. **Next step = the interceptor consistency fix (pipeline, `services/**`
> ⇒ no §1b), then re-run the A-TEST** with a non-vacuity safeguard. Daemon DOWN, `full_stop` PRESENT
> (`halted`), allowlist deny-all, tree clean.
>
> **Cross-model caveat (process):** the owner asked for 4 *agy* (Antigravity Gemini) adversarial reviewers.
> **agy was non-functional during this session's review pass** — even a 3-word `agy -p` smoke prompt timed out
> (rc 143), with a persistent `not logged into Antigravity` OAuth warning; agy's auth/session degrades under
> heavy load. The adversarial re-verification below was therefore produced by 4 read-only agents that
> **independently ground-truthed the live code at `be4b100`** (not by agy). To get a true cross-vendor pass,
> re-authenticate agy (`agy` interactively / login) and re-run the 4 self-contained critique packets parked at
> `review_packet_{1..4}.txt` (they embed all evidence, so agy needs no repo access — pure generation, the only
> agy mode that works reliably).

---

## 0. Starting state — VERIFIED this session + re-audited (do not re-do)

**Branch `master`, HEAD `be4b100`, synced to `origin/master`.** Session history since the rev-10 baseline `5203700`:

| Commit | Item | Route | Audit verdict (rev-11/12 re-audit) |
|--------|------|-------|--------------------|
| `1135c63` | **H1 oracle** — `mutation_gate_error` crash/malformed-target cases | hand-edit (tests, committed first) | **SOUND** — 2 RED-on-HEAD cases, genuine fail→pass |
| `3266b2f` | **H1** — mutation-gate `try/except`→`mutation_gate_error` rollback; copytree ignores `state/`,`samples/`,`.pytest_cache`,`*.egg-info`; validate `mutation_target` | **PIPELINE** (1st-try) | **SOUND** — single-symbol `_auto_commit_accepted`, four gates untouched, oracle 7/7 green, contained |
| `0183b24` | **A.3 oracle** — orch + WORKER path detectors | hand-edit (tests, first) | **SOUND** — RED on HEAD, worker-path covered |
| `d2f8710` | **A.3** — `_skip_ifz` decouple of fuzz + smoke/embedded for `test_authoring`, BOTH files | **HAND-EDIT** (after `PHASE_A3_PIPELINE_DEMO` rejected ×2 `synthesis_or_ast_failed` — the patch path cannot add a module-level import; clean PERMANENT structural blocker, harness byte-unchanged) | **SOUND** — `_skip_ifz` LITERALLY pinned to `mtt == 'test_authoring'` (orch `:2137`, worker `:320`); both guards patched; `grep -c skip_interface_fuzz taxonomies.py == 1`; oracle 4/4 green |
| `2fb7535` | **AGY-FIX** — route agy-backed agents (command basename `agy`: gemini/claude_fallback/antigravity) via STDIN + "write-nothing/fenced-python" tail; capture STDOUT; `_extract_python_block`; write standard outbox submission | **PIPELINE** | **SOUND but with 2 latent follow-ups (see H-AGY-2)** — claude path byte-identical, jail kept, four gates untouched, 82 tests green; gemini now authors real grounded code (~2 min) |
| `be4b100` | **synthesis window 1200→1800** | hand-edit (config value; `config.yaml` not a Python symbol ⇒ un-pipelineable) | **SOUND** — `HARD = 2*window+slack` formula intact (now `HARD≈3900`) |

**Four-gate invariant re-confirmed at `be4b100`:** `grep -c "synthesis_success = True"` == 1 in BOTH
`harness/orchestrator.py` and `harness/orchestrator_worker.py`; orch run_pipeline bool gate at `:2050`
(`synthesis_success = bool(claude_ok and gemini_ok and claude_code and gemini_code)`); worker gates
`:237/:265/:296/:309`. **Not weakened by H1, A.3, or AGY-FIX.**

**Environment (verified):** daemon **DOWN**; `full_stop` PRESENT (`halted`); `auto_promote.allowlist` deny-all;
`bwrap` present + `agent_sandbox.bwrap == true`; `BYPASS_FUZZER_TYPES` intact (`test_authoring` absent,
`bypass_fuzzer:False`+`skip_interface_fuzz:True`); tree clean; memory ro-bound (agents cannot poison it).

---

## 0.1 — Systemic findings from 9-agent adversarial review

1. **(F1) agy-backed agents MUST route their submission via STDIN, not an agentic file-write cascade.**
   Cause: `agy -p` runs an Antigravity "cascade" that tries to *edit the target file in the repo*; the bwrap
   jail (correctly) denies the write → agy emits `# Placeholder` and times out. AGY-FIX (`2fb7535`) routes the
   prompt over stdin with a no-write tail and captures stdout. **Invariant added (§2).** Corollary: **agy is
   unreliable for agentic / long / exploratory tasks and its auth degrades under load** — use agy ONLY for
   self-contained, pure-generation prompts; never depend on agy for agentic exploration.

2. **(F2) The submission-time interceptor must stay NO STRICTER than the real acceptance gate.**
   `ASTVerificationInterceptor.pre_tool_use` (`harness/interceptors.py:40-59`) runs
   `services/neurosymbolic/ast_verifier.py:ASTVerifier().verify()` on EVERY `submit_code` and DENIES on any
   ERROR. Mismatches exist between verifier and enforcer (e.g. `subprocess_no_check` error vs warning, bare `except:` checking, credential scanning on innocent variables). **This is the live A-TEST blocker. Invariant added (§2).**

3. **(F3) Watchdog budget formula mismatch under widened synthesis window.**
   The sequential daemon watchdog timeout `max(1800.0, float(timeout_val) + 300.0)` in `harness/autowork_daemon.py:1373` resolves to `2100` seconds. However, the worker has a hard budget of `2 * timeout_seconds + 300 = 3900` seconds to allow retries. Under sequential execution, the daemon watchdog will kill the worker at 2100s, preventing it from utilizing its allocated second attempt. A similar budget issue exists in `harness/ast_retry.py`.

4. **(F4) Staging Worktree Concurrency race.**
   `staging_path` in `harness/orchestrator.py` is hardcoded globally to `{name}_staging`. Concurrent worker processes will overwrite and delete (`shutil.rmtree`) each other's staging directories, leading to spurious verification failures.

5. **(F5) Destructive Rollback Loophole on `sha=None`.**
   In `_rollback_rejected_commit`, calling the function with `sha=None` (meaning staging commit failed or never happened) falls through to `git reset --hard HEAD~1` on the parent repository, deleting the parent's actual latest commit.

6. **(F6) Foreground Pipeline Task Handling.**
   In `run_pipeline`, failed tasks are unconditionally marked as processed (moved to `processed/` folder) instead of blocked, rendering them "zombies" that cannot be retried. `no_diff` markers are also ignored.

7. **(F7) Multi-file Rollback & Staging Cleanup.**
   `_rollback_rejected_commit` only cleans up `files_touched[0]`, leaving other touched files dirty. In addition, the staging worktree lifecycle is not wrapped in `try...finally` blocks, leaking staging paths on unexpected exceptions.

---

## 1. Phase map & ordering (rev 12) — PIPELINE-FIRST

| Phase | Contents | Route | Status |
|-------|----------|-------|--------|
| 0/0.5/B/A.1/A.2/H1/A.3/AGY-FIX/window | prior + this session | pipeline / hand-edit | **DONE + re-audited SOUND** |
| **H-INT — interceptor consistency fix** | make `ASTVerificationInterceptor` no stricter than the real gate: downgrade `subprocess_no_check` ERROR→WARNING in `services/neurosymbolic/ast_verifier.py` (minimal services-only fix avoiding §1b, or a cleaner interceptor delegation to `validate_code` requiring §1b approval). | **PIPELINE** (`services/**` ⇒ NO §1b; single-function partial_edit). Oracle first. | **TODO — NEXT (unblocks A-TEST)** |
| **H-AGY-2 — AGY-FIX follow-ups** | (a) fix the spawn_agent **double-timeout budget**: make the agy branch pass a short/zero poll budget or account for it. (b) tighten the `_extract_python_block` raw-text fallback. (c) add a jail-ENABLED spawn_agent test. (d) Update the sequential autowork daemon watchdog timeout formula to `max(1800.0, 2.0 * float(timeout_val) + 600.0)` to match worker retries. | **PIPELINE** (partial_edit `spawn_agent` + a tests oracle); `harness/**` ⇒ **§1b** | **TODO — before relying on agy for any timing-sensitive run** |
| **H-ROLLBACK — rollback and staging hardening** | (a) Make `staging_path` task-specific (`{name}_staging_{task_id}`) to prevent collisions. (b) Secure `_rollback_rejected_commit` to check `if not sha:` and abort instead of a destructive `reset HEAD~1`. (c) Clean up all files in `files_touched` during rollback. (d) Wrap staging worktree creation/deletion in try-finally blocks. (e) Fix foreground pipeline status transitions and `no_diff` handling. | **PIPELINE** (harness/orchestrator.py); ⇒ **§1b** | **TODO — with H-AGY-2** |
| **A-TEST — author the Phase-A jail write-denial regression** | re-run `PHASE_A_JAIL_WRITEDENIAL_REGRESSION` (hardened spec already on disk). **Add a non-vacuity safeguard (see R-vacuity below).** | **PIPELINE** (`test_authoring`, NO §1b) | **TODO — gates Phase A; blocked on H-INT, H-AGY-2, H-ROLLBACK** |
| **A — autonomy threshold** | owner go/no-go → owner 8-point vacuousness review → foreground validating RB synthesis (`full_stop` present) → `rm full_stop` | **OWNER-ONLY** | **OWNER-GATED; BLOCKED on A-TEST** |
| **R — anchored-patch / AST-edit primitive** | a surgical anchored-patch `kind` (or sentinel regions) would make A.1/A.3/H-INT-class sub-symbol + module-level-import edits PIPELINEABLE, removing the recurring hand-edit exception. | hand-edit or pipeline | **DEFERRED — STRATEGIC, now highest-leverage** |
| H2 — C10 jail the host subprocesses | route verify (`:1635`), mutant `apply`/vcmd-rerun (`:1712`/`:1717`), worker `:619`, `sandbox_smoke.py`, `test_author.py` through `agent_jail.build_jail_argv` | pipeline/hand-edit | **DEFERRED — top hardening, non-gating** |
| H3 — unify budget formula | `ast_retry.py` (dormant, default-OFF) still uses the OLD `HARD = synthesis_timeout + 300`; share `_compute_timeout_budgets` | pipeline | **DEFERRED — LOW** |
| B3 nits | docstring/glob/repr | pipeline | **OPTIONAL** |

**Recommended sequence (rev 12): H-INT → H-AGY-2 + H-ROLLBACK → A-TEST → owner A.** H-AGY-2 and H-ROLLBACK must land before the timing-sensitive `A-TEST` execution to guarantee stability.

---

## PHASE H-INT — interceptor consistency fix (PIPELINE; services/** ⇒ NO §1b)

**Why pipeline:** `services/neurosymbolic/ast_verifier.py` is NOT under `harness/**`/`config/**`/`scripts/**`,
so no §1b approval is needed, and the change is a single-function partial_edit. No permanent blocker ⇒ **must be
attempted via pipeline, not hand-edited.**

**The fix (pick the minimal correct one):**
- *Minimal (No §1b):* downgrade `subprocess_no_check` severity `"ERROR"`→`"WARNING"` at `services/neurosymbolic/ast_verifier.py:127`, aligning it with `harness/ast_enforcer.py:125`. Verified: `subprocess_no_check` is the **SOLE** ERROR on both A-TEST draft submissions, so this downgrade leaves **zero** errors → the interceptor allows them.
- *Cleaner (Requires §1b):* have `ASTVerificationInterceptor` deny only on the **same** violations the real gate (`harness/ast_enforcer.validate_code`) treats as errors, passing `allow_nondeterminism=True` for `test_authoring` submissions.

**Oracle (commit FIRST):** a unit test asserting `ASTVerifier().verify(<code calling subprocess.run without check=True>)` is NOT `has_errors()`, RED on HEAD, GREEN after. `tests/**` ⇒ no §1b.

---

## PHASE A-TEST — re-run (PIPELINE; NO §1b) with a NON-VACUITY safeguard

**Preconditions:** H-INT, H-AGY-2, and H-ROLLBACK landed; spec dispatchable at `state/tasks/PHASE_A_JAIL_WRITEDENIAL_REGRESSION.json`; window 1800.

**R-vacuity (HIGH — A-TEST):** both the Claude and Gemini drafts are confirmed non-vacuous, but the config-flip mutant must be validated. Treat the **owner 8-point review point 8** ("passes for the wrong reason") as the non-skippable backstop.

---

## 2. Invariants carried through EVERY phase (do-NOT) — verified intact at `be4b100`

- **Never single-agent / lone-candidate acceptance — the four gates.** `grep -c "synthesis_success = True"`
  == 1 per file; gates byte-intact (worker `:237/:265/:296/:309`; orch bool gate `:2050`). HALT on any
  mismatch or a guard weakened to `if True/False:`.
- **Never narrow `BYPASS_FUZZER_TYPES`.** `test_authoring` stays `bypass_fuzzer:False`; the set is only ADDED to.
- **Never grant `skip_interface_fuzz` to any type other than `test_authoring`.** `_skip_ifz` is LITERALLY
  pinned to `mtt == 'test_authoring'` in both files; `grep -c skip_interface_fuzz taxonomies.py == 1`.
- **(NEW, F2) The submission-time interceptor must be NO STRICTER than the real acceptance gate.** After
  H-INT, keep `ASTVerificationInterceptor` ⊆ `harness/ast_enforcer.validate_code` errors.
- **(NEW, F1) agy-backed agents route their submission via STDIN** (`spawn_agent` agy branch). Never revert
  agy to argv `-p` + file-write-cascade in the jail.
- **Never add `*_fix`/any `<task>_fix` to the allowlist.** Deny-all.
- **`full_stop` stays present (`halted`) until owner-gated Phase A** (honored only in the daemon).
- **The §1b approval gate is the autonomous-commit boundary** (`_apply_approval_granted`, protected paths
  `harness/**`,`config/**`,`scripts/**` via `_enforce_apply_scope`).
- **`meta_task_type`/`mutations`/`mutation_target` are read ONLY from the trusted jail-ro task spec.**
- **Mutation-gate fail-closed semantics** (`_auto_commit_accepted`): no-mutant `test_authoring`→reject
  (`mutation_gate_missing`); un-appliable mutant→reject; vacuous test→reject; unexpected exception→
  `mutation_gate_error` rollback (H1). Do NOT weaken.
- **Agents are tree-isolated ONLY via the bwrap jail.**

---

## 3. Open risks specific to rev 12

- **R-interceptor-strict (HIGH, the live A-TEST blocker; addressed by H-INT):** see F2/§H-INT.
- **R-vacuity (HIGH, A-TEST):** config-flip mutant validation. See §A-TEST.
- **R-double-timeout (MED, H-AGY-2):** agy thread budget vs the parallel barrier; fix before timing-sensitive runs.
- **R-staging-collision (HIGH, H-ROLLBACK):** concurrency race on `{name}_staging`.
- **R-destructive-rollback (CRITICAL, H-ROLLBACK):** git reset bug on `sha=None`.
- **R-daemon-watchdog (MED, Phase A):** watchdog killing workers prematurely; re-widen for Phase A.

---

## Appendix A — rev-12 verification audit (2026-05-31, 8 agents, ground-truthed at `be4b100`)

Produced by 8 independent agents that ground-truthed the live code at `be4b100`.
- **A1-A4 (landed H1/A.3/window/AGY-FIX):** verified sound.
- **A5 (stricter interceptor):** confirmed verifier discrepancies block A-TEST.
- **A6 (daemon watchdog mismatch):** verified that 2100s watchdog timeout kills sequential retries.
- **A7 (staging collision / destructive rollback):** confirmed concurrent worktree deletion and `reset HEAD~1` when `sha=None` hazards exist.
- **A8 (rollback & pipeline gaps):** confirmed `run_pipeline` task zombie transitions, `no_diff` omissions, and partial files cleanup.

---

## Appendix B — file:line index (rev 12, anchored to HEAD `be4b100`)

- `harness/orchestrator.py`:
  - `spawn_agent` starting line **:308**
  - `_is_agy` check **:360**
  - agy-stdin branch **:361-402**
  - `run_agent_phase` **:587**
  - `run_both_agents` **:610**
  - parallel barrier `as_completed(timeout=timeout_seconds+30)` **:650**
  - `poll_for_submission` **:480**
  - `_path_b_outbox_fallback` **:444** (ast.parse gate **:468**)
  - four-gate bool **:2050**
  - fuzz guard / `_skip_ifz` **:2137**
  - `_auto_commit_accepted` starting line **:1435**
  - mutation gate check **:1739**
  - try/except block (H1) **:1759-1828**
  - taxonomy imports **:2310-2312**
- `harness/orchestrator_worker.py`:
  - four gates **:237/:265/:296/:309**
  - `_skip_ifz` **:320**
  - `_compute_timeout_budgets` (`HARD=2*window+slack`)
- `harness/interceptors.py`:
  - `ASTVerificationInterceptor.pre_tool_use` **:40-59** (denies on `verify().has_errors()`)
- `services/neurosymbolic/ast_verifier.py`:
  - `subprocess_no_check` severity `"ERROR"` **:127** (H-INT target)
- `harness/ast_enforcer.py`:
  - `subprocess_no_check` severity `'warning'` **:125**
  - `validate_code` **:187**
- `harness/config.yaml`:
  - `synthesis.timeout_seconds: 1800`
- `harness/agent_jail.py`:
  - `sandbox_enabled` **:59-62**
  - `build_jail_argv` **:65-247**
