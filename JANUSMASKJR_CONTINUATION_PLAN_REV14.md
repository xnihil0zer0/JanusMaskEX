# JanusMaskJR — Continuation Plan (2026-05-31, rev 14)

> **rev 14 — written after a 2-round, 8-agent independent, adversarial review of rev-13's content,
> verified against the live codebase using `codebase-memory-mcp`.**
> **rev-14.1 (2026-05-31) — 15 consensus corrections applied after a further 5-agent (4 sub-agents +
> overseer) adversarial pass; every applied correction had ≥3/5 agreement and hard evidence from live
> code at HEAD `2a8eb88`.**
> Supersedes `JANUSMASKJR_CONTINUATION_PLAN_REV13.md`. Governing rule (owner directive, carried):
> **use the PIPELINE for every change wherever possible; HAND-EDIT only after a pipeline attempt fails
> with a PERMANENT blocker (never a timeout).**
>
> **Read this first (one-paragraph state):** **HEAD `2a8eb88` (the rev-13-plan doc-only commit;
> code is byte-identical to its parent `f3fb023`, so all code line-anchors below remain valid),
> synced to `origin/master`.** The rev-13 review revealed
> that although the gating deliverable A-TEST (`f3fb023`) is landed, the plan made several **incorrect assumptions**
> about security containment and lifecycle timing. Specifically, unjailed verification/mutant runs, write access to
> host NPM/D-Bus/systemd paths, and direct in-process fuzz compiler `exec()` calls run **agent-authored code un-jailed
> on the host** (these paths were never wrapped by the bwrap jail — the jail is applied only at `spawn_agent`, so this
> is a standing gap, not a regression). Additionally, **one** timing-math unit test is red at HEAD
> (`test_retry_budget_exhaustion_exits_with_status_2`; the watchdog config test PASSES — see FIX-TESTS).
> **Gating posture (reconciling rev-13, which said "not blocked for a single foreground run"):** the two modes differ.
> **Autonomous/daemon operation is BLOCKED** (C5/C13 budget+suspension, C2/C3 concurrency, plus the unjailed-exec
> surface firing under unattended retries). For the **owner-supervised single foreground Phase-A go/no-go**, H2/H-FUZZ
> still gate it for a *specific* reason: verification, mutant, fuzz and smoke runs execute the candidate's code on the
> host **automatically, before the owner ever sees the result or reaches the §1b approval gate** — so the
> owner-in-the-loop does not cover that exec window. FIX-TESTS is a stale-test bug, not a Phase-A behavior regression;
> it gates only the use of the suite as a clean regression signal. Therefore Phase A remains **gated on H2, H-JAIL,
> H-FUZZ** (FIX-TESTS for the suite-signal), with the rationale above made explicit rather than asserted flatly.

---

## 0. Starting state — VERIFIED this session (do not re-do)

**Branch `master`, HEAD `2a8eb88` (rev-13-plan doc commit; code byte-identical to parent `f3fb023`), synced to `origin/master`.** rev-12 landings (re-audited SOUND, see §1):

| Commit | Item | Route | Audit verdict (rev-14 consensus) |
|--------|------|-------|--------------------|
| `0692490` | **H-INT oracle** — verifier no longer errors on `subprocess.run` w/o `check=True` | hand-edit (tests, first) | **SOUND** — RED on HEAD, GREEN after |
| `9bf6c8a` | **H-INT** — `subprocess_no_check` `"ERROR"`→`"WARNING"` in `services/neurosymbolic/ast_verifier.py` `_ASTVisitor.visit_Call` | **PIPELINE** | **SOUND** — interceptor⊆enforcer parity; `os.system` stays ERROR; bwrap unaffected |
| `1d805f6` | **ROLLB_B oracle** — sha=None destructive-reset case | hand-edit (tests, first) | **SOUND** |
| `a1f378d` | **ROLLB_B** — `if not sha: return` guard in `_rollback_rejected_commit` (orchestrator.py:1351-1353) | **PIPELINE** | **SOUND** — verified live at :1351-1353; prevents `reset --hard HEAD~1` on sha=None |
| `93f55fe` | **AGY2B oracle** — prose/placeholder yields `''`, valid unfenced code extracts | hand-edit (tests, first) | **SOUND** |
| `2e92759` | **AGY2B** — `_extract_python_block` no-fence `ast.parse` guard (test_author.py) | **PIPELINE** | **SOUND** |
| `f3fb023` | **A-TEST** — `tests/adversarial/test_phase_a_selfheal_jail_writedenial.py` (302 lines) | **PIPELINE** (`test_authoring`, NO §1b) | **SOUND** — positive+negative controls; content-equality assertions. ⚠ The "7/7 green real / 7/7 fail mutant" figures are from the landing-time pipeline run and were NOT re-executed this session (6 of 7 tests are `@requires_bwrap`-gated). **Re-run `pytest tests/adversarial/test_phase_a_selfheal_jail_writedenial.py -v` on the owner host (bwrap present) immediately before the Phase-A go/no-go, and confirm the bwrap-flip mutant yields 7 *failures*, not skips.** |

**Hard invariants re-verified intact:**
- `grep -c "synthesis_success = True" harness/orchestrator.py` → **1**
- `grep -c "synthesis_success = True" harness/orchestrator_worker.py` → **1**
- `grep -c skip_interface_fuzz harness/planner/taxonomies.py` → **1** (pinned to `test_authoring`)
- `_SENSITIVE_APPLY_GLOBS` (git_integration.py:16) → `('harness/**', 'config/**', 'scripts/**')` — UNCHANGED
- §1b approval gate `_apply_approval_granted` (orchestrator.py:1419) reads `state/control/decisions/<task_id>.json` — UNCHANGED

---

## 1. Adversarial Review findings — verification verdicts (Consensus-Approved)

Every finding from the 8-agent adversarial review rounds was re-derived and verified against the live code.

| # | Finding / Vulnerability | Sev (rev-13→ours) | Evidence (live code) | Maps to | Gating? |
|---|-------------------------|-------------------|----------------------|---------|---------|
| **C1** | `run_pipeline` failure branches park with `_mark_processed` (13 sites) rather than `_mark_blocked`. Foreground lacks `no_diff` support. | HIGH→**MED** | orchestrator.py:2135-2285 (13 `_mark_processed` sites) + merge_failed `_mark_blocked` :1847 | F6 / **ROLLB-E** | **NO** — Foreground only; daemon budget path already uses `_mark_blocked`. |
| **C2** | `staging_path` is global `{name}_staging` (no task_id) → concurrent workers collide. | HIGH→**MED** | orchestrator.py:1588 | F4 / **ROLLB-A** | **YES if concurrent** — Otherwise co-requisite with ROLLB-D to prevent directory leaks. |
| **C3** | Staging worktree lifecycle not wrapped in `try/finally` → leak on unexpected exceptions. | CRITICAL→**HIGH** | orchestrator.py:1593-1893 | F7 / **ROLLB-D** | **YES if ROLLB-A is applied** — Directory leaks occur on verification crashes otherwise. |
| **C4** | `_rollback_rejected_commit` single-file checkout of `target_rel`. The "other touched files left dirty" risk does NOT actually occur: the peer-commit branch `git revert`s and **returns at :1366** before reaching the checkout; the tip-unchanged branch runs `reset --hard HEAD~1` (:1368) which restores **all** files before the redundant single-file checkout (:1372). | LOW→**LOW (near-vacuous)** | orchestrator.py:1366/1368/1372 | F7 / **ROLLB-C** | **NO** — ROLLB-C is **cosmetic, not a correctness fix** (no file is left dirty on either branch); re-scope it to "delete the dead single-file checkout" or drop it. |
| **C5** | Watchdog `max(1800, timeout+300)`=2100s < worker hard budget `2*1800+300`=3900s. Widening watchdog formula will break config test. **(Numbers derive from `config.yaml:117 timeout_seconds=1800`; the daemon default fallback is 900, so the watchdog only floors at 2100 because the YAML sets 1800.)** | HIGH→**HIGH** | autowork_daemon.py:1373, test_autowork_daemon.py:83 | F3 / **AGY2D** | **YES for daemon runs** — Formula change requires updating mock clock in test (the test PASSES at HEAD; it only needs updating once AGY2D widens the formula). |
| **C6** | Unifying budget formula in `ast_retry.py` (H3) will break the mock time assertions in retry tests. | MED→**MED** | ast_retry.py:39, test_orchestrator_timeout_fixes.py:55 | H3 | **NO** — Unless H3 landed (requires updating mock monotonic clock side-effects). |
| **C7** | **vcmd verification & mutant runs execute agent-modified code on the HOST un-jailed** (`subprocess.run(shell=True)`, env-scrubbed via `_vcmd_scrubbed_env` but NOT contained) → **host code execution**. Not a "sandbox escape" — these paths were never jailed; the bwrap jail is applied only at `spawn_agent` (orchestrator.py:347). | CRITICAL→**CRITICAL** | orchestrator.py:1704, :1803/:1808 | H2 (C10) | **YES** — gating Phase A. Must jail verification + the mutant temp-copies. |
| **C8** | **Jail binds `XDG_RUNTIME_DIR` read-write** → Allows connect to D-Bus session bus and systemd socket, enabling spawning of host-unconfined transient units. | CRITICAL→**CRITICAL** | agent_jail.py:200-202 `--bind xdg xdg` | (new hardening) | **YES** |
| **C9** | **`~/.nvm` rw with no overlay** → persistent host hijack via node binaries (real, unmitigated). **Missing-file gap:** the ro-overlays of `settings.json`/`settings.local.json`/`skills`/`plugins`/`GEMINI.md`/`config` (:186-195) are guarded by `os.path.exists` (:194), so a file ABSENT at spawn is left writable under the rw `~/.claude` parent bind. Dynamic projects created after spawn bypass static overlay. **NOTE — already protected (do not re-protect):** existing `settings*.json`/`skills`/`plugins` and `~/.claude/projects/*/memory` ARE ro-overlaid. | HIGH→**CRITICAL** (for the `~/.nvm`-bin + absent-file vectors only) | agent_jail.py:131-134, :167-175, :186-195 | (new hardening) | **YES** |
| **C10** | **Narrow-Fuzz compiles and runs `exec()` in-process on host** → Executes agent-authored modules inside the un-jailed orchestrator process itself. **This is strictly the worst of C7/C10/C11** — it is in-process `exec`, not a child subprocess, so a jailed-subprocess fix is insufficient; the fuzz must move into a separate jailed python process. | HIGH→**CRITICAL** | `compile`+`exec` at narrow_fuzz/validation.py:75 (within `_exec_module` :71-78); `fuzz()` call site :117 | **H-FUZZ** | **YES** |
| **C11** | **Unjailed subprocesses in smoke and embedded test runner** → Spawns python/pytest unjailed on host for candidate verification. | HIGH→**CRITICAL** | sandbox_smoke.py:102, embedded_test_runner.py:131/160 | H2 | **YES** |
| **C12** | **Test suite broken at HEAD** (`test_retry_budget_exhaustion_exits_with_status_2` fails). | HIGH→**HIGH** | test_orchestrator_timeout_fixes.py:42 | **FIX-TESTS** | **YES** — Breaks the pipeline's own test validation. |
| **C13** | **Suspension Watchdog terminates workers** after 300s sequential run. Resumed workers consume wall-clock budget. | HIGH→**HIGH** | autowork_daemon.py:1385, orchestrator_worker.py:244 | **H-WORKER-DAEMON**| **YES for daemon runs** |

### Corrected Verification Verdicts (transparency)
*   **R2-F5 (Negative Control Write-Denial Check):** **PARTIALLY OVERSTATED — narrow residual gap.** The negative controls do NOT rely on `returncode != 0` alone: each (`:230-231, :240-244, :252-253, :264-266`) pairs it with a content-equality assertion (`target.read_bytes() == before` / HEAD-ref unchanged), and the POSITIVE controls assert `returncode == 0`, so a *total* bwrap-start failure would fail the positive controls rather than pass silently. The **residual** vacuity is narrow: a write that fails for a non-permission reason (e.g. inner-shell path quoting) without changing the target could pass. **Hardening (defense-in-depth, MED):** add a `r.stderr` substring check (`'Read-only file system'` / `'Permission denied'`) to confirm the failure is a real jail denial. This is a tightening, not closing a wide-open hole.
*   **R3-AGY2A (Double-Timeout):** **VALID GAP, mis-anchored.** `os.killpg` is ALREADY wrapped in `except (ProcessLookupError, PermissionError, OSError): pass` (orchestrator.py:~386-388) inside `spawn_agent`'s agy STDIN branch — so it does not raise out. The real residual is that after a killpg no-op/exception there is no `proc.kill()` + `proc.wait()` **reap**, so a surviving child can be re-polled for an extra timeout. Fix = add a direct `proc.kill()`+reap fallback at orchestrator.py:382-389 (NOT :380, which is the timeout-config line).

---

## 2. Phase map & ordering (rev 14) — SECURITY BLOCKERS FIRST

| Phase | Contents | Route | §1b | meta_task_type | Target symbol(s) | Gating | Status |
|-------|----------|-------|-----|----------------|------------------|--------|--------|
| **H2 — jail verification** | Route verify (`1704`), mutant (`1803/1808`), worker, `sandbox_smoke.py:102`, and `embedded_test_runner.py:131/160` through `agent_jail.build_jail_argv` | pipeline/hand-edit | **YES** | harness_self_fix | orchestrator.py, sandbox_smoke.py, embedded_test_runner.py | **YES** | TODO — Blocker |
| **H-JAIL — rw tightening** | Read-only bind `~/.nvm` (esp. `*/bin`); overlay/placeholder the *missing* `settings.json` case (the `os.path.exists` guard at :194 leaves absent files writable). Isolate XDG sockets. **⚠ CONFLICT:** the XDG rw bind (:200-202) is **load-bearing for agy OAuth** — the jail comment (:196-199) documents that agy "loops on authentication timed out" without it. A blanket tmpfs of `XDG_RUNTIME_DIR` will break agy auth; the fix must bind only the keyring socket (not the whole runtime dir) and **must be verified to keep agy authenticating** before landing. | hand-edit/pipeline | **YES** | harness_self_fix | agent_jail.py:131-134, :186-195, :200-202 | **YES** | TODO — Blocker |
| **H-FUZZ — fuzz sandboxing** | Move in-process `exec()` of fuzzer execution into a jailed python process | pipeline/hand-edit | **YES** | harness_self_fix | narrow_fuzz/validation.py:71-78, 117 | **YES** | TODO — Blocker |
| **FIX-TESTS** | Fix the **one** broken test `test_retry_budget_exhaustion_exits_with_status_2` (it exits 1 `synthesis_or_ast_failed`, asserts 2). Its live mock clock is `[0.0, 400.0, 400.0]` (NOT `[0.0,1000.0,1000.0]` — that is the candidate *fix* value, to be verified: elapsed must exceed the budget guard so `remaining < SYNTHESIS_WINDOW` fires → exit 2). **The watchdog test `test_autowork_daemon.py:83` PASSES at HEAD — it is NOT broken**; its mock-clock update belongs under AGY2D (only needed once the watchdog formula is widened), not here. | pipeline/hand-edit | **YES** | harness_self_fix | test_orchestrator_timeout_fixes.py:42 (clock at :50) | **YES** (gates the suite as a clean regression signal) | TODO — Blocker |
| **A — autonomy threshold** | owner go/no-go → owner 8-point vacuousness review of the A-TEST (w/ stderr checks) | **OWNER-ONLY** | — | — | — | **the gate** | **OWNER-GATED** |
| **H-WORKER-DAEMON** | Fix 300s suspension watchdog, inactivity watchdog limit scale, and subtract SIGSTOP duration from worker budget | pipeline/hand-edit | **YES** | harness_self_fix | autowork_daemon.py:1385, 1820; orchestrator_worker.py:244 | **YES for daemon** | TODO |
| **H-ROLLBACK-A** (ROLLB-A) | Make `staging_path` task-specific. **Co-requisite with ROLLB-D** to prevent disk leaks. | PIPELINE | **YES** | harness_self_fix | orchestrator.py:1588 | only if concurrent | TODO |
| **H-ROLLBACK-D** (ROLLB-D) | Wrap staging lifecycle in robust `try...finally` block | PIPELINE→hand-edit | **YES** | harness_self_fix | orchestrator.py:1593-1893 | only if concurrent | TODO |
| **H-ROLLBACK-E** (ROLLB-E) | Route foreground failures to `_mark_blocked` and implement `no_diff` check | PIPELINE→hand-edit | **YES** | harness_self_fix | orchestrator.py: run_pipeline (13 sites) | non-gating | TODO |
| **H-ROLLBACK-C** (ROLLB-C) | **COSMETIC, not a correctness fix** (C4 re-analysis: no touched file is left dirty — peer branch reverts+returns at :1366, tip-unchanged branch's `reset --hard HEAD~1` restores all). Re-scope to "remove the dead single-file checkout at :1372" or DROP. | PIPELINE | **YES** | harness_self_fix | orchestrator.py:1366/1368/1372 | non-gating (optional) | TODO |
| **H-AGY-2-A** (AGY2A) | `killpg` is already wrapped in `except…pass`; add a direct `proc.kill()` + `proc.wait()` reap fallback so a surviving child isn't re-polled for an extra timeout. | PIPELINE | **YES** | harness_self_fix | orchestrator.py:382-389 (killpg block; NOT :380) | non-gating | TODO |
| **G-METADATA** | Swap directory removal order: call `shutil.rmtree` BEFORE `git worktree prune` so pruning succeeds | PIPELINE | **YES** | harness_self_fix | orchestrator.py: remove_staging_worktree | non-gating | TODO |
| **G-UNTRACKED** | Do not drop the operator's stash if a `git stash pop` conflict occurs during parent merge | PIPELINE | **YES** | harness_self_fix | orchestrator.py: merge_staging_to_parent | non-gating | TODO |
| **R — anchored-patch** | anchored-patch `kind` for sub-symbol edits + module-level imports. Full-file AST check post-splice | hand-edit/pipeline | — | — | git_integration.py `_apply_symbol_patch` (:939) | strategic | **DEFERRED** |

> **Why Phase A is gated (reconciling rev-13, not silently reversing it):** rev-13 said Phase A was "not blocked for a single foreground run." That holds for the *agent-spawn* threat (spawns ARE jailed). What rev-13 under-weighted: the security surface C7/C10/C11 is the **verification/mutant/fuzz/smoke** path, which runs agent-authored code on the host **automatically, before the owner sees any result or reaches the §1b approval gate** — so even an owner-supervised run does not have a human in the loop at the exec moment. These are standing gaps (never jailed), not regressions. **Distinguish the modes:** (a) **autonomous/daemon** operation is BLOCKED by C5/C13 (budget+suspension) and C2/C3 (concurrency) on top of the exec surface; (b) the **owner-supervised single foreground go/no-go** is gated specifically by H2/H-FUZZ (the pre-review exec window) and H-JAIL. FIX-TESTS gates only the use of the suite as a clean regression signal (one stale test, not a behavior regression). Phase A **MUST NOT** proceed until H2, H-JAIL, and H-FUZZ are implemented and FIX-TESTS is resolved.

---

## 3. Invariants carried through EVERY phase (do-NOT)

- **Never single-agent / lone-candidate acceptance — the four gates.** `grep -c "synthesis_success = True"` == 1 per file. HALT on mismatch.
- **Never narrow `BYPASS_FUZZER_TYPES`.** `test_authoring` stays `bypass_fuzzer:False`; the set is only ADDED to.
- **Never grant `skip_interface_fuzz` to any type other than `test_authoring`.** `grep -c skip_interface_fuzz taxonomies.py == 1`.
- **(F2) Parity Align:** `subprocess_no_check` parity was **RESTORED by H-INT (`9bf6c8a`)** — both interceptor (`ast_verifier.py:127`) and enforcer (`ast_enforcer.py:125`) now emit WARNING. So "currently violated at HEAD" no longer holds for that rule. Remaining *suspected* interceptor-stricter cases (bare-except, typed-except-pass) are **UNVERIFIED** — audit `ast_verifier.py` vs `ast_enforcer.py` and confirm a concrete divergent rule before claiming a live parity violation. Maintain interceptor⊆enforcer parity going forward.
- **(F1) agy-backed agents route their submission via STDIN** (`spawn_agent` agy branch). Never revert agy to argv `-p` + file-write-cascade in the jail.
- **Never add `*_fix`/any `<task>_fix` to the allowlist.** Deny-all.
- **`full_stop` stays present (`state/control/autowork/full_stop`) until owner-gated Phase A.**
- **The §1b approval gate is the autonomous-commit boundary** (`_apply_approval_granted` orchestrator.py:1419).
- **`meta_task_type`/`mutations`/`mutation_target` are read ONLY from the trusted jail-ro task spec.**
- **Mutation-gate fail-closed semantics** (`_auto_commit_accepted`): no-mutant `test_authoring`→reject; un-appliable mutant→reject; vacuous test→reject; unexpected exception→`mutation_gate_error` rollback. Do NOT weaken.
- **Agents are tree-isolated ONLY via the bwrap jail.** ROLLB-B keeps `sha=None` from a destructive `HEAD~1` reset.

---

## 4. Open risks specific to rev 14

- **R-host-vcmd-exec (CRITICAL, Gating):** vcmd/mutant pytest runs execute un-jailed on the host, executing code from agent-modified source files (orchestrator.py:1704/:1803/:1808).
- **R-jail-rw-surface (CRITICAL, Gating):** XDG runtime directory bind allows D-Bus transient systemd unit host escapes. Writable `~/.nvm` enables node wrapper hijacking. Missing `settings.json` can be written to inject persistent hooks. Dynamic project folders bypass ro-bind memory overlays.
- **R-narrow-fuzz-exec (CRITICAL, Gating):** Compiling and running in-process `exec()` calls on agent-authored modules executes them inside the un-jailed orchestrator process on the host.
- **R-unjailed-smoke-embedded (CRITICAL, Gating):** Smoke-import and embedded test runners spawn unjailed subprocesses, exposing the host.
- **R-failing-tests (HIGH, Gating the suite-signal):** ONE unit test is red at HEAD — `test_retry_budget_exhaustion_exits_with_status_2` exits 1 (`synthesis_or_ast_failed`) where it asserts 2 (the mock clock `[0.0,400.0,400.0]` never trips the budget guard). The watchdog test PASSES. This is a stale-test bug, not a Phase-A behavior regression.
- **R-suspended-worker-depletion (HIGH):** Sequential runs kill suspended parallel PIDs after 300s. Resumed workers count suspension wall time against their monotonic budget clock.
- **R-inactivity-watchdog (HIGH):** Synthesis window is 1800s, but inactivity timeout is hardcoded to 1200s, causing false inactivity escalations on long runs.
- **R-metadata-pruning (MED):** Directory removal runs after worktree pruning, leaving stale `.git/worktrees` metadata references on failure.
- **R-stash-loss (MED):** Conflict on parent merge git stash pop drops the stashed changes, losing operator's untracked files.

---

## Appendix A — file:line index (rev 14, anchored to HEAD `2a8eb88`; code identical to parent `f3fb023`)

- `harness/orchestrator.py`:
  - `spawn_agent` **:308**; agy `_is_agy` branch **:~360-402**; jail wrap **:347**
  - `poll_for_submission` **:480** (early-return check **:528**)
  - `get_next_task` **:785** (processed/ dedupe)
  - `_mark_processed` **:1187**; `_mark_blocked` **:1240**
  - `_rollback_rejected_commit` **:1329** (sha=None guard **:1351-1353** [ROLLB-B]; single-file checkout **:1372** [ROLLB-C])
  - `_apply_approval_granted` **:1419**
  - `_auto_commit_accepted` **:1438**; `staging_path = {name}_staging` **:1588** [ROLLB-A]; lifecycle/cleanup **:1593-1893** [ROLLB-D]
  - vcmd run **:1704**; mutant apply **:1803**; mutant rerun/test **:1808**; check/rollback decision **:1813** [H2]
  - merge_failed `_mark_blocked` **:1847**
  - `run_pipeline` **:1958** (13 `_mark_processed` sites in :1958-2288) [ROLLB-E]
- `harness/orchestrator_worker.py`: four gates + `synthesis_success = True` (×1); `_mark_blocked` ×9; `use_retry_module` default False **:174**
- `harness/autowork_daemon.py`: watchdog `max(1800.0, timeout+300.0)` **:1373** [AGY2D]; watchdog suspension check **:1385-1395**; inactivity watchdog check **:1820-1853**; jail wrap **:604**; config CWD-relative **:635-637**
- `harness/agent_jail.py`: `~/.nvm`/`~/.gemini`/`~/.claude` rw bind **:131-134**; ro-overlays settings/skills/plugins/GEMINI.md **:163-195**; XDG `--bind` **:200-202**; repo ro-bind **:204**; state ro-bind **:214**
- `harness/git_integration.py`: `_SENSITIVE_APPLY_GLOBS` **:16**; `_apply_symbol_patch` **:939** (col-0 splice; AST parse **:989**) [R]
- `services/neurosymbolic/ast_verifier.py`: `subprocess_no_check` severity `"WARNING"` (H-INT, was ERROR) in `_ASTVisitor.visit_Call`
- `harness/ast_enforcer.py`: `subprocess_no_check` `'warning'` **:125**
- `harness/ast_retry.py`: `HARD = synthesis_timeout + 300.0` **:39** [H3]
- `harness/narrow_fuzz/validation.py`: `compile`+`exec` of candidate source in `_exec_module` **:71-78** (the `exec` is **:75**); `fuzz()` call site **:117** [H-FUZZ]
- `tests/test_orchestrator_timeout_fixes.py`: non-retry budget test **:42** (mock clock `[0.0,400.0,400.0]` at **:50**, RED at HEAD); retry-module budget test **:55** [FIX-TESTS]
- `tests/test_autowork_daemon.py`: watchdog configuration test **:83** — **PASSES at HEAD** (only update under AGY2D if the watchdog formula is widened; NOT a FIX-TESTS target)
- `tests/adversarial/test_phase_a_selfheal_jail_writedenial.py` (**302 lines**): negative controls (assert returncode!=0 AND content-equality) at **:225-266**; positive controls (assert returncode==0) at **:268-285**; sanity check/harness escalation test at **:287-302**
