# Design: Self-Healing Remediation Agent (autonomous operator)

**Status:** DRAFT for review — 2026-06-16
**Author:** operator session (factory)
**Reviewers wanted:** adversarial review of the FSM, the action-grammar bounds, the discipline guards, and the trust-boundary safety. This document is meant to be critiqued and torn apart before any of it is built.

> The substrate-mapping investigation returned (§7 is now `file:line`-evidenced). A root-cause adversarial audit (§0) found the failures this FSM was meant to remediate reduce to a few concrete fixes *simpler than the FSM itself*; git **provenance** of every code site this plan touches is in §0.55 (nothing here is older than 27 days; the keystone defect is ~4 days old). Read §0 first; it reframes the priority. **Build order is settled: keystone (A) → reclaim (C, sha-gated) → idle-wake (B, generalized) → pause-unify (R1, incl. resume) → NGv2 loopback wire (§0.4).** §0.6 is the consolidated execution state and route — the keystone fix, the pre-clean set, the liveness/restart ordering, the gate model, and the open items — all re-verified by scripted test (the keystone has been reproduced directly nine times across audit rounds). Everything in §0.6 reflects the live system as of 2026-06-16; superseded round-by-round framing has been removed.

---

## 0. Root-cause findings and execution state (2026-06-16)

Adversarial audit against the live system established the headline: **the "fail-silent, generic stall" framing of §1 over-generalizes.** The observed stalls were not many independent problems — they were **one root defect repeating** (§0.1), plus a **pattern of partially-landed fixes** (§0.2) that left gaps a *second* mechanism was later bolted onto. This argues for **landing a small set of targeted root fixes FIRST** (Phase 0: keystone A, reclaim C, idle-wake B, pause-unify R1) and only then judging how much of the §2 FSM is still warranted. §0.1–§0.55 are the root causes + provenance; §0.6 is the consolidated execution state and route. Every claim here is `file:line`-cited and reproduced by scripted test.

### 0.1 The single dominant root defect — the planner silently drops RED oracles
`_drop_redundant_precommitted_oracles` (`harness/planner/plan_normalizer.py:635-744`, guard at `:721`, drop at `:722`) deletes a `test_authoring` oracle whenever (a) its target module exists on disk AND (b) *some* committed test names that module AND (c) an in-plan impl touches that module. That heuristic **false-positives for every brief that adds a NEW test file to an already-tested existing module** — i.e. the entire "edit a harness file + author its new oracle" shape. The impl's `verification_command` still points at the dropped oracle's file → `verification_failed: file or directory not found` → clean `reject_rollback` → doomed retry loop.
- **Reproduced deterministically** against the live diff: `state/planning/current_diff.json` shows **both** Claude and Gemini drafted `daemon-wake-oracle`; it is dropped in *normalization*, NOT reconciliation. (This corrects my earlier misdiagnosis that reconciliation drops single-agent oracle tasks — it does not; the both-concede/one-defends merge keeps it.)
- **Blast radius:** this one defect blocked `daemon-wake`, `mfapb` (×2 tasks), and `poc_writer_cwe_expansion` — i.e. *every* spec-only impl+oracle brief, including the e2e-unblock work.
- **The fix (Phase 0, item A) — it is ONE invariant guarded across TWO passes** (reproduced directly, nine times). A plan = [impl editing an existing HEAD module + a NEW `test_authoring` oracle whose `mutation_target` is that module] is stripped of its oracle by **both** passes independently:
  - **PASS 1** `_drop_redundant_precommitted_oracles` (`:635-744`, guard at `:721`, drop at `:722`): its `covered` flag turns true when *any* committed `tests/**/*.py` imports the dotted module, and the `ac5af72` guard (`covered and _module_path(target) in impl_paths`) still fires because an impl+oracle brief *has* the impl sibling. `ac5af72` only spared STANDALONE oracles — it is itself a partial fix. Reproduced: PASS 1 alone on such a plan → `survivors: ['impl']`.
  - **PASS 2** `_drop_committed_module_impls` (`:745-844`, 100 lines, drop at `:814-817`): drops BOTH impl and oracle → `empty_plan`. Because `normalize_plan` runs once per brief with no brief-origin in the task dict, PASS 2 *cannot* see the cross-brief clobber it guards; its observable signal is byte-identical to the legitimate edit+new-oracle shape.
- **The guard:** add the same **file-keyed impl-gating predicate** to BOTH passes — skip the drop when the oracle's `files_touched` is named by some in-plan impl's `verification_command`. File-keyed (not module-keyed) is load-bearing: it is the only definition under which `tests/planner/test_dedupe_precommitted_oracle.py` stays green (a true cross-brief clobber, whose impl vcmd does NOT name the new oracle, still drops + emits `duplicate_module_skipped`). Real clobber defense remains downstream in `git_integration._enforce_apply_scope` + the in-plan anti-clobber oracle. Both patched symbols are <150 lines → single `__JANUSMASK_PATCHES__` symbol patches; the keystone edits TWO symbols in one impl-only brief.
- **Empirical result (verified on an isolated copy):** patching the predicate into both passes over the full `tests/planner/` dir (**64 files / 490 tests**) yields **2 failed / 488 passed** — failing exactly two committed **bug-asserting tests** that must be hand-corrected first (test edits, allowed): case (a) `test_committed_module_dedup.py:84` (`test_committed_module_rebuild_impl_and_paired_oracle_dropped`) and case (e) `:172` (`test_dependents_of_dropped_clobber_rewired`). Both must be inverted to assert KEEP/no-rewire.
- **Authoring discriminator (load-bearing):** the normalizer's `_is_test_authoring` keys on **`meta_task_type == 'test_authoring'`** (`:46-47`), NOT `task_type` or `kind`; `_task_id` keys on `task_id`. The keystone brief, its RED oracle, and any reproduction MUST set `meta_task_type` exactly, or the oracle is silently not processed as one and the guard never runs. This is the trap that hid the bug for five rounds.
- **Validation protocol (load-bearing):** verify the patch in a unique, single-shot worktree the live daemon cannot touch — the daemon sweeps `/tmp` copies mid-pytest (phantom failures), and pytest run from the repo cwd silently loads the REAL `harness/` over `PYTHONPATH` (a false "490 passed"). Run from a tree where the patched copy is the cwd-resolved `harness/`.
- `plan_normalizer.py` is **NOT** `_NEVER_AUTO_APPROVE` → auto-approvable, no decision file, no daemon restart (planner runs as a fresh subprocess). The keystone brief does not yet exist — authoring it is the first action. Its slug must avoid regenerating `impl-plan-normalizer`/`oracle-plan-normalizer` (both already present in `state/tasks/processed/`).

### 0.2 The recurring meta-pattern — fixes landed half-way, then duplicated
The redundancy hunt proved several "done" fixes were **partial**, so the gap resurfaced and a *second* mechanism was added beside the first instead of completing it. These are redundancy without added safety — the user's explicit target:
- **R1 — two pause gates that can't see each other.** `autowork_daemon.run_daemon` honors the `state/control/autowork/pause` **file-existence** sentinel (`autowork_daemon.py:2378`); `orchestrator.main()` honors `state/control/orchestrator.flag == "paused"` (`orchestrator.py:3288` → `control_gate.py:48-66`). The WebUI exposes **both** buttons against **different files** (`tools/webui_control.py:541-543` vs `:727-730`). Neither loop reads the other's gate → "pause orchestrator" leaves the live daemon dispatching. Plus a third `full_stop` sentinel only the daemon honors. **No single control stops everything.** Fix: one shared `control_gate.is_paused(state_dir)` predicate = union of all three, honored by both loops.
- **R2 — idle-sleep blind to ready retries** (this is exactly the `daemon_backoff_aware_wake` brief). Idle daemon sleeps `heartbeat`=1800s; the only early-wake `_autowork_watch_mtime` (`:2072-2094`) watches allowlist + `brief_hooks_*.md` ONLY — not `blocked/*.retry.json` backoff. A 300s retry waits up to 1800s. Confirmed live defect.
- **R3 — `required_task_ids` is rejection-only (a half-fix).** Read solely at `plan_validator.py:268-272` to *reject* a plan missing a required task; it **never re-adds** one, and is stamped (`cli.py:356`) AFTER normalize (`:355`) so it *cannot* preserve a task even in principle. It also works at cross-purposes with 0.1's drop pass. Completing it (stamp before normalize + exempt required ids from the drop) would *subsume* both the `ac5af72` standalone-oracle guard and 0.1's vcmd guard — a candidate single consolidation worth weighing against the minimal 0.1 fix.
- **R4 (owner-decision):** `auto_approve_sensitive_ceiling` + self-heal provenance block is **dead under the shipped `autowork.enabled:true` posture** (entirely inside `if not _widened:`, `orchestrator.py:2228-2278`) yet still increments a write-only counter (`:2847`). Either re-arm it as a backstop or stop pretending it gates.
- **R5/R6/R7 (keep / minor):** F1 sha-staleness `elif mtime` branch is a legacy no-sha fallback (keep, comment it); park-marker mtime-clear is complementary to F1 (keep, optionally sha-align); `KNOWN_ORPHAN_ALLOWLIST` is one stale entry (`config_loader.py`) from empty (wire-or-retire, then assert empty).
- **Genuine defense-in-depth (do NOT consolidate):** two-stage approval (dispatch vs commit), `_NEVER_AUTO_APPROVE` re-checked inside `git_integration._enforce_apply_scope`, the three Stage-A promotion gates, runtime `wire_up_gate` vs static orphan test (shared engine, different scope). Verified both paths execute and the second adds real safety.

### 0.3 The owner's north star has a precise, simple home
"Submit a brief → the system cleans and wakes itself to complete it." There is **no auto-clean-on-resubmit hook anywhere** (grep-confirmed). Because task_ids are deterministic brief-derived slugs, a resubmitted brief regenerates the *same* ids, which collide with stale state: **849 live `processed/` markers** (→ `zombie`/`processed_unaccepted`, never re-staged, `brief_status.py:73,89-90`), `.exhausted` markers that kill rerun forever (`autowork_daemon.py:911-912`; the held `poc-writer-cwe-expansion` is in this state now), and stale `state/output/<slug>.{py,patches.json,files.json}` sidecars that take precedence. **Fix (Phase 0, item C):** a `_reclaim_stale_brief_state()` called at the top of `_auto_promote` (`autowork_daemon.py:1360`) that evicts per-task `processed/`/`blocked/`/`output/`/`autocompiler/` artifacts **gated on `source_brief_sha256` mismatch** (never clobbers in-flight work). The gate MUST be sha-keyed, not mtime: scripted-verified that the stale `state/output/daemon-wake-impl.py` sidecar's mtime is *newer* than its brief, so an `brief_mtime > artifact_mtime` gate would refuse to evict the very sidecar most needing eviction. This is the literal embodiment of the directive — and it's a single hook, not an FSM.

### 0.4 The e2e blocker is NOT what standing memory says
Memory claims poc_writer CWE-template coverage is THE NGv2 e2e blocker. **False against current code.** `ngv2/poc_writer.py:378-382` now templates 9 CWEs incl. the two highest-volume live findings (CWE-22 ×13, CWE-918 ×8). The real binding blocker is the **unwired `LoopbackListener`**: `detonate_live` (`poc_runner_live.py:192-271`) never starts it / injects its port / checks its sentinel, so every SSRF (CWE-918) PoC connects to a dead port → `refuted` → fail-closed. **The correct next brief is wiring the loopback listener into the detonation jail, NOT the held CWE-expansion epic.** This invalidates §8 item 6 below.

### 0.55 Provenance of every code site this plan intends to change (git-verified 2026-06-16)
Repo age: JanusMaskJR first commit **2026-05-20** (27 days old); NobleGreedv2 separate repo. So *nothing* here is "months" old — the oldest target is 27 days. File created = first commit creating the file (`--diff-filter=A`); Symbol introduced = commit that added the function; Symbol last touched = most recent commit touching that **symbol's** line span (`git log -L`).

| # | Code site this plan changes | File created | Symbol introduced | Symbol last touched | Trust-core? |
|---|---|---|---|---|---|
| A | `plan_normalizer._drop_redundant_precommitted_oracles` (PASS 1, the dominant defect; guard `:721`/drop `:722`) | b897176 **2026-06-05** | feb13ad **2026-06-12** | ac5af72 **2026-06-15** (partial fix) | NO → auto-approvable |
| A′| `plan_normalizer._drop_committed_module_impls` (PASS 2, `:745-844`/drop `:814-817`) | b897176 **2026-06-05** | 32f85ab **2026-06-13** | a7091b0 **2026-06-13** | NO → auto-approvable |
| — | `plan_normalizer._sanitize_impl_verification_commands` (PASS 3, context only) | 81e726a 2026-06-05 | 436df86 2026-06-13 | 3 days | NO |
| B | `autowork_daemon.run_daemon` idle-sleep line ~2406 (R2 wake) | d1fcce0 2026-05-25 | 417f14c **2026-06-02** | **14 days untouched** | **YES** (decision file) |
| B-src | `autowork_daemon._retry_blocked_tasks` (mirrored read-only by B's helper) | d1fcce0 2026-05-25 | 7d1925e 2026-06-06 | not edited by this plan | YES |
| C | `autowork_daemon._auto_promote` (reclaim-hook host) | d1fcce0 2026-05-25 | 2692818 **2026-06-15** | **1 day** | **YES** (decision file) |
| R1 | `control_gate.check_pause` → new unified `is_paused` union | 9837077 2026-05-25 | 3ea7988 2026-06-13 | net-new predicate | NO (not in NEVER list) |
| R1 | `tools/webui_control.py` pause/resume writers (~:541, :727) | d1fcce0 2026-05-25 | ece3e4c 2026-06-13 | 3 days | NO |
| R3 | `plan_validator.validate_plan` (required_task_ids reject) | d1fcce0 2026-05-25 | c6b28e0 **2026-06-15** | **1 day** | NO |
| R3 | `planner/cli.py` required_task_ids stamp (`:105-107` **and** `:398-400`) + normalize at `:354-355` | d1fcce0 2026-05-25 | e639bb0 **2026-06-16** | **today** | NO |
| §0.4 | NGv2 `poc_runner_live.detonate_live` (loopback wire site) | 004e140 2026-06-11 | 7d6f8dd **2026-06-16** | **today** | NGv2 repo |
| §0.4 | NGv2 `loopback_listener.py` (unwired module) | cab40a7 2026-06-15 | cab40a7 2026-06-15 | 1 day, never re-touched | NGv2 repo |
| §0.4 | NGv2 `poc_writer._TEMPLATE_LIST` (CWE coverage, context) | a6e5ffd 2026-06-12 | d197ba8 2026-06-14 | 2 days | NGv2 repo |

**What the provenance reveals:**
- The keystone defect (A + A′) is the **youngest, least load-bearing code in the entire change set** — the dedup functions were added `feb13ad` (06-12) / `32f85ab` (06-13), and `ac5af72` (06-15) was a partial fix, not the closure. So the defect dates to ~4 days, in a file created `b897176` (06-05). The substrate they corrupt (`run_daemon`, `_auto_promote`, `validate_plan`) is 3–4 weeks old and stable. The regression is concentrated in fresh dedup code, not the old core → the simplest fix lives in the youngest code.
- The "for months" claim (now retracted) is impossible: the entire repo is 27 days old and these passes are ~4 days old.
- **Provenance-flagged discrepancy — RESOLVED NEGATIVE (R3).** The `:105-107` stamp lives inside `persist_plan` (called only at `:362`) and `:398-400` inside `_stamp_brief_metadata` (called only at `:356`). Both run **after** `normalize_plan` (`:355`); the normalizer never reads `required_task_ids`. So R3's "cannot preserve a dropped task even in principle" is **TRUE**. (Nuance: the validate-time *rejection* became functional only at `e639bb0`, today.)
- B touches a line untouched for 14 days inside trust-core `run_daemon` — low churn, high blast-radius → the one change here that most warrants the decision-file gate it already has.

### 0.6 Execution state and route (scripted-verified 2026-06-16)

This section is the current execution state — the keystone fix, the live-system pre-clean, the restart ordering, the gate model, and the open items. Every fact was reproduced by scripted test against the live repo. Absolute PIDs and timings are deliberately omitted (they rotate; discover at execution time).

**Build order (settled):** keystone (A) → reclaim hook (C, sha-gated) → idle-wake (B, generalized) → pause-unify (R1, incl. resume) → NGv2 loopback wire (§0.4). Keystone A and R1's `control_gate` leaf go live with **no daemon restart** (planner + per-task pipeline are fresh subprocesses); B, C, and R1's daemon-honor leaf are inert until one supervised daemon restart.

**(A) Keystone — the two-symbol patch.** Fully specified in §0.1: add the file-keyed impl-gating predicate to PASS 1 (`:721`) and PASS 2 (`:814-817`); hand-correct the two bug-asserting tests (cases a `:84`, e `:172`) to assert KEEP/no-rewire; set `meta_task_type` on the oracle; validate in an isolated single-shot worktree. One impl-only `harness_self_fix` brief on `plan_normalizer.py`, vcmd scoped to `tests/planner/`, no decision file, no restart. Expect 2-fail→0 after the test correction, 488 pass. Unblocks the mfapb re-plan.

**(B) Idle-wake — generalize, don't special-case.** The `daemon_backoff_aware_wake` brief caps idle sleep at the next *blocked-retry* window only. An idle daemon also sleeps through plan-park backoff (`_recently_failed_to_plan`) and the inactivity watchdog. Build ONE net-new helper `_next_timed_wake(state_dir, config)` returning `min(heartbeat, soonest of {blocked-retry, plan-park, watchdog} due-times)`, capping `sleep_target` at `autowork_daemon.py:2406`. Neither `_next_pending_wake` nor `_next_timed_wake` exists today (only `_autowork_watch_mtime:2072`) — build from scratch. `autowork_daemon.py` is trust-core → operator decision file (`daemon-wake-impl.json` exists) + supervised restart.

**(C) Reclaim hook — sha-gated, full coverage.** Per §0.3: `_reclaim_stale_brief_state()` at the top of `_auto_promote` (`:1360`), gated on `source_brief_sha256` mismatch (NOT mtime — proven unsafe in §0.3). Cover `processed/`, `blocked/` (incl. `.retry.json` and `.exhausted`), `output/*.{py,patches.json,files.json}`, `autocompiler/`, and `running/selfheal_*.pid` reconciliation. trust-core → decision file + restart. Also migrate the §3 action-grammar `CLEAR_STALE_PARK` row from mtime to the sha gate so the grammar matches.

**(R1) Pause-unify — must unify resume too, must not soften full_stop.** Three sentinels: orchestrator reads `orchestrator.flag=='paused'` (content, `control_gate.py:48-66`); daemon reads `autowork/pause` (existence, `:2378`); `full_stop` (existence, daemon-only, never auto-cleared — supervisor-respawn only). The two WebUI resume writers are asymmetric — `post_autowork_resume` unlinks `autowork/pause` (`webui_control.py:735`) vs `post_orchestrator_resume` rewrites `orchestrator.flag='running'` (`:548`). A unified `is_paused = pause ∨ orch_flag ∨ full_stop` honored by both loops MUST ship with a unified `resume()` that clears pause+orch_flag in one action but leaves full_stop untouched. `control_gate.py` is not trust-core; `webui_server` imports `webui_control` at module scope, so the webui leaf needs a **manual relaunch** (its parent is `systemd --user`, not a supervisor; `run-webui.sh` is teardown-on-exit, not a respawn loop, and is not running).

**(R3) required_task_ids is reject-only and runs after the drop.** `normalize_plan` runs first (`cli.py:355`); both stamps are after it; the normalizer never reads `required_task_ids`. Validate-time rejection became functional at `e639bb0` (today) — it is a backstop reject, not a preserve. The keystone guard is what actually prevents the drop.

**(R4, owner-decision) Dead ceiling.** Under `autowork.enabled:true`, `_widened=True` skips the provenance requirement and the ceiling read (`orchestrator.py:2223-2278`), yet the counter increments unconditionally (`:2847-2857`) → `auto_approve_count.json` is write-only. Either re-arm a rate cap outside `if not _widened:` or delete the dead read + counter.

**Gate model (resolved).** There is NO automatic full-suite in-jail gate. `_resolve_verification_command` (`orchestrator.py:1952`) returns the brief's literal vcmd verbatim; `_verify_from_ro_parent` (`git_integration.py:1608`) runs ONLY the 2 hermetic `_RO_GATE_TESTS` (defined `orchestrator.py:2395`, call site `:2809`, gated on `_granted_via_auto_approve and auto_approve_ro_gate`). So the harness gate = (brief's literal vcmd in the `bwrap --unshare-net` jail) + (2-test RO-gate, only on the auto-approve commit path). Keep each vcmd narrow AND hermetic (no net/abspath/subprocess so it passes inside `--unshare-net`); the full adversarial suite runs in-jail ONLY if a brief's vcmd IS the broad suite (forbidden). B/C/keystone face no full-suite gate.

**mfapb — the keystone bug reproduced in-plan (blocked-by A).** The staged `plan_hooks_multifile_additive_patch_bundle.json` has only the 2 `harness_self_fix` impl leaves; both vcmds reference `tests/adversarial/test_multifile_additive_patch_bundle.py`, which has never existed in git or on disk → guaranteed `verification_failed` (already logged: `exit 4, file or directory not found`; mfapb-2 has also hit `auto_commit_failed`). The *brief* DOES declare the oracle leaf (line 119); the planner dropped it — exactly the (A) bug, since `orchestrator`/`git_integration` are import-covered HEAD modules with impl siblings. **Remedy: land the two-pass keystone, then RE-PLAN mfapb so the oracle survives — do NOT hand-add the oracle, do NOT repoint the vcmd.** mfapb is the keystone's live validation case. Because `_auto_promote` runs while paused and `multifile_additive_patch_bundle` is allowlisted, the broken plan is re-staged every heartbeat → fix mfapb before the restart.

**mfapb slug-provenance (blocking pre-req, couples with the re-plan).** `mfapb-2-git-integration-newfile-kind` / `mfapb-3-orchestrator-routing-validation` are planner-minted; there is no `mfapb-1`; the brief's "Required plan shape" is prose with no `required_task_ids`. Three decision files exist at `state/control/decisions/` (`daemon-wake-impl`, `mfapb-2`, `mfapb-3`); a forced re-plan re-mints the 2 mfapb slugs and orphans those 2 decision files → trust-core leaves fail closed. **Fix: add `required_task_ids: [mfapb-2-…, mfapb-3-…, <oracle-leaf-id>]` and the oracle leaf to the brief before re-planning.**

**Landing while paused is impossible — use a single-shot drive.** A paused daemon dispatches nothing (`autowork_daemon.py:1794-1795` returns `chosen=[]`; `:1980` `if not paused:` hard-gates dispatch), and a brief commits only inside a dispatched worker (`orchestrator_worker.py:554`). Land each brief out-of-band: `stage_task` + `python -m harness.orchestrator_worker --task-id <id>` (commits a green result without unpausing). `_auto_promote` is NOT pause-gated (`:1374` checks only full_stop/disabled) → the paused daemon still stages, plans, retries, and harvests self-heal briefs.

**The system is NOT quiescently paused — reap+restart BEFORE pre-clean.** The inactivity watchdog is called every loop (`:2403`, outside the pause gate); `is_stuck` is gated by `not live_worker` (`:2933`), so it re-escalates once per worker-death cycle (muted only by `inactivity_escalated.json`, which is absent). A live `bwrap`+`claude` self-heal worker has been re-spawning throughout the audit (its pid rotated four times in this round alone) — its `running/selfheal_*.pid` is the documented all-dispatch-deadlock substrate. Any pre-clean done while the daemon loops is re-dirtied within a heartbeat. **Order: (1) discover + reap the live self-heal worker (`state/control/autowork/running/selfheal_*.pid` + `ps --ppid $(cat state/control/autowork.pid)`) and the orphan gemini poll-and-write process → (2) `kill -TERM $(cat state/control/autowork.pid)` (supervisor respawns; startup deletes `inactivity_escalated.json` at `:2330`) → (3) pre-clean → (4) single-shot-drive the landings → (5) unpause last.** Never kill the supervisor; never nohup a second daemon.

**Pre-clean set (after reap+restart, before unpause).** Discover-and-clear; do not hardcode pids:
- `state/control/git_commit.lock` — holds a dead pid (verify with `ps`/`kill -0`); a stale lock wedges commits.
- `state/tasks/blocked/{daemon-wake-impl,mfapb-2-…}.retry.json` — both at attempts==2 and at/past the 3600s backoff, so both fire attempt-3 on the next unpaused dispatch; clearing resets the budget so the keystone-fixed tasks get a clean run. (There is NO `mfapb-3` retry sidecar and NO `daemon-wake-impl.json` blocked dict — do not look for them. Both outcomes `worker_crash_orphan`/`auto_commit_failed` ∉ `_DETERMINISTIC_OUTCOMES` → `effective_max=3`.)
- the `state/output/*.py` sidecars (+ any `.patches.json`/`.files.json`) for the staged slugs.
- the 4 orphan gemini workdirs `JanusMaskJR_agentwork/gemini/gemini-r1-daemon-wake-impl-*` (sibling of the repo).
- staged specs `state/tasks/mfapb-2-…json` + `state/tasks/mfapb-3-…json` (dispatch-ready fuel that fires against the un-landed fix on resume), plus in-flight `state/planning/{brief.json,amendment_report.json}` and the stale `state/STATE.json` gemini_status. (The 849 `state/tasks/processed/` markers are NOT armed for this batch — the mfapb/daemon-wake/loopback slugs have no colliding marker; only `impl-/oracle-plan-normalizer` do, which the keystone slug must avoid.)

**Allowlist.** `auto_promote.allowlist` (`state/control/autowork/`) already has active `daemon_backoff_aware_wake` and `multifile_additive_patch_bundle`. Absent and to be added: `daemon_wake_oracle` (brief exists), the not-yet-authored keystone slug, and `ngv2_loopback`.

**(§0.4) NGv2 loopback wire — necessary and nearly sufficient (NGv2 repo, not JM trust-core).** Structural facts reconfirmed by scripted test: `LoopbackListener` is unwired (`grep LoopbackListener ngv2/poc_runner_live.py` → zero matches); `poc_writer.py:345` hard-codes `port='8000'` while `LoopbackListener` binds `port=0` (ephemeral, real port via `server_address[1]` → `.port`); loopback works inside `bwrap --unshare-net` (`lo` UP). The listener's `_record_request` writes an `fs_signature` sentinel into `work_dir` → lands in `fs_snapshot_diff` → `semantic_verdict` → `confirmed`. Wire content: start the listener, read its real `.port`, inject that port + a fresh nonce into the rendered payload, and bind the listener's `work_dir`/`fs_signature` to the detonation tmpfs. (The finding-VOLUME numbers — CWE-22 ×13, CWE-918 ×8, `may_confirm=True` — are inference-level until re-checked in `/home/xnihil0zer0/NobleGreedv2`; the structural claims stand.) This invalidates §8 item 6.

**Net:** the design is sound and the keystone is empirically reproduced (nine times) as a two-symbol patch. No further design rounds are warranted; remaining risk is operational. Open execution items: (0) author the two-symbol keystone brief; (1) fix mfapb's brief (oracle leaf + pinned `required_task_ids`); (2) reap-then-restart-then-preclean with discovered pids; (3) single-shot-drive the landings, unpause last; (4) B/C/R1 and the NGv2 loopback wire per the build order.

### 0.5 Reframe for this document
- Phase 0 root fixes (A = oracle-drop guard; B = backoff-aware wake R2; C = reclaim hook; + pause-unify R1) are **smaller and lower-risk than the §2 FSM**, and they remove the *causes* of most §8 problem-catalog entries rather than remediating their *symptoms*.
- The FSM's value proposition narrows to: (i) reading the *true* failure reason past log noise (§4 "crucial fix at the source" still stands), and (ii) the genuinely-novel-failure case. The "many gaps ⇒ need a general remediator" argument is weakened now that the gaps collapse to a few roots.
- **Open question for the next audit:** after Phase 0, is the FSM still justified, or does a much smaller "diagnose-and-loud-escalate" surface (no autonomous REMEDIATE) suffice? Look for the *deepest* shared root under §8 — the second pass already collapsed ~6 symptoms into 0.1+0.2; is there a still-simpler cut?

---

## 1. Motivation

The factory's dominant failure mode is **fail-silent, not fail-loud.** When the pipeline hits a problem — a malformed brief, an orphaned blocked task, an un-templatable finding, an exhausted approval ceiling, an `empty_plan` whose real reason is buried under log noise — it does not crash and it does not alert. It *quietly stalls or fails closed*, in a way often indistinguishable from normal "nothing to do" or "no bug found." A human (or, in practice, an operator agent) then has to notice, dig out the real reason, fix the root cause, and run the fix through.

Two cross-cutting audits (`JanusMaskJR/AUTONOMY_GAPS.md` — 12 gaps; `NobleGreedv2/AUTONOMY_GAPS.md` — 16 gaps) independently converged on this: **there is no single component that notices a problem and takes initiative to remedy it.** The existing self-heal is toothless — it can diagnose but its corrective brief requires operator promotion to ever run (see §7).

### What this is NOT
A passive "operator-action queue" that surfaces problems to a human inbox is the **wrong** answer. It just relocates the stall. The system should *rarely* need a human.

### What this IS
**Automate the operator role.** The thing a human currently does — "investigate this and fix it" — becomes an autonomous agent that is *alerted when a problem arises, diagnoses the root cause, fixes it (stepping outside the failing brief/plan when necessary), and runs the fix through to a green commit.** Initiative, not laziness.

### The non-negotiable constraint
The power to "step outside the task/brief/plan" is exactly the power to thrash, clobber, and go rogue. Therefore the remediator must operate under **strict state-machine discipline**: a bounded FSM with an explicit, auditable action-grammar, idempotent transitions, conflict-set safety, and hard budgets. It gets a leash, not free rein.

---

## 2. The remediation FSM

```
        ┌─────────┐   problem signal   ┌──────────┐
        │ WATCH   │───────────────────▶│ DIAGNOSE │
        └─────────┘                    └────┬─────┘
            ▲                                │ root cause + chosen action class
            │ resumed / no open problems     ▼
        ┌───┴─────┐    verified green   ┌──────────┐
        │ RESUME  │◀────────────────────│REMEDIATE │
        └─────────┘                     └────┬─────┘
                                             │ apply outcome
                                             ▼
                                        ┌──────────┐  unsafe / out of budget
                                        │  VERIFY  │──────────────────────▶ ESCALATE
                                        └──────────┘                        (rare, loud)
```

| State | Responsibility | Exit condition |
|---|---|---|
| **WATCH** | Subscribe to the unified problem bus (§4). Idle otherwise. | A problem signal fires → DIAGNOSE. |
| **DIAGNOSE** | Read the *real* reason (not log noise): classify root cause into a known problem-class with a known remedy template. Pull the precise PlanViolation/error, not the truncated `stderr_tail`. | Root cause + chosen action-class → REMEDIATE; or "unknown/unsafe" → ESCALATE. |
| **REMEDIATE** | Execute exactly ONE action from the bounded action-grammar (§3). This is the "step outside" state. | Action applied → VERIFY. |
| **VERIFY** | Confirm the remedy actually worked: brief now loads / plan now validates / blocked bomb drained / corrective fix committed green. | Verified → RESUME; failed and budget remains → DIAGNOSE (re-attempt, different action); failed and out of budget → ESCALATE. |
| **RESUME** | Release the original work to continue (unpause, re-promote, clear the marker). Return to WATCH. | Original work re-dispatched. |
| **ESCALATE** | Terminal-for-this-problem. Write a *loud*, human-visible record with the full diagnosis and what was attempted. Used ONLY when the fix is genuinely unsafe (trust-core) or budget-exhausted. | Human picks it up (rare). |

Each transition is **logged to a dedicated remediation ledger** so the whole episode is auditable after the fact.

---

## 3. The action-grammar (what REMEDIATE may do — the bounded "step outside")

REMEDIATE may execute exactly one of a **closed, enumerated set** of actions. Anything not on this list routes to ESCALATE. Each action is idempotent and scoped.

| Action | When | Bound |
|---|---|---|
| `FIX_MALFORMED_BRIEF` | brief fails `load_brief` (missing REQUIRED_SECTION, bad frontmatter) | May only add/repair frontmatter/sections deterministically; if the fix is ambiguous → ESCALATE. |
| `DRAIN_ORPHAN_BLOCKED` | a `state/tasks/blocked/<tid>.json` whose source brief is gone/withdrawn | Write `<tid>.exhausted`; purge the staging sidecars. Never touches an allowlisted-brief's blocked task. |
| `CLEAR_STALE_PARK` | a deterministic plan-park whose brief was since edited (`source_brief_sha256` mismatch — NOT mtime; see §0.3/§0.6 C) | Remove the `plan_attempts/<slug>.json` marker. |
| `AUTHOR_CORRECTIVE_BRIEF` | root cause is a harness defect (the recurring-failure class) | Author a `harness_self_fix` brief + inject it into the allowlist (§5). Subject to trust boundaries (§6). |
| `CORRECT_OVERCONSTRAINT` | plan rejected by a brief-level constraint that doesn't compose (e.g. `required_task_ids` on a decomposing epic) | Adjust the brief's constraint deterministically. |
| `RESTART_DAEMON_FOR_CODE` | a landed harness change isn't live (code-cache) | Trigger a supervised child restart (kill child; supervisor respawns). Gated on "a harness commit landed since daemon start." |
| `NO_OP_OBSERVE` | problem is transient (e.g. a single API hiccup) | Record and return to WATCH without acting. |

> **Reviewers:** is this set complete? Too broad? Each row is a place the agent acts on production state — scrutinize the bounds.

---

## 4. Problem bus (DETECT inputs)

Today these signals exist but **scatter** — some are logged, some are markers, nothing consumes them to *drive* remediation. The first build-step is to unify them into one subscribable bus:

- `planner_hallucination_discarded`, `empty_plan`, `plan_timeout` (in `state/impl_progress.jsonl`)
- Deterministic plan-park markers (`state/control/autowork/plan_attempts/*.json`, `deterministic:true`)
- Malformed-brief load failures (currently mislabeled as hallucinations — must be distinguished at the source)
- Blocked tasks + retry sidecars (`state/tasks/blocked/`)
- `auto_commit_failed`, rollback failures, quarantine
- Loop-spin circuit breaker (`_dispatch_timestamps`)
- Inactivity watchdog (20 min no `impl_progress` event)
- Exhausted ceilings (`auto_approve_sensitive_ceiling`, self-heal runaway ceiling)

**Crucial fix at the source:** several of these are *miscategorized* today (a malformed brief looks like a planner hallucination; an `empty_plan` reports ORCH log noise instead of the real `missing_required_task` PlanViolation). The bus is only as good as the signal — DIAGNOSE must read the *true* reason, which may require fixing the emit sites first.

---

## 5. The crux: autonomous corrective-brief injection ("initiative")

The single capability that separates this from the toothless status quo: **the remediator must be able to inject corrective work into the queue itself** — author a `brief_hooks_<slug>.md` at repo root AND add `<slug>` to the allowlist — without a human.

Today (to be confirmed by the substrate map) the self-heal can *diagnose* but its corrective brief **requires operator allowlist promotion to ever run** — so it never closes the loop. Granting autonomous injection is the heart of "initiative," and also the highest-risk capability, so it is the most tightly bounded:

- Only `harness_self_fix`-class corrective briefs, authored from vetted remedy templates.
- Rate-limited (N corrective briefs per window) and de-duplicated (don't re-inject a fix for a problem already in flight).
- Every injected brief is tagged with its triggering problem + diagnosis, fully auditable.
- The corrective brief still runs the **full normal pipeline** (planner, dual-agent synthesis, RED oracles, adversarial gate) — the remediator does not get to bypass validation; it only gets to *propose and dispatch* a fix that must still earn its green.

---

## 6. Discipline guards (the leash)

The design is only safe if these hold:

1. **Conflict-set safety (avoid the self-heal deadlock).** A KNOWN failure, **now fixed in code**: the inactivity self-heal worker (empty `files_touched`) conflicted with *every* real task via the conservative `can_run_parallel` (empty files ⇒ "could touch anything"), blocking ALL dispatch → the self-heal *caused* the inactivity it was meant to cure. The permanent fix is `harness/autowork_parallelism.py:40-41` (commit `ea6b9db`): any `selfheal_`-prefixed task id returns `can_run_parallel == True`, bypassing the empty-files conflict. **Design rule:** the remediator's own worker/pidfile MUST carry the `selfheal_` prefix (or declare an accurate, narrow `files_touched`); otherwise it re-introduces the all-dispatch block. This is the substrate the deadlock-avoidance must inherit, not re-derive.
2. **Bounded attempts per problem.** A problem gets K remediation attempts, then ESCALATE. No infinite loops (this session's `empty_plan` retried every ~500s — that exact class must be capped).
3. **Idempotent transitions.** Re-entering a state with the same input produces the same result; safe to crash/resume mid-episode.
4. **Trust boundaries respected, never bypassed.** `_NEVER_AUTO_APPROVE` trust-core files (orchestrator/daemon/git_integration/agent_jail…) still require an operator decision; the remediator routes those to ESCALATE rather than forcing them. It honors `harness_self_fix` requirements, sensitive-glob scope, and the approval ceilings.
5. **One open episode at a time per problem-class** (configurable), to prevent remediation storms.
6. **Everything logged, loudly.** Even successful self-healing writes a visible record, so an operator reviewing later can see exactly what the agent did and why.

---

## 7. Substrate it builds on (verified map, 2026-06-16)

This must *extend* existing machinery, not reinvent it. Confirmed `file:line` from the substrate map:

- **Diagnosis half (already runs, unconditionally):** `_escalate_to_autobrief` (`autowork_daemon.py:708`) spawns a jailed diagnosis agent when a task exhausts retries (`_retry_blocked_tasks` at `:937`, after the `.exhausted` marker `:928-935`). The agent writes `brief_hooks_<id>_fix.md` **to its outbox only**; its prompt (`:843`) explicitly forbids touching the live repo or the allowlist. The inactivity watchdog (`_check_inactivity_watchdog`, `autowork_daemon.py:2866`, called `:2403`) likewise spawns a **read-only** `diagnosis.md` agent (`_escalate_inactivity`, `:2695`), once-then-mute via `inactivity_escalated.json` (`:2935-2942`, auto-deleted on startup `:2330` and on recovery `:2947`).
- **Promotion half (toothless):** `_harvest_selfheal_briefs` (`harness/selfheal.py:225`) is the ONLY thing that injects corrective work — and it is a **pure no-op when `selfheal_auto_promote` is false** (`:268-269`, the live state, `config.yaml:63`). When on, it copies the outbox brief to repo root, synthesizes a plan, and mints an HMAC provenance marker. `_auto_promote_brief_eligible` (`autowork_daemon.py:2621`) additionally requires the flag **and** a valid provenance marker, OR an allowlisted-epic-child, OR the slug literally present in `state/control/autowork/auto_promote.allowlist`.
- **The single missing capability (§5 crux, confirmed):** the daemon **never opens `auto_promote.allowlist` for write** — grep-confirmed the only writer is the operator WebUI PUT (`tools/webui_control.py:828-923`). So today there is **no path** for the daemon to author a free-form repo-root brief AND self-promote its slug. That trusted, provenance-bound injection channel is exactly what this design adds.
- **Overseer gated-procedure FSM** (the reusable disciplined-state-machine substrate — **extend, don't reinvent**): `overseer/procedure.py` — `advance(procedure, phase, gate_result)` (`:68-89`) is a pure deterministic reducer; a failed gate returns `Blocked(reason, fix_hint)` and refuses to advance. Stdlib-only, no UI/tmux/network coupling. The **`daemon-supervisor` procedure** (OBSERVE→HEALTH→RECONCILE→REPORT) is the natural fit. Gates fail-closed (`overseer/gate_runner.py:30-31,151`). State persists to `state/procedures/{id}.json` (`overseer/procedure_state.py:25-60`) — survives restarts, resumable mid-episode.
- **Trust/approval machinery** — `_NEVER_AUTO_APPROVE` (`orchestrator.py:2282`: agent_jail, dbus_proxy, paths, git_integration, orchestrator, interceptors, selfheal, autowork_daemon, services/**). Even the **widened** auto-approve path (live, `config.yaml:57` → `_auto_approve_sensitive_eligible` `:2176-2256`) still rejects any `_NEVER_AUTO_APPROVE` match and any non-harness sensitive path (config/scripts/services). A remediator editing those files **fails closed** without an operator decision file — route to ESCALATE.
- **Problem bus (written, NOT consumed):** every signal is a JSONL row via `_emit_telemetry` (`autowork_daemon.py:150`) to `state/impl_progress.jsonl`, plus marker dirs (`tasks/blocked/`, `plan_attempts/`, `quarantine/`, `selfheal_skip/`). Nothing currently consumes these to drive a closed remediation loop — that subscription is the DETECT input.

---

## 8. Problem catalog (the cases the remediator must handle)

The 28 audited gaps are the initial test set. Lead cases (each is a (signal → diagnosis → action) the FSM must get right):

1. **Malformed brief** (JM gap #1): `brief_loader.py:187` → `cli.py:303` rc=3 → daemon `_check_hallucination` sets `deterministic:true` (`autowork_daemon.py:1636-1645`). Today: silent 24h park, mislabeled. Remedy: distinguish at source + `FIX_MALFORMED_BRIEF` / ESCALATE.
2. **Blocked-retry time-bomb** (JM gap #2): `_retry_blocked_tasks` (`autowork_daemon.py:883-971`) re-fires `blocked/*.json` with no allowlist/brief check. Remedy: `DRAIN_ORPHAN_BLOCKED`.
3. **Daemon code-cache** (JM gap #3): landed harness change not live until restart. Remedy: `RESTART_DAEMON_FOR_CODE`.
4. **`empty_plan` reason buried** (observed this session): real `missing_required_task` PlanViolation hidden behind ORCH log noise. Remedy: fix emit site + `CORRECT_OVERCONSTRAINT`.
5. **`required_task_ids` is rejection-only** (`plan_validator.py:268-272`): rejects a plan that drops a required task but never re-adds it, and is exact-match so it also never matches suffixed epic leaf IDs (see §0.2 R3). Remedy: complete the fix (stamp-before-normalize + drop-exempt), NOT a remediator action.
6. ~~NGv2: un-templatable CWE fail-closes…~~ **SUPERSEDED by §0.4.** poc_writer already templates the high-volume CWEs; the real e2e blocker is the unwired `LoopbackListener` in the detonation jail. The capability-gap-detection idea still has merit for *genuinely* novel CWEs, but it is not the current binding blocker.
7. **The dominant root (NEW, §0.1):** planner oracle-drop — not a remediation case at all, a one-line normalizer fix. Most of items 1–4's *symptoms* (verification_failed loops, empty_plan retries, blocked time-bombs) trace partly to it.
8. … remaining gaps in the two `AUTONOMY_GAPS.md` files (re-validate against §0 before treating any as live — several were partial-fix artifacts, not independent gaps).

---

## 9. Open questions for reviewers

1. **FSM home:** extend the overseer FSM, or a new dedicated remediation FSM that reuses its primitives? (Coupling vs. blast radius.)
2. **Action-grammar completeness/safety:** is §3 the right closed set? Which actions are too dangerous to grant autonomously even bounded?
3. **Corrective-brief injection rate/dedup policy:** what limits prevent a remediation storm while still being responsive?
4. **DIAGNOSE intelligence:** how much is template-matched (deterministic classifier) vs. an LLM agent reasoning over the failure? The more LLM, the more capable but the less predictable — where's the line given the discipline requirement?
5. **Escalation surface:** when it DOES escalate, where does that go so a human reliably sees it without it becoming the passive-queue anti-pattern?
6. **Conflict-set correctness:** how do we *prove* the remediator can't re-create the self-heal deadlock before granting it dispatch power?
7. **Build order:** which single gap should be the first end-to-end vertical slice (DETECT→…→RESUME) to prove the architecture? (Candidate: malformed-brief, since it's deterministic, low-risk, and bit us this session.)

---

## 10. Risks

- **Remediation storm / oscillation** — mitigated by bounded attempts, one-episode-per-class, dedup.
- **Self-heal deadlock recurrence** — the root cause is already fixed (`autowork_parallelism.py:40-41`, `ea6b9db`); residual risk is the remediator dropping the `selfheal_` prefix or declaring an empty `files_touched`. Guard #1 must enforce the prefix/conflict-set as a precondition, not assume it.
- **Over-broad autonomy editing trust-core** — mitigated by routing `_NEVER_AUTO_APPROVE` to ESCALATE.
- **Masking real defects by auto-papering-over** — every self-heal is logged loudly; recurring same-class remediations should themselves raise a "this keeps breaking" signal rather than being silently re-applied forever.
- **The remediator itself stalling silently** — it must be subject to its own liveness watchdog (who heals the healer?), with a hard human-escalation floor.
