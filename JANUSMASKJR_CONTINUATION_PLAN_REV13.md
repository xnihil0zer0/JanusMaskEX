# JanusMaskJR — Continuation Plan (2026-05-31, rev 13)

> **rev 13 — written after a CROSS-VENDOR (agy / Antigravity Gemini) adversarial review of rev-12's
> landed work, independently ground-truthed against the live code at HEAD `f3fb023`.**
> Supersedes `JANUSMASKJR_CONTINUATION_PLAN_REV12.md`. Governing rule (owner directive, carried):
> **use the PIPELINE for every change wherever possible; HAND-EDIT only after a pipeline attempt fails
> with a PERMANENT blocker (never a timeout).**
>
> **Read this first (one-paragraph state):** **HEAD `f3fb023`, pushed to `origin/master`.** The rev-12
> execution session landed, all via the dual-agent pipeline: **H-INT** (`9bf6c8a`, oracle `0692490`) —
> `subprocess_no_check` ERROR→WARNING in `services/neurosymbolic/ast_verifier.py` `_ASTVisitor.visit_Call`,
> restoring interceptor⊆enforcer (F2) parity and clearing the live A-TEST blocker; **ROLLB_B** (`a1f378d`,
> oracle `1d805f6`) — the CRITICAL F5 `if not sha: log; return` guard in `_rollback_rejected_commit`
> (orchestrator.py:1351-1353) that prevents a destructive `git reset --hard HEAD~1`; **AGY2B** (`2e92759`,
> oracle `93f55fe`) — `_extract_python_block` no-fence fallback now `ast.parse`-guards (returns `''` on
> non-code); **A-TEST** (`f3fb023`) — `tests/adversarial/test_phase_a_selfheal_jail_writedenial.py`
> (303 lines) proving the real bwrap jail denies writes to harness/state/memory/git and allows
> work_dir/sessions, **7/7 green on real config and 7/7 fail under the bwrap-flip mutant** (re-confirmed
> this session: `7 passed in 0.37s`). The A-TEST was the gating deliverable; **the next gate is OWNER-ONLY
> Phase A.** Environment re-verified: daemon **DOWN**; `full_stop` PRESENT at
> `state/control/autowork/full_stop` (the daemon-honored path); `auto_promote.allowlist` deny-all; `bwrap`
> present + `agent_sandbox.bwrap == true`; tracked tree CLEAN (only `harness/orchestrator.db` untracked).
>
> **Cross-model caveat (process):** this review pass WAS produced by **agy** (the cross-vendor reviewers
> the owner asked for), but **agy is known-unreliable and tampered the repo tree during the review** — its
> reports were therefore treated as UNVERIFIED CLAIMS and every actionable finding below was
> independently re-derived against the live code (file:line evidence) by the overseer. The tree was
> snapshot-verified clean afterward.

---

## 0. Starting state — VERIFIED this session (do not re-do)

**Branch `master`, HEAD `f3fb023`, synced to `origin/master`.** rev-12 landings (re-audited SOUND, see §1):

| Commit | Item | Route | Audit verdict (rev-13 re-derive) |
|--------|------|-------|--------------------|
| `0692490` | **H-INT oracle** — verifier no longer errors on `subprocess.run` w/o `check=True` | hand-edit (tests, first) | **SOUND** — RED on HEAD, GREEN after |
| `9bf6c8a` | **H-INT** — `subprocess_no_check` `"ERROR"`→`"WARNING"` in `services/neurosymbolic/ast_verifier.py` `_ASTVisitor.visit_Call` | **PIPELINE** | **SOUND** — interceptor⊆enforcer parity; `os.system` stays ERROR; bwrap unaffected |
| `1d805f6` | **ROLLB_B oracle** — sha=None destructive-reset case | hand-edit (tests, first) | **SOUND** |
| `a1f378d` | **ROLLB_B** — `if not sha: return` guard in `_rollback_rejected_commit` (orchestrator.py:1351-1353) | **PIPELINE** | **SOUND** — verified live at :1351-1353; prevents `reset --hard HEAD~1` on sha=None |
| `93f55fe` | **AGY2B oracle** — prose/placeholder yields `''`, valid unfenced code extracts | hand-edit (tests, first) | **SOUND** |
| `2e92759` | **AGY2B** — `_extract_python_block` no-fence `ast.parse` guard (test_author.py) | **PIPELINE** | **SOUND** |
| `f3fb023` | **A-TEST** — `tests/adversarial/test_phase_a_selfheal_jail_writedenial.py` (303 lines) | **PIPELINE** (`test_authoring`, NO §1b) | **SOUND** — 7/7 green real, 7/7 fail mutant; positive+negative controls; content-equality assertions |

**Hard invariants re-derived this session (all PASS):**
- `grep -c "synthesis_success = True" harness/orchestrator.py` → **1**
- `grep -c "synthesis_success = True" harness/orchestrator_worker.py` → **1**
- `grep -c skip_interface_fuzz harness/planner/taxonomies.py` → **1** (pinned to `test_authoring`)
- `_SENSITIVE_APPLY_GLOBS` (git_integration.py:16) → `('harness/**', 'config/**', 'scripts/**')` — UNCHANGED
- §1b approval gate `_apply_approval_granted` (orchestrator.py:1419) reads
  `state/control/decisions/<task_id>.json` — UNCHANGED

**Environment (verified):** daemon **DOWN**; `full_stop` PRESENT (`state/control/autowork/full_stop`);
`auto_promote.allowlist` deny-all; `bwrap` present + `agent_sandbox.bwrap == true`; tracked tree clean
(only `harness/orchestrator.db` untracked, a local SQLite artifact); memory ro-bound in the jail.

---

## 1. agy review findings — verification verdicts (CONFIRMED only; refuted/hallucinated excluded)

Every actionable finding from `/tmp/agy_review_out/R{1..4}.md` was re-derived against the live code.
The CONFIRMED set (real, with evidence) maps onto the deferred items already enumerated in rev-12 §0.1;
**agy surfaced no NEW gating defect** — its substantive correct findings are restatements of
rev-12's F-series and the deferred H-AGY-2 / H-ROLLBACK / H2 backlog. The single materially-new
*claim* (R3's "try/finally CRITICAL") is real-but-defensive (no current foreground leak path triggers it).

| # | Finding (agy) | Sev (agy→ours) | Evidence (live code) | Maps to | Gating? |
|---|---------------|----------------|----------------------|---------|---------|
| C1 | `run_pipeline` parks every failure with `_mark_processed`, never `_mark_blocked` (zombie tasks, no retry) | HIGH→**MED** | orchestrator.py: 12 `_mark_processed` sites in `run_pipeline` (1958-2280); `_mark_blocked` (:1240) is used by the **worker/daemon** path (orchestrator_worker.py ×9, orchestrator.py:1847 merge_failed) but NOT by foreground `run_pipeline` | F6 / **ROLLB-E** | **NO** — foreground-only; the daemon path (the retry-budget owner) already uses `_mark_blocked`. Foreground has no retry budget. Re-dispatch gotcha = `rm` the `processed/` shadow (memory learning 4). |
| C2 | `staging_path` is global `{name}_staging` (no task_id) → concurrent workers collide | HIGH→**MED** | orchestrator.py:1588 `staging_path = worktree_root.parent / f"{worktree_root.name}_staging"` | F4 / **ROLLB-A** | **NO for a single foreground run** (one worktree at a time). Gating ONLY if Phase A runs concurrent workers. |
| C3 | Staging worktree lifecycle not wrapped in `try/finally` → leak on unexpected exception locks out future tasks | CRITICAL→**MED** | orchestrator.py:1593-1893 — `remove_staging_worktree` IS called best-effort at each branch return (:1631,:1729,:1756,:1816,:1826,:1893) but there is NO single outer `try/finally`; an exception on a path that skips those calls leaks the dir | F7 / **ROLLB-D** | **NO** — every *known* exit path already cleans up; only an *unhandled* exception between create (:1594) and the next cleanup leaks. Defensive hardening, not a live blocker. (agy over-rates as CRITICAL.) |
| C4 | `_rollback_rejected_commit` only checks out `target_rel` (files_touched[0]); other touched files left dirty | LOW→**LOW** | orchestrator.py:1372 `git checkout HEAD -- target_rel` only | F7 / **ROLLB-C** | **NO** — multi-file rollback only; single-file tasks unaffected. |
| C5 | Daemon sequential watchdog `max(1800, timeout+300)`=2100s < worker hard budget `2*1800+300`=3900s → kills retries | HIGH→**MED** | autowork_daemon.py:1373 `watchdog_timeout = max(1800.0, float(timeout_val)+300.0)` | F3 / **AGY2D** | **NO right now** (daemon DOWN). Gating for **Phase A daemon runs**: re-widen to `max(1800.0, 2.0*timeout+600.0)` before any daemon-driven retry-capable run. |
| C6 | `ast_retry.py` uses `HARD = synthesis_timeout + 300` (not `2*…`) | MED→**LOW** | ast_retry.py:39 `HARD = synthesis_timeout + 300.0` | H3 | **NO** — `use_retry_module` defaults `False` (orchestrator_worker.py:174, orchestrator.py:1983) and is absent from `config.yaml`; the module is dormant. |
| C7 | vcmd verification + mutant re-run execute on the HOST un-jailed (`subprocess.run(shell=True, env=_vcmd_scrubbed_env())`) — arbitrary host code during pytest | CRITICAL→**MED** | orchestrator.py:1704 (vcmd), :1808/:1813 (mutant apply + vcmd); `build_jail_argv` is wired ONLY into agent *synthesis* spawns (orchestrator.py:347, autowork_daemon.py:604), NOT verification | H2 (C10) | **NO** — vcmd/mutants come from the **trusted jail-ro task spec**, not agent-authored stdout; the agent cannot inject the vcmd. Top hardening item, long-known deferred. |
| C8 | Jail binds host `XDG_RUNTIME_DIR` **rw** (D-Bus/keyring/systemd-user sockets) → potential namespace-escape via session bus | CRITICAL→**LOW/UNCERTAIN** | agent_jail.py:200-202 `--bind xdg xdg` | (new hardening) | **NO** — documented as load-bearing for agy OAuth keyring refresh (jail comment :196-199); a write *boundary*, not an exfil/IPC boundary; this is a hardening trade-off, not a regression. Probe deferred. |
| C9 | Jail binds `~/.nvm`, `~/.gemini`, `~/.claude` **rw** (node runtime / CLI dirs writable) → host-exec persistence | HIGH→**LOW** | agent_jail.py:131-134 `--bind` each | (new hardening) | **NO** — deliberate (CLIs write session/oauth state); the *dangerous* sub-paths (`~/.claude/settings.json`, `settings.local.json`, `skills`, `plugins`, `~/.gemini/GEMINI.md`, `config`, and every `projects/*/memory`) ARE ro-overlaid (:163-195). Residual rw surface (e.g. `~/.nvm` binaries, `~/.claude/projects/` root) is a hardening gap, not a live escape. |

### Refuted / over-rated agy claims (transparency)
- **R2-F5 "false PASS on bwrap-start failure":** **REFUTED for the suite.** The A-TEST carries positive
  controls `test_jail_allows_write_to_work_dir` (:269, asserts `returncode==0`) and
  `test_jail_allows_write_to_state_sessions` (:279) — if bwrap could not start at all these FAIL, so a
  total sandbox crash cannot leave the suite green. Negative tests also assert content-equality
  (`al_before` :244). The single-test concern is fail-safe (loud fail), not a vacuous pass.
- **R2-F3 "CWD dependency → false FAILURE":** **REFUTED as gating.** The config is loaded CWD-relative
  (autowork_daemon.py:635), and the test is run from the repo root (where pytest is invoked), so config
  IS found and bwrap IS applied (7/7 green confirmed). Running from a foreign CWD would fail *loud*, not
  pass vacuously — a portability nit, LOW.
- **R3 "try/finally is CRITICAL / gating":** **REFUTED as gating** (kept as MED hardening, C3). Every known
  exit path already calls `remove_staging_worktree`; no live foreground path leaks.
- **R3-AGY2A "spawn_agent double-timeout (another full 1800s in poll)":** **REFUTED for the normal case.**
  The agy branch `proc.communicate(timeout)` SIGKILLs the process group on timeout (orchestrator.py:~380),
  and `poll_for_submission` early-returns once `proc.poll() is not None` (:528) — a SIGKILL'd proc is
  reaped promptly, so poll does not re-spend the full budget. Subtle edge only; matches the rev-12 memory
  note "agy-via-stdin already fast". Tracked as LOW (AGY2A).
- **R4 four-gate "collusion" / "agent knows the mutants":** **NON-ACTIONABLE / architectural.** The
  four-gate `synthesis_success` and mutation gate are working as designed (invariants re-verified == 1).
  Mutant-awareness is mitigated by the **owner 8-point review point 8** ("passes for the wrong reason"),
  which is the non-skippable Phase-A backstop. No code defect.
- **R4 §1b "self-approval falsifies audit trail":** **PROCESS NOTE, not a code regression.** The bwrap jail
  makes `state/control/decisions/**` read-only to the *agent* (agent_jail.py:205-215), so only the host
  operator session can write a decision file. The owner explicitly authorized §1b self-approval for this
  session to avoid in-project approval prompts; cryptographic-signing (R4 rec #2) is a future hardening
  option, recorded under "Open risks", not a blocker.
- **R4 "no full-file AST validation post-splice":** real-but-LOW (the verification command surfaces a
  corrupt merge as a test failure → reject). Folded into the deferred **R (anchored-patch)** strategic item.

---

## 2. Phase map & ordering (rev 13) — PIPELINE-FIRST

| Phase | Contents | Route | §1b | meta_task_type | Target symbol(s) | Gating | Status |
|-------|----------|-------|-----|----------------|------------------|--------|--------|
| 0…A-TEST | rev-12 landings | pipeline | — | — | — | — | **DONE — re-audited SOUND** |
| **A — autonomy threshold** | owner go/no-go → owner 8-point vacuousness review of the A-TEST → foreground validating RB synthesis (`full_stop` present) → `rm full_stop` | **OWNER-ONLY** | — | — | — | **the gate** | **OWNER-GATED — NEXT** |
| **H-ROLLBACK-A** (ROLLB-A) | `staging_path` → `{name}_staging_{task_id}` | PIPELINE | **YES** | harness_self_fix | orchestrator.py:1588 `_auto_commit_accepted` (single line, mid-function) | only if concurrent | TODO — before any concurrent Phase-A run |
| **H-ROLLBACK-E** (ROLLB-E) | route `run_pipeline` failure branches to `_mark_blocked` (+ honor `no_diff`) | PIPELINE→hand-edit | **YES** | harness_self_fix | orchestrator.py:`run_pipeline` (:1958-2280, 12 sites — **large fn, drift risk**) | foreground retry only | TODO — defensive |
| **H-ROLLBACK-D** (ROLLB-D) | wrap staging create/use/remove in `try/finally` | PIPELINE→hand-edit | **YES** | harness_self_fix | orchestrator.py:1593-1893 `_auto_commit_accepted` (**large rewrite — hand-edit candidate**) | non-gating | TODO — defensive |
| **H-ROLLBACK-C** (ROLLB-C) | checkout ALL `files_touched`, not just `target_rel` | PIPELINE | **YES** | harness_self_fix | orchestrator.py:1371-1372 `_rollback_rejected_commit` | non-gating | TODO — LOW |
| **H-AGY-2-D** (AGY2D) | watchdog formula → `max(1800.0, 2.0*float(timeout_val)+600.0)` | PIPELINE→hand-edit | **YES** | harness_self_fix | autowork_daemon.py:1373 (inside `_iteration`, **large nested fn — column-0 directive / hand-edit candidate**) | **YES for daemon Phase A** | TODO — before any daemon retry run |
| **H-AGY-2-C** (AGY2C) | jail-ENABLED `spawn_agent` test (assert `argv[0]` endswith `bwrap` + repo ro-bound) | PIPELINE | **NO** | test_authoring | new test under `tests/adversarial/` | non-gating | TODO — coverage |
| **H-AGY-2-A** (AGY2A) | guard the agy `communicate`-timeout→`poll` budget edge (pass short/zero poll budget when proc already dead) | PIPELINE | **YES** | harness_self_fix | orchestrator.py:~355-402 `spawn_agent` agy branch | non-gating (subtle) | TODO — LOW |
| **R — anchored-patch / AST-edit primitive** | a surgical anchored-patch `kind` (or sentinel regions) makes sub-symbol + module-level-import + nested-method edits PIPELINEABLE; folds in R4's full-file post-splice AST check | hand-edit or pipeline | — | — | git_integration.py `_apply_symbol_patch` (:939) | strategic | **DEFERRED — highest leverage** |
| **H2 — jail vcmd / mutant host subprocesses** (C10) | route verify (orchestrator.py:1704), mutant apply+rerun (:1808/:1813), worker `:619`, `sandbox_smoke.py`, `test_author.py` through `agent_jail.build_jail_argv` | pipeline/hand-edit | **YES** | harness_self_fix | orchestrator.py:1704/:1808/:1813 | non-gating | **DEFERRED — top hardening** |
| **H-JAIL — residual rw-surface tightening** | (optional) probe/ro-overlay `~/.nvm` bins + `~/.claude/projects/` root; revisit XDG `--bind`→narrower | hand-edit | **YES** | — | agent_jail.py:131-134, :200-202 | non-gating | **DEFERRED — LOW (from agy C8/C9)** |
| H3 — unify budget formula | `ast_retry.py:39` `HARD` (dormant, default-OFF) → share `_compute_timeout_budgets` | pipeline | YES | harness_self_fix | ast_retry.py:39 | non-gating | **DEFERRED — LOW** |
| B3 nits | docstring/glob/repr | pipeline | — | — | — | optional | **OPTIONAL** |

**Recommended sequence (rev 13):**
1. **OWNER Phase A** — nothing below blocks it for a *single foreground* RB synthesis run (the A-TEST is
   landed; all CONFIRMED items are non-gating for one foreground worker — see §1 "Gating?" column).
2. If Phase A is run **under the daemon with retries**: land **AGY2D** (watchdog) first (the only item
   that actually cuts off retries), and **ROLLB-A** (per-task staging) if workers run concurrently.
3. Then the remaining defensive H-ROLLBACK / H-AGY-2 items (C/D/E, AGY2A/C) via pipeline.
4. Strategic: **R (anchored-patch)** → **H2 (jail vcmd)** → **H-JAIL** → H3 → B3.

> **Why Phase A is NOT blocked (correcting agy R3):** agy argued H-ROLLBACK/H-AGY-2 are "gating blockers
> before owner Phase A." Re-derivation shows the gating-claimed items are all conditional on
> **concurrency** (ROLLB-A) or the **daemon retry budget** (AGY2D, ROLLB-E) — neither is exercised by a
> single foreground RB synthesis with `full_stop` present. The one true CRITICAL (F5 destructive rollback)
> is ALREADY LANDED (ROLLB-B `a1f378d`). So Phase A may proceed at owner discretion; the deferred items
> are hardening for the *autonomous-daemon* phase that follows.

---

## PHASE A — autonomy threshold (OWNER-ONLY)

**Preconditions (all MET):** A-TEST landed (`f3fb023`) + re-confirmed 7/7 green; `full_stop` present;
window 1800; tree clean; invariants intact.

**Owner steps (do NOT do autonomously):** owner go/no-go → **owner 8-point vacuousness review of the
A-TEST** (point 8 = "passes for the wrong reason" — the non-skippable mutant-awareness backstop, covers
R4's collusion concern) → foreground validating RB synthesis with `full_stop` PRESENT → `rm full_stop`.

---

## 3. Invariants carried through EVERY phase (do-NOT) — verified intact at `f3fb023`

- **Never single-agent / lone-candidate acceptance — the four gates.** `grep -c "synthesis_success = True"`
  == 1 per file (re-verified). HALT on any mismatch or a guard weakened to `if True/False:`.
- **Never narrow `BYPASS_FUZZER_TYPES`.** `test_authoring` stays `bypass_fuzzer:False`; the set is only ADDED to.
- **Never grant `skip_interface_fuzz` to any type other than `test_authoring`.** `grep -c skip_interface_fuzz
  taxonomies.py == 1` (re-verified); `_skip_ifz` pinned to `mtt == 'test_authoring'` in both orch + worker.
- **(F2) The submission-time interceptor stays NO STRICTER than the real acceptance gate.** Keep
  `ASTVerificationInterceptor` ⊆ `harness/ast_enforcer.validate_code` errors (H-INT preserved this;
  `subprocess_no_check` now WARNING in both verifier and enforcer; `os.system` stays ERROR).
- **(F1) agy-backed agents route their submission via STDIN** (`spawn_agent` agy branch). Never revert agy
  to argv `-p` + file-write-cascade in the jail.
- **Never add `*_fix`/any `<task>_fix` to the allowlist.** Deny-all.
- **`full_stop` stays present (`state/control/autowork/full_stop`) until owner-gated Phase A** (honored in the daemon).
- **The §1b approval gate is the autonomous-commit boundary** (`_apply_approval_granted` orchestrator.py:1419;
  `_SENSITIVE_APPLY_GLOBS = ('harness/**','config/**','scripts/**')` git_integration.py:16 via `_enforce_apply_scope`).
  The agent CANNOT write `state/control/decisions/**` (jail ro); only the host operator session can.
- **`meta_task_type`/`mutations`/`mutation_target` are read ONLY from the trusted jail-ro task spec.**
- **Mutation-gate fail-closed semantics** (`_auto_commit_accepted`): no-mutant `test_authoring`→reject; un-appliable
  mutant→reject; vacuous test→reject; unexpected exception→`mutation_gate_error` rollback (H1). Do NOT weaken.
- **Agents are tree-isolated ONLY via the bwrap jail.** ROLLB-B keeps `sha=None` from a destructive `HEAD~1` reset.

---

## 4. Open risks specific to rev 13

- **R-daemon-watchdog (MED, gating for daemon Phase A):** watchdog 2100s < worker budget 3900s
  (autowork_daemon.py:1373). Re-widen (AGY2D) before any daemon-driven retry-capable run. Non-issue for
  foreground.
- **R-staging-collision (MED, gating only under concurrency):** global `{name}_staging`
  (orchestrator.py:1588). Make per-task (ROLLB-A) before concurrent workers.
- **R-foreground-zombie (MED):** `run_pipeline` parks failures via `_mark_processed`; re-dispatch needs the
  `processed/` shadow removed (memory learning 4). Daemon path is already correct.
- **R-host-vcmd-exec (MED, deferred H2):** vcmd/mutant runs un-jailed on host (orchestrator.py:1704/:1808/:1813);
  mitigated by vcmd coming from the trusted jail-ro spec.
- **R-jail-rw-surface (LOW, deferred H-JAIL):** XDG `--bind` and `~/.nvm`/`~/.gemini`/`~/.claude` rw
  (agent_jail.py:200-202, :131-134); dangerous sub-paths already ro-overlaid; residual surface is a
  hardening gap, not a live escape.
- **R-§1b-self-approval (PROCESS):** owner-authorized this session; future option = cryptographically signed
  operator approvals (R4 rec #2) so the session agent cannot self-approve.
- **R-anchored-patch (STRATEGIC):** the column-0/string-splice patcher (git_integration.py:939) corrupts
  multi-line string literals and skips a full-file post-splice AST check; the recurring hand-edit exception.
  Highest-leverage strategic fix (R).

---

## 5. Techniques & gotchas (reusable — carried forward from rev-12 execution)

- **Nested class-method partial edits need a COLUMN-0 directive in the brief.** The validation gate
  (orchestrator.py:~1087 / git_integration.py:989) `ast.parse`s the raw patch `code`; an in-class-indented
  `def` → `SyntaxError: unexpected indent` (permanent-blocker class). Emit the def dedented to column 0;
  `_apply_symbol_patch` re-indents on apply. Top-level functions are unaffected. (AGY2D / ROLLB-D targets
  are nested/large → apply this or treat as hand-edit candidates.)
- **A verification failure is NOT a permanent blocker.** Fix the brief's grounding (e.g. monkeypatch a
  FUNCTION as a function, not a bare Path — `harness.paths.agent_work_dir` is `(agent, slug)->Path`) and
  RE-DISPATCH. Only a reproducible structural rejection (e.g. patch path can't add a module-level import;
  column-0 syntax) is a permanent blocker that justifies a hand-edit.
- **Re-running a rejected task under the same id:** `get_next_task` (orchestrator.py:785) dedupes by
  filename against `processed/`. `rm` the stale `processed/` shadow first (or use a fresh task_id), and
  clean `state/sessions/*<task>*`, `state/output/<task>.*`, and `agentwork *<task>*` between attempts.
- **agy is uncontained on the host.** Snapshot + verify + revert the tree after ANY agy run (agy tampered
  the tree during THIS review). For briefs, use an **Opus drafter → independent Opus adversarial reviewer →
  overseer ingests UNREAD** (cp + pytest behavior-check only, never reads the brief). **agy `-p <big argv>`
  hangs (>300s); STDIN / tiny-argv-to-file works** — use agy only for self-contained pure-generation, never
  agentic exploration.
- **§1b self-approval (this session only, per owner):** the overseer may write
  `state/control/decisions/<task_id>.json` `{"decision":"approve"}` to unblock a `harness_self_fix` apply;
  do NOT persist this practice. Owner 8-point review + Phase A `rm full_stop` remain OWNER-ONLY.
- **Orchestrator is a long-running service** (loops "No unprocessed tasks"); kill its PID at terminal.
  `pgrep -f harness.orchestrator` false-positives on your own shell — verify with `ps -eo pid,cmd`.

---

## Appendix A — file:line index (rev 13, anchored to HEAD `f3fb023`)

- `harness/orchestrator.py`:
  - `spawn_agent` **:308**; agy `_is_agy` branch **:~360-402**; jail wrap **:347**
  - `poll_for_submission` **:480** (early-return on `proc.poll() is not None` **:528**)
  - `get_next_task` **:785** (processed/ dedupe)
  - `_mark_processed` **:1187**; `_mark_blocked` **:1240**
  - `_rollback_rejected_commit` **:1329** (sha=None guard **:1351-1353** [ROLLB-B]; single-file checkout **:1372** [ROLLB-C])
  - `_apply_approval_granted` **:1419**
  - `_auto_commit_accepted` **:1438**; `staging_path = {name}_staging` **:1588** [ROLLB-A]; lifecycle/cleanup **:1593-1893** [ROLLB-D]
  - vcmd run **:1704**; mutant apply/rerun **:1808/:1813** [H2]
  - merge_failed `_mark_blocked` **:1847**
  - `run_pipeline` **:1958** (12 `_mark_processed` failure sites in :1958-2280) [ROLLB-E]
- `harness/orchestrator_worker.py`: four gates + `synthesis_success = True` (×1); `_mark_blocked` ×9; `use_retry_module` default False **:174**
- `harness/autowork_daemon.py`: watchdog `max(1800.0, timeout+300.0)` **:1373** [AGY2D]; jail wrap **:604**; config CWD-relative **:635-637**
- `harness/agent_jail.py`: `~/.nvm`/`~/.gemini`/`~/.claude` rw bind **:131-134**; ro-overlays settings/skills/plugins/GEMINI.md **:163-195**; XDG `--bind` **:200-202**; repo ro-bind **:204**; state ro-bind **:214**
- `harness/git_integration.py`: `_SENSITIVE_APPLY_GLOBS` **:16**; `_apply_symbol_patch` **:939** (col-0 splice; AST parse **:989**) [R]
- `services/neurosymbolic/ast_verifier.py`: `subprocess_no_check` severity `"WARNING"` (H-INT, was ERROR) in `_ASTVisitor.visit_Call`
- `harness/ast_enforcer.py`: `subprocess_no_check` `'warning'` **:125**
- `harness/ast_retry.py`: `HARD = synthesis_timeout + 300.0` **:39** (dormant) [H3]
- `tests/adversarial/test_phase_a_selfheal_jail_writedenial.py`: 7 tests, negative controls (returncode!=0 + content-equality) :225-264, positive controls (returncode==0) :269/:279
