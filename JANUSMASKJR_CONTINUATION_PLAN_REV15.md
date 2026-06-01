# JanusMaskJR — Continuation Plan (2026-05-31, rev 15)

> **rev 15 — written after the rev-14 gating chain was fully executed via the pipeline (9 dual-agent
> landings, 0 hand-edits) and then adversarially re-reviewed by a 4-agent Antigravity/Gemini panel
> (reports in `~/janusmask_briefs/review/R{1..4}_*.md`), with every panel claim re-verified by the
> overseer against live code at HEAD `187b681`.**
> Supersedes `JANUSMASKJR_CONTINUATION_PLAN_REV13.md` (rev-14 content). Governing rule (owner directive,
> carried): **use the PIPELINE for every change wherever possible; HAND-EDIT only after a pipeline attempt
> fails with a PERMANENT blocker (never a timeout, never a re-groundable verification failure).**
>
> **Read this first (one-paragraph state):** **HEAD `187b681`, synced to `origin/master`.** All four rev-14
> Phase-A gating blockers are CLOSED via the pipeline: FIX-TESTS (C12), H-FUZZ (C10), H-JAIL_A/B/C (C9/C9/C8),
> H2A/H2B/H2C (C7/C11), plus H2B-FIX (a self-caught smoke-interpreter regression). The dual-agent four-gate
> invariant is byte-intact (`synthesis_success = True` ×1 per file), §1b was respected (per-task decisions only;
> `state/control/**` is jail-ro), agy OAuth was smoke-verified under the new XDG jail, and the full suite is
> **6282 passed / 7 failed** where **all 7 fails are PRE-EXISTING** (identical at base `2a8eb88`; not
> session-caused). **Phase A (lift `full_stop`) remains OWNER-ONLY** and was not done. rev-15 records the
> remaining (non-gating) rev-14 items, the new hardening items the adversarial panel surfaced (filtered for
> Gemini false-positives), and a pipeline-first ordering for them.

---

## 0. Landed this session — VERIFIED (do not re-do)

All via PIPELINE (dual-agent, four-gate, §1b, oracle committed RED-first), tree byte-checked after each run.

| Commit | Item | Target symbol | Closes | Notes |
|--------|------|---------------|--------|-------|
| `72234ca` | FIX-TESTS | `test_retry_budget_exhaustion_exits_with_status_2` mock clock | C12 | tests/** = no §1b |
| `3cece79` | H-JAIL_A | `build_jail_argv` (`~/.nvm` → `--ro-bind`) | C9 | `.gemini`/`.claude` stay rw |
| `4f62d90` | H-FUZZ | `_exec_module` (in-proc `exec()` → jailed `python3` subprocess) | C10 | 3 attempts (2 re-grounds) |
| `20c6b55` | H-JAIL_B | `build_jail_argv` (absent overlays → `--ro-bind /dev/null`) | C9 | files+dirs both |
| `bb735df` | H2A | `_auto_commit_accepted` (verify+mutant jailed) | C7 | phase-B battery green |
| `29ee67f` | H2B | `smoke_import` (smoke subprocess jailed) | C11 | |
| `ddb831e` | H2C | `run_embedded_tests` (both pytest subprocesses jailed) | C11 | attempt 2 (1 re-ground) |
| `98048df` | H-JAIL_C | `build_jail_argv` (XDG whole-dir rw → `--tmpfs` + bus/keyring) | C8 | agy-auth smoke PASSED |
| `187b681` | H2B-FIX | `smoke_import` (jailed `python3` → venv 3.13 interp) | regression | self-caught by live sweep |

**Hard invariants re-verified intact at HEAD:** `grep -c "synthesis_success = True"` → 1 in both
`orchestrator.py` (:2170) and `orchestrator_worker.py` (:309); `skip_interface_fuzz` pinned to `test_authoring`
(×1); `_SENSITIVE_APPLY_GLOBS = ('harness/**','config/**','scripts/**')`; `state/control/**` jail-ro;
`full_stop` PRESENT.

**Grounding invariants learned this session (apply to EVERY harness_self_fix brief):**
1. The `harness_self_fix` fuzzer-bypass route **commits CLAUDE's submission only** (gemini is AST-syntax-only;
   see §2 R2). Ground toward claude being fully correct; gemini passing is irrelevant to acceptance.
2. Jailed subprocess interpreter MUST be jail-resolvable: use bare `python3` (jail ro-binds `/usr`,`/bin`),
   NEVER `sys.executable` (the venv `.venv→miniconda3` symlink chain is unbound → `bwrap execvp` fails).
3. `build_jail_argv(cmd, *, repo_root, work_dir, state_dir, home=None, extra_ro=())` — `cmd` is the ONLY
   positional; the rest are KEYWORD-ONLY; it self-appends `cmd`. Positional call → TypeError; never swallow it
   into an unjailed fallback (only `FileNotFoundError` = bwrap-absent justifies the documented fallback).
4. Jailed `pytest`/`import pytest` needs the venv interpreter+deps: `extra_ro=[sys.base_prefix, sys.prefix]`
   AND prepend `os.path.join(sys.prefix,'bin')` to the jailed `PATH`.
5. Re-dispatch cleanup: `rm state/tasks/blocked/<id>*.json state/tasks/test_results/<id>_baseline.json
   state/sessions/{claude,gemini}_round1_<id>_submission.json state/output/<id>.*` then re-place taskspec.
   Oracle commit + §1b decision persist across attempts.

---

## 1. Adversarial-panel findings — overseer-verified verdicts

The 4-agent Gemini panel raised the items below. Each was re-checked against live code; Gemini false-positives
are marked. **Trust the verdict column, not the raw panel claim.**

| # | Panel claim | Overseer verdict (verified @187b681) | Sev | Pipeline-viable? |
|---|-------------|--------------------------------------|-----|------------------|
| **SEC-1** | D-Bus session `bus` socket bound rw → jailed agent reaches `org.freedesktop.systemd1.StartTransientUnit` → host exec (bwrap doesn't unshare IPC). `agent_jail.py:231-235`. | **CONFIRMED — real residual.** Known/accepted tradeoff (agy OAuth needs the bus); H-JAIL_C narrowed XDG from whole-dir rw to bus+keyring but the bus residual remains. NOT a regression. | **HIGH** | Partially — needs `xdg-dbus-proxy` (new subprocess) ⇒ likely hand-edit after a pipeline attempt. |
| **SEC-2** | H2A verify+mutant use `extra_ro=[sys.base_prefix]` only, missing `sys.prefix` (H2C uses both). `orchestrator.py:1727/1834/1847`. | **CONFIRMED.** Works today only because the venv lives under `repo_root` (ro-bound); fragile for any venv outside repo_root. | **MED** | YES — single-symbol `_auto_commit_accepted` edit: `extra_ro=[sys.base_prefix, sys.prefix]`. |
| **SEC-3** | Fail-open/fail-closed inconsistency: `H2A`/`H2C` don't catch `FileNotFoundError` from `build_jail_argv` (crash if bwrap missing+enabled); smoke/`H-FUZZ` may fall back unjailed. | **CONFIRMED (dormant — bwrap present here).** Harmonize to fail-CLOSED: a missing bwrap while sandbox enabled must reject the run, never run unjailed and never crash the worker. | **MED** | YES — per-symbol guards. |
| **SEC-4** | H-FUZZ driver does not redirect the *candidate's* stdout, so a candidate `print('{"status":"ok"}')` could corrupt the JSON protocol and mask a crash. `narrow_fuzz/validation.py`. | **PLAUSIBLE — needs driver-source confirm.** grep shows the driver writes framed JSON to stdout and sends diagnostics to stderr, but no explicit `sys.stdout` redirect was found around the candidate call. Confirm, then harden. | **MED** | YES — single-symbol `_exec_module` edit: redirect candidate stdout to devnull/stderr in the driver before any candidate call. |
| **SEC-5** | Jailed verification (H2A) false-rejects legitimate future fixes whose `verification_command` needs paths the jail doesn't bind (`~/.local`, `/var/run` sockets, `/tmp`, network, editable installs). | **CONFIRMED — real operational risk.** Could stall the pipeline on valid work once jailing is the default. | **MED-HIGH** | YES — add a config-driven `agent_sandbox.verify_extra_ro`/`extra_rw` allowlist consumed by `_auto_commit_accepted` / `run_embedded_tests`. |
| MUT-MASK | (R2 Rank 1) Jailed mutant rerun failing for *infra* reasons (`returncode!=0`) is misread as "mutant caught" → masks a vacuous test. `orchestrator.py:1850`. | **DOWNGRADED to LOW.** The BASELINE verify is also jailed (same config, same `_mcopy`); an infra failure fails the baseline first → task rejected, not masked. Residual only if a mutant uniquely trips an infra limit. | LOW | YES (optional hardening — distinguish assertion-fail from infra-fail). |
| GATE-1 | (R2 Rank 3) `harness_self_fix` commits CLAUDE only; gemini is AST-syntax-only ⇒ 8/9 harness changes effectively single-author. | **CONFIRMED — design tradeoff.** Mitigated by §1b operator approval on every harness change. Worth strengthening (e.g. require gemini's submission to also pass the verification_command, or a differential check) but NOT a regression. | LOW/strategic | Needs design (route change) ⇒ hand-edit/strategic. |
| FP-1 | (R3) "the 7 suite failures are regressions introduced this session." | **REFUTED.** All 7 fail identically at base `2a8eb88` (overseer ran them there). Pre-existing. R4 concurs. | n/a | — |
| OK-1 | (R4) A-TEST `test_phase_a_selfheal_jail_writedenial.py` is non-vacuous (bwrap-flip mutant → 7 FAILURES, not skips). | **CONFIRMED** — supports the owner's Phase-A 8-point review. | n/a | — |

---

## 2. Unclosed rev-14 findings (non-gating) — status @187b681

(From rev-14 §1; re-verified by R3. None blocks the owner-supervised foreground Phase-A go/no-go; several gate
**autonomous/daemon** operation.)

| Item | What | Real? | Gates | Route | Anchor |
|------|------|-------|-------|-------|--------|
| **C2/ROLLB-A** | `staging_path` global `{name}_staging` → concurrent collision | yes | daemon-concurrency | **PIPELINE** (1-line, add `task_id`) | orchestrator.py:1604 |
| **C5/AGY2D** | watchdog `max(1800,timeout+300)`=2100 < worker hard 3900 → kills retrying workers | yes | daemon | **PIPELINE** (+update mock test) | autowork_daemon.py:1373 |
| **C6/H3** | `ast_retry HARD = timeout+300` vs worker `*2+300` → premature retry abort if attempt>300s | yes | retry-budget | **PIPELINE** (1-line + mock assert) | ast_retry.py:39 |
| **AGY2A** | timeout `killpg` with no `proc.kill()`+`wait()` reap → zombies | yes | hygiene | **PIPELINE** (replace except block) | orchestrator.py:385-388 |
| **G-METADATA** | `git worktree prune` before `rmtree` → stale `.git/worktrees` refs | yes | hygiene | **PIPELINE** (block swap) | git_integration.py:~1249 |
| **G-UNTRACKED** | `git stash drop` on pop-conflict → loses operator changes | yes | operator-safety | **PIPELINE** (block edit) | git_integration.py:~1356 |
| **C4/ROLLB-C** | dead single-file `git checkout` after `reset --hard HEAD~1` | yes | cosmetic | **PIPELINE** (delete block) | orchestrator.py:~1372 |
| **C3/ROLLB-D** | staging lifecycle not in `try/finally` → leak on exception | yes | daemon | **HAND-EDIT** (wraps whole fn body → reindent) | orchestrator.py:1608-1893 |
| **C1/ROLLB-E** | 13 `_mark_processed` failure sites in `run_pipeline` (no `_mark_blocked`/`no_diff`) | yes | foreground-only | **HAND-EDIT** (13 non-contiguous edits) | orchestrator.py:run_pipeline |
| **C13/H-WORKER-DAEMON** | suspended workers count SIGSTOP wall-time vs monotonic budget | yes | daemon | **HAND-EDIT** (signal/suspension accounting) | orchestrator_worker.py:244 |
| **R-anchored-patch** | only full-symbol replace; can't add module-level import/sub-symbol | yes | strategic | **HAND-EDIT** (new splicer) | git_integration.py:939 |

---

## 3. Regression-signal cleanup (NOT gating, NOT session-caused — restore a clean suite)

The 7 pre-existing fails break the suite as a clean regression signal. Fix them so future pipeline runs that
include the full suite get a green baseline. (Root-causes per R3/R4; verified pre-existing by the overseer.)

- **5×** `test_escalate_to_autobrief_*` (`test_autowork_self_healing.py`, `test_autowork_escalation.py`): the
  tests mock `builtins.open` globally so the daemon reads YAML where it expects the task JSON → empty
  `objective`/`files_touched` → the degenerate-escalation guard (`autowork_daemon.py:~631`) aborts before the
  mock `Popen`. Fix the TESTS (scope the `open` mock / populate non-empty task fields). **PIPELINE** (test edits,
  no §1b).
- **2×** `test_spawn_agent_cwd_relocated_outside_repo`, `test_T5_spawn_cwd...`: the agy STDIN path (prior-session
  AGY-FIX) calls `proc.communicate(...)`, but the tests' `_FakePopen`/`_P` mocks lack `communicate()`. Fix the
  TESTS (add a `communicate` to the fakes). **PIPELINE** (test edits, no §1b).

---

## 4. Recommended ordered next steps — PIPELINE-FIRST

Each pipeline item: Gemini drafts the brief → Opus sub-agent adversarially reviews/corrects → overseer ingests
UNREAD, commits the oracle RED-first, self-approves §1b (harness/**), runs the worker, verifies (exec-handover
`not_found` + integrate commit + both agent submissions + invariants + targeted suite). Hand-edit ONLY after a
pipeline attempt fails with a PERMANENT blocker (a new module-level import/top-level symbol the applier can't
add, or a genuinely multi-file/whole-body reindent change — NOT a re-groundable verification failure).

**Phase 1 — pipeline-viable (do these first):**
1. Regression-signal cleanup (§3): 2 test-fix tasks (escalation mocks; `_FakePopen.communicate`). Gets a green
   full suite so subsequent runs have a clean signal.
2. **SEC-2** — H2A/mutant `extra_ro=[sys.base_prefix, sys.prefix]` (harmonize with H2C). Easy, removes fragility.
3. **C6/H3** — `ast_retry.py:39` `HARD = synthesis_timeout*2 + 300.0` + update mock asserts.
4. **C2/ROLLB-A** — task-specific `staging_path`.
5. **C5/AGY2D** — widen watchdog formula + update mock test.
6. **AGY2A** — `proc.kill()`+`proc.wait(timeout=5)` reap fallback.
7. **G-METADATA**, **G-UNTRACKED**, **C4/ROLLB-C** — three small git_integration/orchestrator edits.
8. **SEC-3** — fail-closed harmonization (catch `FileNotFoundError`→reject, never unjailed) across
   `_auto_commit_accepted`/`run_embedded_tests`/`smoke_import`/`_exec_module`.
9. **SEC-5** — config-driven `agent_sandbox.verify_extra_ro`/`extra_rw` allowlist consumed by the jailed verify.
10. **SEC-4** — redirect candidate stdout in the H-FUZZ driver (after confirming the gap).

**Phase 2 — hand-edit ONLY after a failed pipeline attempt with a permanent blocker:**
11. **SEC-1** — `xdg-dbus-proxy`-filtered bus (restrict to `org.freedesktop.secrets`, block `systemd1`); requires
    spawning the proxy + binding its socket ⇒ attempt pipeline, expect a permanent blocker, then hand-edit. MUST
    re-run the agy-auth smoke (`~/janusmask_briefs/agy_jail_smoke.py`) after and revert if agy auth breaks.
12. **C3/ROLLB-D** (try/finally), **C1/ROLLB-E** (13 sites→blocked), **C13/H-WORKER-DAEMON** (suspension budget),
    **R-anchored-patch** (new splicer). Each: attempt pipeline first to demonstrate the permanent blocker.

**Phase A (OWNER-ONLY — the gate, unchanged):** `pytest tests/adversarial/test_phase_a_selfheal_jail_writedenial.py -v`
on the owner host; confirm the bwrap-flip mutant yields **7 failures, not skips** (non-vacuity, confirmed by R4);
owner go/no-go; `rm state/control/autowork/full_stop`. **Do NOT automate.**

> **Sequencing note:** SEC-1/SEC-5 materially change the autonomous-operation risk posture but are NOT required
> for the owner-supervised single foreground Phase-A run (the operator is in the loop). They ARE recommended
> before enabling the daemon. C2/C5/C13 remain the autonomous/daemon gate.

---

## 5. Invariants carried through EVERY phase (do-NOT)

- Never single-agent / lone-candidate acceptance: `grep -c "synthesis_success = True"` == 1 per file. HALT on
  mismatch. (Note GATE-1: on the bypass route claude is the sole *author*; the gate syntax is still intact and
  §1b is the human backstop — do not silently widen this.)
- Never narrow `BYPASS_FUZZER_TYPES`; `test_authoring` stays `bypass_fuzzer:False`; the set is only ADDED to.
- Never grant `skip_interface_fuzz` to any type other than `test_authoring` (`grep -c` == 1).
- agy-backed agents route submission via STDIN; never revert to argv `-p`+file-write in the jail.
- Never add `*_fix`/any `<task>_fix` to the allowlist. Deny-all.
- `full_stop` stays present until owner-gated Phase A. §1b (`_apply_approval_granted`) is the autonomous-commit
  boundary; `meta_task_type`/`mutations`/`mutation_target` read ONLY from the jail-ro task spec.
- Mutation-gate fail-closed semantics unchanged. Agents tree-isolated ONLY via the bwrap jail.
- After ANY agy run (uncontained): snapshot (`~/janusmask_briefs/repo_snapshot.sh`) + verify tree byte-identical
  + revert on drift. **Known nuisance:** loading the harness config from an external process re-emits
  `harness/config.yaml` with comments stripped (values identical) — restore with `git checkout HEAD -- harness/config.yaml`.
  (Minor; investigate whether a load path round-trips the YAML — low priority.)

---

## Appendix — file:line index (anchored to HEAD `187b681`)

- `harness/orchestrator.py`: `spawn_agent` jail wrap **:347**; agy STDIN branch **:360-402** (timeout killpg
  **:385-388** [AGY2A]); `_rollback_rejected_commit` redundant checkout **:~1372** [ROLLB-C]; `_auto_commit_accepted`
  jailed verify **:1727** / mutant-apply **:1834** / mutant-rerun **:1847** (all `extra_ro=[sys.base_prefix]`
  [SEC-2]); `_mvacuous` **:1850** [MUT-MASK]; staging_path **:1604** [ROLLB-A]; lifecycle **:1608-1893** [ROLLB-D];
  `run_pipeline` 13 `_mark_processed` sites [ROLLB-E]; four-gate `synthesis_success = True` **:2170** (×1).
- `harness/orchestrator_worker.py`: four gates + `synthesis_success = True` **:309** (×1); bypass save
  `_save_final_output(...,agent_a_code)` **:351** [GATE-1]; monotonic budget **:244** [H-WORKER-DAEMON].
- `harness/agent_jail.py`: nvm `--ro-bind` **:138-143** [H-JAIL_A]; `/dev/null` missing-overlay **:205-216**
  [H-JAIL_B]; XDG `--tmpfs`+bus/keyring **:229-235** [H-JAIL_C / SEC-1]; repo ro-bind **:~224**; state ro-bind
  **:~248**; sessions rw-bind **:266-275**.
- `harness/narrow_fuzz/validation.py`: `_exec_module` jailed driver **:71-300**; framed-JSON stdout **:175-189**;
  host readline **:124/267** [SEC-4]; gate uses `bwrap_available()` not `sandbox_enabled()` **:~248-254** [SEC-3].
- `harness/sandbox_smoke.py`: `smoke_import` jailed **:~108-137** (venv interp fix; FileNotFoundError fallback) [SEC-3].
- `harness/embedded_test_runner.py`: `run_embedded_tests` jailed **:144-188** (`extra_ro=[base_prefix,prefix]`,
  PATH prepend) [SEC-3].
- `harness/ast_retry.py`: `HARD = synthesis_timeout + 300.0` **:39** [C6/H3].
- `harness/autowork_daemon.py`: watchdog `max(1800,timeout+300)` **:1373** [AGY2D]; degenerate-escalation guard
  **:~631** [§3].
- `harness/git_integration.py`: `_SENSITIVE_APPLY_GLOBS` **:16**; `_apply_symbol_patch` **:939** [R];
  `remove_staging_worktree` prune/rmtree order **:~1249** [G-METADATA]; stash-pop drop **:~1356** [G-UNTRACKED].
- `tests/adversarial/test_phase_a_selfheal_jail_writedenial.py`: A-TEST (non-vacuous; bwrap-flip → 7 fails).
