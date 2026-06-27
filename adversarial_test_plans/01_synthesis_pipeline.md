# Adversarial Test Plan 01 — Synthesis Pipeline & Dual-Agent Core

Author: exploration agent 1/4. Read-only audit. Tests below are PLANNED, not
written/run. A tester sub-agent executes them next session. NONE may spawn real
agy/claude; all agent execution is mocked at `subprocess.Popen` /
`run_both_agents` / `run_agent_phase` / `synthesize_with_retries` boundaries.

---

## 1. Area & scope

Modules / functions owned:

- `harness/orchestrator.py`
  - `_build_agent_command` (:162), `_build_agent_env` (:187),
    `_boost_antigravity_mcp_config` (:222), `spawn_agent` (:265),
    `kill_agent` (:309), `_path_b_outbox_fallback` (:339),
    `poll_for_submission` (:375), `run_agent_phase` (:474),
    `run_both_agents` (:497), `prepare_task_prompt` (:785 region),
    `collect_submissions` (:803), `_validate_submission` (:857),
    `_resolve_files_touched` (:1146), `_apply_approval_granted` (:~1287),
    `_auto_commit_accepted` (:~1400) incl. verification_command exec (:1481-1574),
    `_stage_inbox` (:2432), `_stage_targets` (:2496),
    `_INBOX_SOURCES_BY_MODE` (:2430).
  - run_pipeline synthesis loop + dual-agent agreement invariant at
    `synthesis_success` (:1681 init, **:1732** invariant, :1808 set).
- `harness/orchestrator_worker.py`
  - `main` (:80), per-worker timeout budgets `_compute_timeout_budgets` (:~556),
    `RECONCILE_SLACK_SECONDS` (:~555), `synthesis_success` (:127 init,
    **:173** invariant, :245 set), retry/budget loop (:178-246), BYPASS
    acceptance path (:255-309), exit codes (2=timeout, 1=rejected, 0=accepted).
- `harness/ast_retry.py` — `synthesize_with_retries` (:5).
- `harness/git_integration.py` (24h-touched apply-scope) — `_enforce_apply_scope`,
  `_matches_sensitive`, `_SENSITIVE_APPLY_GLOBS`, `commit_accepted_output`,
  `_commit_accepted_output_multi`, `_commit_accepted_output_patches`.
- `harness/paths.py` — `agent_workroot`, `agent_work_dir`.
- `harness/planner/reconciliation.py`, `cross_examination.py`,
  `harness/agent_streamer.py` (supporting; no new 24h changes, clean of markers).

---

## 2. 24h changes in this area (git show)

| sha | files | concrete change |
|-----|-------|-----------------|
| **9e0fc64** AGENT_ISOLATION (hand-edit) | orchestrator.py, git_integration.py, paths.py, autowork_daemon.py, config.yaml, hooks/_env.py, hooks/gemini/pre_tool.py, planner/blind_draft.py, webui_control.py + tests | (a) `paths.agent_workroot()` / `agent_work_dir()` put workdirs in `<repo>_agentwork` SIBLING dir (override `$JANUSMASK_AGENT_WORKROOT`). (b) `_build_agent_env` now uses `agent_work_dir(...)` for `JANUSMASK_WORK_DIR`. (c) `spawn_agent` passes `cwd=str(work_dir)` to `Popen` and resolves `{WORK_DIR}` in the prompt. (d) `prepare_task_prompt` rewritten to read `{WORK_DIR}/inbox/task.json` + `{WORK_DIR}/inbox/targets/<rel>` (was `{STATE_DIR}/tasks/current_task_<id>.json`). (e) `_stage_inbox` for synthesis calls new `_stage_targets` to copy each resolved files_touched into `inbox/targets/<rel>` (repo-relative-to guard). (f) git_integration: new `_enforce_apply_scope(rel_strs, allowed_files, meta_task_type, approval_ok)` + `_matches_sensitive` + `_SENSITIVE_APPLY_GLOBS=('harness/**','config/**','scripts/**')`; `commit_accepted_output` + `_commit_accepted_output_multi` + `_commit_accepted_output_patches` gained `*, allowed_files, meta_task_type, approval_ok` kwargs and call the scope check before committing each rel. (g) `_auto_commit_accepted` computes `_mtt` + `_apply_approval_granted(state_dir, task_id)` and passes `allowed_files=set(files_touched)`. (h) new `_apply_approval_granted` reads `state/control/decisions/<task_id>.json`, returns True only when `decision` in {approve,approved}. (i) `_boost_antigravity_mcp_config` de-obfuscated `"HO"+"ME"` -> `os.environ["HOME"]`. |
| **8dac6e1** RECONCILE_TIMEOUT_BUDGETS (hand-edit) | orchestrator_worker.py, tests/test_orchestrator_worker_timeout_budgets.py | Removed hardcoded `HARD_TIMEOUT_SECONDS=900`/`SYNTHESIS_WINDOW_SECONDS=600` module constants; added `RECONCILE_SLACK_SECONDS=300.0` and pure `_compute_timeout_budgets(config) -> (timeout+slack, timeout)`; `main()` assigns both as **locals** derived from config at :105. Default 600 when unconfigured. |
| **3ec31ab** ORCHESTRATOR_TIMEOUT_FIXES | autowork_daemon.py, orchestrator_worker.py | Worker: captured `worker_start_monotonic` at :90; per-retry budget guard (:179-185) exits 2 `insufficient_time_for_retry` when `remaining < window`; double-timeout branch (:195-200) now EXITS 2 `both_agents_timed_out` instead of retrying; single-agent-missing branch retries with augmented prompt; `None`-comparison hardened (`is None` not falsy). Daemon: `start_new_session=True` on worker Popen, `_kill_process_group` SIGKILLs whole pgroup on watchdog. |
| **28db488** SYNTHESIS_TIMEOUT_UPGRADE | config.yaml | `synthesis.timeout_seconds` 600 -> 1200. |
| **12b61d5** WATCHDOG_TIMEOUT_INCREASE | autowork_daemon.py | Daemon sequential watchdog now `max(1800.0, timeout_seconds+300.0)` (was hardcoded 900s). |

Config state at HEAD (`harness/config.yaml`): `timeout_seconds: 1200`,
`max_ast_retries: 3`, `antigravity_mode: false`, `use_retry_module` ABSENT
(=> defaults False), `active_agents` present, `claude_fallback` agent defined.

---

## 3. Architecture map & invariants

Call paths (mocked entry points in **bold**):

```
autowork_daemon._iteration
  -> Popen([python,-m,harness.orchestrator_worker, --state-dir, --task-id])  (start_new_session=True; watchdog max(1800,timeout+300))
       -> orchestrator_worker.main()                       [worker_start_monotonic @ :90]
            HARD,WINDOW = _compute_timeout_budgets(config)   [:105 -> (1500,1200) at HEAD]
            if use_retry_module:                            [FALSE at HEAD]
                synthesize_with_retries(agent, ...) x2  (ast_retry.py; NO budget check inside)
            else:                                           [ACTIVE path at HEAD]
                while ast_retries < max_ast_retries:
                    budget guard (:179) ... 
                    **orch.run_both_agents(a_prompt,b_prompt,...)**
                      -> run_agent_phase(agent) -> **spawn_agent** -> Popen(cwd=workdir) -> poll_for_submission
                    synthesis_success = a_code AND b_code AND a_valid AND b_valid   [INVARIANT :173/:245]
            if mtt in BYPASS_FUZZER_TYPES: smoke/embedded/narrow on agent_a_code only -> _auto_commit_accepted
            else: fuzz_from_task(a_code,b_code) -> equivalent? -> _auto_commit_accepted
                 -> git_integration.commit_accepted_output(..., allowed_files, meta_task_type, approval_ok)
                      -> _enforce_apply_scope() per rel  [APPLY-SCOPE INVARIANT]
                 -> verification_command via bash inside staging worktree; exit!=0 => rollback+reject
```

`run_pipeline` in orchestrator.py mirrors the worker (lines 1681-1949) for the
in-process (non-daemon) flow; same invariant at :1732.

### Invariants that MUST hold (tests must NOT weaken these)

1. **Dual-agent agreement (orchestrator.py:1732, worker:173/245):**
   `synthesis_success` is True ONLY if BOTH agents produced non-empty code AND
   both validated. If either is None/empty/invalid, must be False -> reject.
2. **Fuzzer equivalence (non-bypass):** acceptance requires
   `fuzz_result.equivalent` after differential fuzzing of a_code vs b_code.
3. **BYPASS only for `mtt in BYPASS_FUZZER_TYPES`**; bypass still requires both
   agents submitted (invariant #1) PLUS smoke+embedded+narrow gates on a_code
   (unless mtt in SKIP_SMOKE_GATE_TYPES).
4. **Apply-scope (git_integration._enforce_apply_scope):** committed rel-path
   must be a member of resolved files_touched; `harness/**`,`config/**`,`scripts/**`
   require `meta_task_type=='harness_self_fix'` AND `approval_ok`.
5. **CWD isolation:** every agent Popen launches with `cwd` under
   `agent_workroot()` which is OUTSIDE `PROJECT_ROOT`.
6. **Verification gate:** acceptance requires a non-empty `verification_command`
   that exits 0 inside the staging worktree.
7. **Worker timeout budget monotonic:** inner HARD = window+slack must stay
   `< daemon watchdog max(1800,timeout+300)` for all configured timeouts <=1500.

---

## 4. Adversarial test plan (enumerated)

> Mocking primitives reused throughout:
> - `monkeypatch.setattr(orch, 'run_both_agents', lambda *a, **k: (CODE_A, CODE_B))`
>   to drive the worker/pipeline without spawning.
> - `monkeypatch.setattr(orch, 'run_agent_phase', fake)` to drive `run_both_agents`.
> - `monkeypatch.setattr(orchestrator.subprocess, 'Popen', FakePopen)` where a
>   FakePopen records `cwd=`/`env=`/`cmd` kwargs, exposes `.pid`, `.poll()->0`,
>   `.returncode`, `.wait()`, `.stdout`/`.stderr` file-likes, and never execs.
> - `monkeypatch.setenv('JANUSMASK_AGENT_WORKROOT', str(tmp_path/'wr'))` so
>   isolation tests don't pollute the real sibling dir.
> - For commit tests, build a real throwaway git repo in `tmp_path` (or reuse
>   the `tmp_repo` fixture pattern in `tests/adversarial/test_agent_isolation.py`).

### T1 — Dual-agent invariant: one agent empty string must NOT accept
- Target: `orchestrator_worker.main` (:173/:201) and `orchestrator.run_pipeline` (:1732/:1754).
- Scenario: mock `run_both_agents` to return `("def f():...valid", "")` (b empty
  string, which is falsy but NOT None). Drive the worker else-branch.
- Expected: single-agent-missing branch (:201) increments retries and re-prompts;
  if all retries return the same, `synthesis_success` stays False, worker exits 1
  `synthesis_or_ast_failed`. NEVER accept on one agent.
- Suspected bug: `agent_a_code is None and agent_b_code is None` (:195) only
  matches None+None; the empty-string case falls to `not a or not b` (:201)
  which retries forever-bounded — verify it does NOT silently coerce to accept,
  and that `synthesis_success = bool(... and a_code and b_code)` (:173 is only on
  the retry-module path) — confirm the else-branch never sets success without both.
- Assert: exit_code == 1; phase rejected; commit helper never called (patch
  `orch._auto_commit_accepted` to a tracking stub, assert not called).
- Mock: yes (run_both_agents). No real spawn.

### T2 — Dual-agent invariant: both None double-timeout exits 2, no retry
- Target: `orchestrator_worker.main` (:195-200).
- Scenario: mock `run_both_agents` -> `(None, None)` on first call. Provide a
  spy on `run_both_agents` call count.
- Expected: emits `double_timeout`, prints `both_agents_timed_out`, returns 2 on
  the FIRST iteration (no second run_both_agents call).
- Suspected incompleteness: the `ast_retries += 1` at :196 is immediately
  followed by `return 2`, so the increment is **dead** and the augmented retry
  prompt that the old code set for double-timeout is gone. Assert run_both_agents
  called exactly once and exit==2. (Documents the dead increment; do not assert it
  retries.)
- Mock: yes.

### T3 — Per-retry budget guard fires only on retries, and is currently unreachable on double-timeout
- Target: `orchestrator_worker.main` budget guard (:179-185) + `_compute_timeout_budgets`.
- Scenario A (reachable): set config timeout small (e.g. monkeypatch
  `_compute_timeout_budgets` to return `(hard=1.0, window=10.0)`), force
  `worker_start_monotonic` far in the past by patching `time.monotonic`, and make
  `run_both_agents` return `(code_a, None)` (single-missing) so the loop reaches a
  2nd iteration (ast_retries>0). Expect exit 2 `insufficient_time_for_retry`.
- Scenario B (dead-path proof): because both-None exits immediately (T2), show the
  budget guard can ONLY be entered via the single-missing or AST-invalid retry
  branches, never via double-timeout. Assert the guard is skipped when ast_retries==0.
- Suspected incompleteness: budget guard never runs on attempt 0 by design, and
  double-timeout short-circuits before any retry — so the only way to consume
  budget across retries is repeated single-agent-missing / AST-invalid loops.
- Mock: yes. No real timing dependence beyond patched `time.monotonic`.

### T4 — use_retry_module path ignores the per-worker timeout budget entirely
- Target: `orchestrator_worker.main` (:142-173) vs `ast_retry.synthesize_with_retries`.
- Scenario: set `config['synthesis']['use_retry_module']=True`; mock
  `synthesize_with_retries` to record the args it received.
- Expected/asserted: `synthesize_with_retries` receives NO budget params and its
  body (ast_retry.py:30-48) has NO `worker_start_monotonic`/budget check — so a
  worker on the retry-module path can run `max_ast_retries` full synthesis windows
  with no insufficient_time_for_retry guard. This is a GAP: the RECONCILE budget
  work only protects the legacy inline else-branch.
- Assert: inspect `ast_retry.synthesize_with_retries` source contains no
  `monotonic`/`budget`/`HARD_TIMEOUT` token (string assertion on the function
  source via `inspect.getsource`); document that HEAD config has use_retry_module
  False so the protection is active by default, but flipping the config silently
  removes it.
- Mock: yes.

### T5 — spawn_agent launches with cwd OUTSIDE the repo
- Target: `orchestrator.spawn_agent` (:298) + `_build_agent_env` (:216).
- Scenario: set `$JANUSMASK_AGENT_WORKROOT=tmp`, patch `subprocess.Popen` with a
  FakePopen capturing kwargs, patch `start_stream_threads`/`control_gate.record_agent_pid`
  to no-ops. Call `spawn_agent('claude', prompt, {'state_dir':...})`.
- Expected: captured `cwd` startswith `agent_workroot()` and is NOT under
  `PROJECT_ROOT`; `env['JANUSMASK_WORK_DIR']` == that cwd.
- Suspected regression risk: someone reverts cwd= or work_dir back into state_dir.
  (Partially covered by existing test_agent_isolation.py:72 — extend to assert the
  prompt `{WORK_DIR}` token was substituted in resolved_prompt passed to
  `_build_agent_command`.)
- Mock: yes (Popen). Must NOT exec.

### T6 — prepare_task_prompt points agents at per-spawn inbox, never repo paths
- Target: `orchestrator.prepare_task_prompt` (:785).
- Scenario: call with a task dict; assert the returned prompt contains
  `{WORK_DIR}/inbox/task.json` and `{WORK_DIR}/inbox/targets/` and contains NEITHER
  `{STATE_DIR}/tasks` NOR `current_task_<id>.json`-style repo path.
- Multi-file variant: task with 2 files_touched -> prompt contains
  `inbox/targets/<rel>` guidance in the MANIFEST block. partial_edit / bypass mtt
  variant -> PARTIAL-EDIT block references `inbox/targets/<rel>`.
- Suspected incompleteness: `_INBOX_SOURCES_BY_MODE['synthesis']` stages to
  `inbox/task.json` but `_stage_inbox` prefers `tasks/current_task_<id>.json`
  source first (:2471) then `tasks/current_task.json`; prompt hardcodes
  `inbox/task.json` dest — verify the staged DEST filename == prompt expectation
  (`task.json`) and matches `hooks/_env._INBOX_EXPECTATIONS['synthesis']==('task.json',)`.
- Mock: none (pure string function).

### T7 — _stage_targets only copies files inside the repo (path-escape guard)
- Target: `orchestrator._stage_targets` (:2496) / `_stage_inbox` synthesis branch.
- Scenario: craft a task.json whose `files_touched` includes `../../etc/passwd`,
  an absolute `/etc/hostname`, and a symlink rel that resolves outside repo_root.
  Run `_stage_inbox(work_dir, 'synthesis', state_dir)` with a tmp state_dir whose
  parent is a tmp "repo".
- Expected: only in-repo regular files are copied into `inbox/targets/<rel>`;
  the `src.relative_to(repo_root)` guard (:2523) skips escapes; function never
  raises (best-effort).
- Suspected incompleteness: `repo_root = state_path.resolve().parent` — if
  state_dir is itself relocated (tests pass tmp dirs), repo_root may be wrong;
  also `_resolve_files_touched` exception falls back to raw `files_touched`
  (:2514) — verify the escape guard still applies to that fallback list.
- Mock: monkeypatch `_resolve_files_touched` to return the crafted list.

### T8 — apply-scope membership: commit of a non-files_touched rel is rejected
- Target: `git_integration._enforce_apply_scope` via `_commit_accepted_output_multi`
  and `_commit_accepted_output_patches` (the manifest/patches sidecar paths).
- Scenario: build a real tmp git repo; write a `.files.json` sidecar mapping
  `{"a/in.py": "...", "b/sneaky.py": "..."}` but pass `allowed_files={"a/in.py"}`.
- Expected: `_commit_accepted_output_multi` returns `committed=False` + `error`
  containing "apply-path scope violation" and "not a member"; NO commit created.
- Suspected gap: existing test_agent_isolation.py only unit-tests
  `_enforce_apply_scope` and the single-file `commit_accepted_output`; the
  multi-file (:801) and patches (:1087) call sites are NOT independently covered.
  Probe each. Also probe membership when `allowed_files=None` (opt-out) still
  applies the sensitive-path gate.
- Mock: none for the helper; real git for the commit path (or assert at the
  `_enforce_apply_scope` return before any git op by patching `_apply_file_to_target`).

### T9 — apply-scope sensitive path: harness/** blocked without approval, allowed with it
- Target: `_enforce_apply_scope` + `_apply_approval_granted` + `_matches_sensitive`.
- Scenario: rel=`harness/orchestrator.py`, `allowed_files={"harness/orchestrator.py"}`.
  (a) meta_task_type=None -> reject. (b) `harness_self_fix` + approval_ok=False ->
  reject. (c) `harness_self_fix` + approval_ok=True -> pass. Plus `config/x.yaml`,
  `scripts/y.sh`, and a `harness` exact-dir vs `harnessx/z.py` (must NOT match —
  prefix-boundary test on `_matches_sensitive`).
- Suspected bug to probe: `_matches_sensitive` treats `harness/**` via
  `p == base or p.startswith(base+'/')`; assert `harnessextra/a.py` does NOT match
  (no false positive) and `harness` (the bare dir) DOES match.
- `_apply_approval_granted`: corrupt JSON, missing file, `decision:"deny"`,
  `decision:"APPROVE"` (case), non-dict top-level -> only approve/approved => True.
- Mock: none (pure). For approval, write decision file under
  `state/control/decisions/<id>.json`.

### T10 — verification_command failure rolls back and rejects (no orphan commit)
- Target: `_auto_commit_accepted` verification block (:1480-1574).
- Scenario: real tmp repo; mock `_resolve_verification_command` to return
  `"false"` (exit 1); ensure commit lands then verify fails.
- Expected: `_rollback_rejected_commit` + `remove_staging_worktree` called,
  function returns False, impl_progress ledger row `verification_failed`.
- Empty-vcmd variant: vcmd "" or None -> `verification_missing`, rollback, False.
- Unscoped-pytest variant: vcmd `"pytest"` -> rewritten to append scoped test
  files via `get_relevant_test_files` (:1528-1535); assert the rewrite happens
  and a missing-test fallback to `tests/test_import.py`.
- Suspected gap: the 600s `subprocess.run(..., timeout=600)` is hardcoded and NOT
  derived from `synthesis.timeout_seconds` — at timeout_seconds=1200 a long verify
  can be killed at 600s and recorded as exit 124. Probe the hardcoded 600 and
  document the mismatch with the raised synthesis timeout.
- Mock: `_resolve_verification_command`; real git or patch git_integration calls.

### T11 — claude_fallback path preserves the dual-agent invariant
- Target: `run_both_agents` (:511-547).
- Scenario: antigravity_mode False (HEAD); mock `run_agent_phase` so claude->None,
  claude_fallback->"codeA", gemini->"codeB".
- Expected: returns ("codeA","codeB") — fallback substitutes for claude_a but
  gemini_b is still independently produced; invariant (#1) intact (two distinct
  submissions still get fuzzed). Assert claude_fallback is invoked exactly once
  and only when agent_a is 'claude' and None.
- Negative: claude->None AND claude_fallback->None -> returns (None, codeB) ->
  downstream synthesis_success False. Assert NOT accepted.
- Suspected gap: fallback only triggers for `agent_a == 'claude'`; if active_agents
  reorders so claude is agent_b, the fallback never fires (probe this asymmetry).
- Mock: yes.

### T12 — poll_for_submission interceptor-deny and path-B outbox fallback
- Target: `poll_for_submission` (:375-472) + `_path_b_outbox_fallback` (:339).
- Scenario: FakePopen alive then exits; no sessions/ submission file but an
  outbox `submission.py` with valid Python exists -> fallback promotes it.
  Variant: interceptor `pre_tool_use` returns `{'decision':'deny'}` -> code dropped,
  submission file unlinked, poll continues/returns None.
  Variant: outbox content is non-py target (files_touched[0] not .py) -> skips
  ast.parse and still promotes (verify the target_is_py branch).
- Suspected gap: watchdog at :460 uses `status_updated_at_epoch` from state; if a
  prior task left a stale running status with old epoch, a brand-new poll could
  immediately self-timeout. Probe: state has agent_status 'running' with
  updated_at = now - timeout - 1 -> returns None even though FakePopen is alive.
- Mock: patch interceptor registry; FakePopen; tmp state_dir.

### T13 — agent_workroot honors override and is repo-derived, not state-dir-derived
- Target: `paths.agent_workroot` / `agent_work_dir`.
- Scenario: (a) with `$JANUSMASK_AGENT_WORKROOT` set -> returns resolved abs path,
  NOT expanduser'd (pass a `~`-containing value, assert literal). (b) unset ->
  `PROJECT_ROOT.parent / f"{PROJECT_ROOT.name}_agentwork"`. (c) called from a
  per-agent planning session_dir as state_dir must NOT relocate the root inside
  the repo (the doc warns about the `_PerAgentConfig` trick) — but workroot ignores
  state_dir entirely, so assert it's invariant to any state_dir argument (there is
  none — confirm the signature takes none).
- Mock: monkeypatch env only.

### T14 — kill_agent reaps the whole process group
- Target: `kill_agent` (:309).
- Scenario: FakePopen with `poll()->None` then after SIGTERM `poll()->0`; patch
  `os.killpg`/`os.getpgid` to spies. Assert SIGTERM to pgid first, SIGKILL only on
  `wait` TimeoutExpired. Variant: `os.getpgid` raises ProcessLookupError ->
  falls back to `proc.terminate()`.
- Mock: yes; never touch a real pid.

---

## 5. Incompleteness & gap candidates (file:line)

- **orchestrator_worker.py:196** — `ast_retries += 1` immediately before
  `return exit_code` in the double-timeout branch: DEAD increment. The old
  double-timeout retry-with-augmented-prompt behavior was removed; double timeout
  now hard-exits 2 on the first occurrence. (Documented intentional by 3ec31ab,
  but the increment is vestigial.)
- **orchestrator_worker.py:179-185 + ast_retry.py:30-48** — per-worker timeout
  budget guard exists ONLY in the legacy inline else-branch. The
  `use_retry_module=True` path (`synthesize_with_retries`) has NO budget check, so
  the RECONCILE_TIMEOUT_BUDGETS protection silently vanishes if that config flag
  is flipped. HALF-WIRED feature.
- **orchestrator.py:1543 / 1481-1574** — `verification_command` subprocess timeout
  hardcoded to `timeout=600` while `synthesis.timeout_seconds` was raised to 1200.
  A legitimate >600s verification is killed (exit 124) and rejected. Hardcoded
  constant not reconciled with the SYNTHESIS_TIMEOUT_UPGRADE.
- **orchestrator.py:2536-2541** — stray module-level string-literal expression
  statements (leftover task-prompt/brief text from prior AST merges) and a
  trailing `import fcntl` + `from harness.ast_enforcer import Violation` after the
  `_stage_targets` def. Dead no-op statements; cosmetic but indicates AST-merge
  residue at module scope.
- **orchestrator.py:2468-2471** — `_stage_inbox` synthesis prefers
  `tasks/current_task_<task_id>.json` then `tasks/current_task.json`; the prompt
  and `_INBOX_EXPECTATIONS` both key on dest `task.json`. If neither candidate
  exists (e.g. worker wrote only `current_task_spec_path`), `_stage_targets` is
  never reached and `inbox/targets/` is empty — agent then has no on-disk target
  context after CWD relocation. Potential silent-empty-context path; verify the
  candidate list always includes the actual worker-written spec path.
- **orchestrator.py:_stage_targets:2514** — on `_resolve_files_touched` exception,
  falls back to raw `task.get('files_touched')`; the escape guard still applies but
  the parent-chain resolution (decomposed child tasks) is lost, so a child task's
  real targets may not be staged. Degraded-mode behavior, untested.
- **run_both_agents:514/538** — claude_fallback ONLY fires when `agent_a=='claude'`.
  If `active_agents` is reordered, the fallback is unreachable for the non-first
  slot. Asymmetric, config-fragile.
- **git_integration `_enforce_apply_scope`** — `allowed_files=None` opt-out
  (used by low-level callers/tests) disables the membership check while keeping the
  sensitive-path gate. Confirm no production caller ever passes None for a
  non-harness target (would allow committing arbitrary in-repo rels).
- **poll_for_submission:460** — watchdog self-timeout keys on
  `status_updated_at_epoch` from shared state; a stale 'running' status with an old
  epoch could immediately time out a fresh poll. State-coupling hazard.

(NOT planned — known pre-existing failures, excluded per brief: the 5×
`test_escalate_to_autobrief_*` and 2×
`test_orchestrator_timeout_fixes.py::test_*_exits_with_status_2_use_retry_module`.)

---

## 6. Runbook

Suggested new test file(s):
- `tests/adversarial/test_synthesis_dual_agent_invariant.py` — T1, T2, T11.
- `tests/adversarial/test_worker_timeout_budget_paths.py` — T3, T4.
- `tests/adversarial/test_spawn_cwd_and_prompt_isolation.py` — T5, T6, T13
  (extend, don't duplicate, `test_agent_isolation.py` / `test_orchestrator_parallel_prompt_isolation.py`).
- `tests/adversarial/test_stage_targets_escape.py` — T7.
- `tests/adversarial/test_apply_scope_callsites.py` — T8, T9.
- `tests/adversarial/test_verification_gate_rollback.py` — T10.
- `tests/adversarial/test_poll_submission_paths.py` — T12.
- `tests/adversarial/test_kill_agent_pgroup.py` — T14.

Invocations (venv Python 3.13):
```
.venv/bin/python -m pytest tests/adversarial/test_synthesis_dual_agent_invariant.py -q
.venv/bin/python -m pytest tests/adversarial/test_worker_timeout_budget_paths.py -q
.venv/bin/python -m pytest tests/adversarial/test_spawn_cwd_and_prompt_isolation.py -q
.venv/bin/python -m pytest tests/adversarial/test_stage_targets_escape.py tests/adversarial/test_apply_scope_callsites.py -q
.venv/bin/python -m pytest tests/adversarial/test_verification_gate_rollback.py tests/adversarial/test_poll_submission_paths.py tests/adversarial/test_kill_agent_pgroup.py -q
# regression sanity on the 24h-touched in-area tests (must stay green):
.venv/bin/python -m pytest tests/test_orchestrator_worker_timeout_budgets.py tests/adversarial/test_agent_isolation.py tests/adversarial/test_orchestrator_parallel_prompt_isolation.py -q
```

Mocking notes (HARD constraint — no real agy/claude):
- ALWAYS set `JANUSMASK_AGENT_WORKROOT` to a tmp dir before any spawn-touching test.
- Patch `harness.orchestrator.subprocess.Popen` with a FakePopen that records
  `cwd`/`env`/`cmd`, returns a fixed pid, `poll()`/`returncode`/`wait()`/
  `stdout`/`stderr`; it must NEVER actually launch a process.
- Patch `start_stream_threads`, `control_gate.record_agent_pid`,
  `interceptor_registry.*`, and `_boost_antigravity_mcp_config` to no-ops.
- For invariant/loop tests, mock at the higher `run_both_agents` /
  `run_agent_phase` / `synthesize_with_retries` seam — cheaper and spawn-free.
- For commit/scope tests use a throwaway `git init` repo in `tmp_path` (mirror the
  `tmp_repo` fixture in `tests/adversarial/test_agent_isolation.py`), or assert at
  the `_enforce_apply_scope` boundary by patching `_apply_file_to_target`.
- Do NOT weaken invariants #1-#6; do NOT add a `mtt` to BYPASS_FUZZER_TYPES; do
  NOT lift full_stop / autowork.enabled / allowlist safe states.
