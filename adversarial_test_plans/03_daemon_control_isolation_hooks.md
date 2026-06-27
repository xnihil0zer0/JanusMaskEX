# 03 — Adversarial Test Plan: Autowork Daemon, Control Gate, Agent Isolation & Hooks

Exploration agent 3 of 4. Read-only audit. A tester sub-agent executes this plan next
session. All planned tests MUST mock `subprocess.Popen` (NO real agy/claude) and pin
`JANUSMASK_AGENT_WORKROOT` to a tmp dir. Safe states (`full_stop=halted`,
`autowork.enabled` absent/false, allowlist deny-all) must remain untouched.

---

## 1. Area & scope

Functional area: the autowork control plane and the 24h-old AGENT_ISOLATION barrier.

In scope (files):
- `harness/autowork_daemon.py` — dispatch loop, `_spawn_worker` (`:768`), the two
  self-heal spawn paths `_escalate_to_autobrief` (`:563`) and `_escalate_inactivity`
  (`:1611`), the degenerate-escalation guard (`:584`, `:1619`), `_check_inactivity_watchdog`
  (`:1734`), `_retry_blocked_tasks` (`:687`), `_get_errors_for_task` (`:499`),
  `_emit_telemetry` (`:142`), `_parallel_cap` (`:68`).
- `harness/control_gate.py` — `require_approval_for`, `await_decision`, `check_pause`,
  `decisions_dir`, `record_agent_pid`.
- `harness/paths.py` — `agent_workroot()` / `agent_work_dir()` (the isolation root).
- `harness/orchestrator.py` — `spawn_agent` cwd (`:294`-`:297`), `_build_agent_env`
  (`:210`), `_apply_approval_granted` (`:1287`), `_auto_commit_accepted` scope wiring
  (`:1461`-`:1475`), `_stage_inbox`/`_stage_targets` (`:2486`+).
- `harness/git_integration.py` — `_enforce_apply_scope`, `_matches_sensitive`,
  `commit_accepted_output` + the multi/patches commit paths (§1b apply gate).
- `harness/hooks/_env.py` — `_work_dir` outside-repo fallback.
- `harness/hooks/gemini/pre_tool.py` — `_SHELL_ALLOW`, `_decide_shell`,
  `_read_allowed_roots`, `_decide_write_or_replace`.

Out of scope / do NOT re-flag (fail on clean HEAD f1a746b):
- 5× `test_escalate_to_autobrief_*` in `tests/test_autowork_escalation.py` and
  `tests/adversarial/test_autowork_self_healing.py` (broken by the degenerate guard +
  their `mock_open`).
- 2× `tests/...test_orchestrator_timeout_fixes.py::test_*_exits_with_status_2_use_retry_module`.

---

## 2. 24h changes (shas / files / what changed)

### `9e0fc64` — AGENT_ISOLATION: sanctioned hand-edit (24h ago) — the dominant change
Closes the agy-rogue-edit incident (agy ran with CWD=repo, hook gate never loaded, could
edit `harness/` + git-commit out of band). Touched (logic files only):
- **`harness/paths.py`**: new `agent_workroot()` → `JANUSMASK_AGENT_WORKROOT` override
  (absolute, no `expanduser`) else `PROJECT_ROOT.parent / "<repo>_agentwork"` (sibling,
  OUTSIDE repo). Anchored on `PROJECT_ROOT` (from `__file__`), deliberately NOT on a
  caller-supplied `state_dir` (planning passes per-agent session dirs as `state_dir`).
  New `agent_work_dir(agent, slug)`.
- **`harness/orchestrator.py`**:
  - `_build_agent_env` workdir now `agent_work_dir(...)` not `state_dir/workdirs/...`.
  - `spawn_agent` `Popen(..., cwd=str(Path(env['JANUSMASK_WORK_DIR'])))` (was no cwd).
  - `_boost_antigravity_mcp_config` de-obfuscated `"HO"+"ME"` → `os.environ["HOME"]`.
  - `prepare_task_prompt` reads spec from `{WORK_DIR}/inbox/task.json` + targets staged
    under `{WORK_DIR}/inbox/targets/<rel>` (was `{STATE_DIR}/tasks/current_task_<id>.json`);
    `{WORK_DIR}` token added to `resolved_prompt`.
  - `_apply_approval_granted(state_dir, task_id)` NEW — reads
    `state/control/decisions/<task_id>.json`, True iff `decision ∈ {approve, approved}`.
  - `_auto_commit_accepted` passes `allowed_files=set(files_touched)`,
    `meta_task_type`, `approval_ok` into `commit_accepted_output`.
  - `_stage_inbox`/`_stage_targets` NEW — synthesis stages current target bytes into
    `inbox/targets/<rel>` (best-effort, never copies from outside repo).
- **`harness/git_integration.py`** (§1b apply gate, independent of CWD): new
  `_SENSITIVE_APPLY_GLOBS = ('harness/**','config/**','scripts/**')`, `_matches_sensitive`,
  `_enforce_apply_scope(rel_strs, *, allowed_files, meta_task_type, approval_ok)`. Wired
  into all 3 commit paths (`commit_accepted_output`, `_commit_accepted_output_multi`,
  `_commit_accepted_output_patches`). Two constraints: (a) **membership** — every rel-path
  must be in `files_touched` (skipped if `allowed_files is None`); (b) **sensitive** — a
  `harness/**|config/**|scripts/**` path is rejected unless
  `meta_task_type=='harness_self_fix' AND approval_ok`.
- **`harness/autowork_daemon.py`**: both self-heal spawns relocated to
  `agent_work_dir(...)` + `Popen(..., cwd=str(work_dir))`; prompts scrubbed of
  repo/allowlist/git writes (write only to `{OUTBOX_PATH}`); `_get_errors_for_task` reads
  error reports from `agent_workroot()` not the dead `state_dir/workdirs`.
- **`harness/hooks/_env.py`**: `_work_dir` fallback (when `JANUSMASK_WORK_DIR` unset)
  now `agent_work_dir(a, sid)` not `state_dir/workdirs/<a>/<sid>`.
- **`harness/hooks/gemini/pre_tool.py`**: `_SHELL_ALLOW` shrunk to
  `[pytest, python -m pytest, mkdir, touch]` (dropped tee/cp/mv/ln/cat<<EOF/chmod/rm and
  python -c / sandbox.py).
- Tests added: `tests/adversarial/test_agent_isolation.py` (10 cases — see §3 coverage).

### `1a30972` — GUARD_DEGENERATE_ESCALATION (pipeline-integrated)
- `_escalate_to_autobrief` (`:584`): skip when task JSON missing OR
  (empty objective AND no files_touched AND no errors); emits `skip_degenerate_escalation`
  telemetry with reason `missing_task_json` / `empty_objective_files_no_errors`.
- `_escalate_inactivity` (`:1619`): skip when NO actionable work
  (`_has_allowlisted OR _has_queued OR _has_live_blocked` all false); emits
  `skip_degenerate_escalation` reason `no_actionable_work`.

Supporting prior shas (context): `6a42fc7` AUTOWORK_DAEMON_SAFEGUARDS (dispatch circuit
breaker + watchdog), `11551b0`/`12b61d5` watchdog timeout config, `65bd045`
loop-spin/cmdline-length fix.

---

## 3. Architecture map (from codebase-memory-mcp + source read)

### Dispatch + spawn topology (4 spawn sites)
1. **Worker dispatch** — `_spawn_worker` (`:768`) `Popen([python, -m, harness.orchestrator_worker, --state-dir, --task-id])`. **NO `cwd=`** — but the worker is the harness itself (trusted), not an agent; the agent is spawned downstream by `orchestrator.spawn_agent`.
2. **Agent spawn** — `orchestrator.spawn_agent` (`:294`) `Popen(cmd, ..., start_new_session=True, cwd=<WORK_DIR>)`. Builds env via `_build_agent_env` → workdir under `agent_workroot()`.
3. **Retry-budget self-heal** — `_escalate_to_autobrief` (`:683`) `Popen(cmd, env, cwd=work_dir)`.
4. **Inactivity self-heal** — `_escalate_inactivity` (`:1730`) `Popen(cmd, env, cwd=work_dir)`.

`_check_inactivity_watchdog` (`:1734`): if `has_unfinished` backlog AND no agent-level
ledger event for >1200s → write `inactivity_escalated.json` marker → call
`_escalate_inactivity`. `_retry_blocked_tasks` (`:735`) calls `_escalate_to_autobrief` when
a blocked task exhausts `max_attempts`.

### The isolation barrier model (3 layers — NOT a jail)
- **Layer A (CWD relocation, §3.1/§3.2)**: agents launch with `cwd=<repo>_agentwork/...`.
  Stops `git` `.git` auto-discovery from CWD and stops bare *relative* repo paths from
  resolving. Explicitly **NOT a filesystem jail** — an agent can still `open()` an
  absolute repo path. Necessary-but-not-sufficient.
- **Layer B (§1b apply-path gate, `git_integration._enforce_apply_scope`)**: the
  authoritative barrier at the submission→commit boundary. Independent of CWD. Rejects
  any committed path outside `files_touched`, and any `harness/**|config/**|scripts/**`
  write unless `harness_self_fix + operator approval decision file`.
- **Layer C (hook gate, gemini/pre_tool `_SHELL_ALLOW`)**: defense-for-the-future. **The
  gate never loads for bare `agy`** — config.yaml wires gemini/agy as
  `${PROJECT_ROOT}/.agents/agy/agy -p --sandbox` (no `--settings`/BeforeTool hook), so
  `_SHELL_ALLOW` is INERT for the actual production agent. It only fires for an agent
  invoked with `config/gemini_settings.json` (BeforeTool → `harness.hooks.gemini.pre_tool`).
  The pre_tool docstring/comment (§3.3) admits this.

### Control gate
`await_decision` returns `'auto'` immediately when phase ∉ `require_approval` (default
no-op). `check_pause` reads `state/control/orchestrator.flag`, fail-open to not-paused.
`_apply_approval_granted` (orchestrator) reuses the SAME `decisions/<id>.json` channel.

---

## 4. Adversarial test plan (enumerated)

> Common fixtures: `monkeypatch.setenv("JANUSMASK_AGENT_WORKROOT", str(tmp_path/"work"))`;
> a `_FakePopen` that records `args`/`kwargs` and returns an object with `.pid`,
> `._work_dir` assignable, `.poll`/`.wait` no-ops; `monkeypatch.setattr(<module>.subprocess,
> "Popen", FakePopen)`. NEVER let a real Popen run.

### Group 1 — cwd-outside-repo on every spawn site

**TC-1.1 — worker dispatch leaks no cwd into the agent tree (documentation/guard)**
- Target: `autowork_daemon._spawn_worker` (`:768`).
- Scenario: call `_spawn_worker(state_dir, "T1")` with mocked Popen; inspect kwargs.
- Expected: `_spawn_worker` passes NO `cwd` (it spawns the trusted harness worker, which
  itself relocates the agent via `spawn_agent`). The test ASSERTS the documented
  contract: `"cwd" not in kwargs` AND that the spawned argv is `orchestrator_worker`
  (i.e. confirm the daemon never directly launches an agent CLI without going through
  `spawn_agent`). Suspected incompleteness: this is the one spawn site with no cwd; verify
  it cannot be reached with an agent command.
- Assertion: inspect captured `Popen` call argv + kwargs.

**TC-1.2 — `agent_workroot()` honors the env override and is outside repo**
- Target: `paths.agent_workroot` / `agent_work_dir`.
- Scenario: with `JANUSMASK_AGENT_WORKROOT` set to tmp; and a second sub-case with it
  UNSET (assert default `PROJECT_ROOT.parent/"<name>_agentwork"`, still outside repo).
  Adversarial: set override to a RELATIVE path → assert `.resolve()` still lands it, and
  set it to a path *inside* the repo → assert the helper does NOT reject it (documents that
  the override is operator-trusted; a misconfig re-opens the relative-path hole).
- Expected: returns the resolved override; default is the sibling dir.
- Suspected incompleteness: `agent_workroot` does not validate the override is outside the
  repo — a tester or stray env var pointing inside `PROJECT_ROOT` silently defeats Layer A.
- Assertion: `agent_work_dir("gemini","s").is_relative_to(PROJECT_ROOT)` is False for the
  default; document the override-inside-repo gap.

**TC-1.3 — `_escalate_to_autobrief` passes `cwd=work_dir` outside repo**
- Target: `autowork_daemon._escalate_to_autobrief` (`:683`).
- Scenario: stage a non-degenerate blocked task JSON
  (`tasks/blocked/T.json` with objective+files_touched) so the guard does NOT short-circuit;
  mock Popen; call.
- Expected: `Popen` called with `cwd=str(work_dir)`, `cwd` startswith `agent_workroot()`,
  `cwd == env['JANUSMASK_WORK_DIR']`, and `cwd` not under `PROJECT_ROOT`.
- Mocking: patch `autowork_daemon.subprocess.Popen`; provide minimal `harness/config.yaml`
  resolution (or rely on the `agents` default fallback). Avoid the known-failing
  `mock_open` pattern — write a real temp task JSON instead.

**TC-1.4 — `_escalate_inactivity` passes `cwd=work_dir` outside repo**
- Target: `autowork_daemon._escalate_inactivity` (`:1730`).
- Scenario: seed actionable work (write a non-comment line to a *tmp* allowlist under the
  test's state_dir — NOT the real repo allowlist) so the guard passes; mock Popen.
- Expected: `Popen(..., cwd=str(work_dir))`, outside repo, equals env WORK_DIR.

**TC-1.5 — env WORK_DIR and cwd agree (no split-brain submission)**
- Target: `orchestrator._build_agent_env` + `spawn_agent` + `_env._work_dir`.
- Scenario: build env for agent, then call `_env._work_dir()` with that env in os.environ.
- Expected: `_build_agent_env(...)['JANUSMASK_WORK_DIR'] == str(_env._work_dir(...))` —
  the spawn site and the hook fallback compute the SAME dir; regression would persist a
  submission to one tree and poll from another.

### Group 2 — degenerate-escalation guard edge cases

**TC-2.1 — autobrief skip: missing task JSON**
- Target: `_escalate_to_autobrief` (`:586`).
- Scenario: `tasks/blocked/T.json` absent; mock Popen.
- Expected: NO Popen; one `skip_degenerate_escalation` row with detail
  `missing_task_json` appended to `state_dir/impl_progress.jsonl`.

**TC-2.2 — autobrief skip: empty objective + no files + no errors**
- Scenario: task JSON exists with `{"objective":"", "files_touched":[]}`, no fuzz/ledger
  errors. Expected: skip, reason `empty_objective_files_no_errors`, no Popen.

**TC-2.3 — autobrief proceeds when ONLY errors are present (no objective/files)**
- Scenario: empty objective + empty files_touched BUT seed a fuzz result JSON under
  `logs/fuzz_results/*T*.json` with a `failures` list so `_get_errors_for_task` returns
  non-empty. Expected: guard does NOT skip → Popen IS called. This pins the boundary that
  errors alone rescue the escalation.
- Suspected incompleteness: `_no_errors` compares the *stripped whole string* to the
  sentinel `'No traceback or fuzz error logs found.'`; any error content flips it. Verify a
  whitespace-only / truncated-marker error body doesn't falsely count as "has errors".

**TC-2.4 — autobrief proceeds with objective only (no files, no errors)**
- Scenario: `{"objective":"do X","files_touched":[]}`. Expected: NOT skipped (the AND
  requires ALL three empty). Popen called.

**TC-2.5 — inactivity skip: no actionable work**
- Target: `_escalate_inactivity` (`:1644`).
- Scenario: empty/comment-only tmp allowlist, no `tasks/*.json`, no live blocked.
  Expected: skip, reason `no_actionable_work`, no Popen.

**TC-2.6 — inactivity edge: blocked task with `.exhausted` sidecar is NOT live**
- Target: `:1632`-`:1639`. Scenario: `tasks/blocked/B.json` + `tasks/blocked/B.exhausted`
  both present, nothing else. Expected: `_has_live_blocked` False → skip. Then remove the
  `.exhausted` sidecar → expect proceed. Pins the exhausted-sidecar logic.

**TC-2.7 — guard reason string fidelity / telemetry shape**
- Assert the emitted row is valid JSON with `event=="skip_degenerate_escalation"` and the
  exact `detail` reason; assert `_emit_telemetry` wrote to `impl_progress.jsonl`.

### Group 3 — self-heal prompt scrub

**TC-3.1 — retry-budget prompt forbids repo/git/allowlist writes**
- Target: `_escalate_to_autobrief` resolved prompt (`:656`, `:676`).
- Scenario: capture the resolved `-p` argument from the mocked Popen argv.
- Expected: prompt contains "Do NOT" + "outbox" + "{OUTBOX_PATH}"→resolved outbox path;
  MUST NOT contain "auto_promote.allowlist append" instruction or
  "Append `<task>_fix` ... to the allowlist". Assert the legacy instruction
  `"Append `{task_id}_fix` as a new line to the allowlist"` is ABSENT (regression guard
  for the ex-phantom-task-no-promote memory).
- Assertion: substring checks on the captured argv element after `-p`.

**TC-3.2 — inactivity prompt forbids repo/git writes, outbox-only**
- Target: `_escalate_inactivity` prompt (`:1683`, `:1703`).
- Expected: contains "Do NOT write anywhere outside your outbox", "do NOT run git", "do
  NOT edit the auto-promote allowlist"; the only write target is `{OUTBOX_PATH}/diagnosis.md`.

**TC-3.3 — self-heal default agent fallback can spawn a hook-less agy (gap test)**
- Target: `_escalate_to_autobrief`/`_escalate_inactivity` agent_cfg fallback (`:630`,
  `:1661`).
- Scenario: config with NO `agents.<agent>` entry AND
  `control.autobrief_default_agent: gemini`. Expected: command resolves to bare `agy
  -p --sandbox` — assert the argv `command` endswith `agy` and there is NO `--settings`
  flag → documents that the self-heal containment for agy rests ONLY on prompt scrub +
  cwd + §1b, NOT on the (never-loaded) hook gate.
- Note: with default config (`autobrief_default_agent: claude`) this path picks claude;
  the test forces the gemini default to expose the gap.

### Group 4 — approval-gate enforcement (§1b)

**TC-4.1 — apply gate rejects a non-member path**
- Target: `git_integration._enforce_apply_scope`.
- Scenario: `allowed_files={'a/b.py'}`, rel `a/c.py`. Expected: returns a
  "scope violation ... not a member" string (non-None).

**TC-4.2 — apply gate blocks harness/** without approval**
- Scenario: rel `harness/x.py`, `meta_task_type='feature'`, `approval_ok=False` (and a
  sub-case `meta_task_type='harness_self_fix', approval_ok=False`). Expected: rejection
  string in both. Then `harness_self_fix + approval_ok=True` → returns None (allowed).

**TC-4.3 — `_matches_sensitive` `**` semantics**
- Scenario: assert `harness/a.py`, `harness/sub/a.py`, `config/x`, `scripts/y` match;
  `harnessx/a.py`, `notharness/a.py`, `harness` (the bare dir name matches base) edge:
  test `'harness'` equals base → True; `'harnessfoo'` → False. Pins the manual prefix test
  (fnmatch does not treat `**` recursively).

**TC-4.4 — `_apply_approval_granted` decision-file parsing**
- Target: `orchestrator._apply_approval_granted`.
- Scenario: decision files: missing → False; `{"decision":"approve"}` → True;
  `{"decision":"approved"}` → True; `{"decision":"reject"}` → False; corrupt JSON →
  False; non-dict (`[]`) → False; `{"decision":" APPROVE "}` (whitespace+case) → True
  (it `.strip().lower()`s).
- Assertion: direct return-value checks; write decision files under
  `state_dir/control/decisions/<id>.json`.

**TC-4.5 — `commit_accepted_output` membership defaults (None opt-out)**
- Scenario: call a commit path helper with `allowed_files=None` and a `harness/x.py`
  target. Expected: membership check skipped BUT sensitive gate still fires (rejection).
  Confirms low-level callers that pass None don't accidentally bypass the sensitive gate.
- Mocking: this needs a tmp git worktree (see `test_agent_isolation.py:_git`/`tmp_repo`
  fixture as a template) — reuse that pattern; no agents involved.

**TC-4.6 — `await_decision` default no-op + timeout**
- Target: `control_gate.await_decision`.
- Scenario: phase NOT in `require_approval` → returns `'auto'` immediately (no sleep).
  Then phase IN `require_approval`, no decision file, `timeout=0.01`, `poll_interval=0.001`
  → returns `'timeout'` and `emit_timeout` fired. Then drop a `{"decision":"approve"}`
  file first → returns `'approve'`.
- Assertion: return value + callback spy; keep timeouts tiny.

**TC-4.7 — `check_pause` fail-open**
- Scenario: flag file = "paused" → True; absent → False; flag is a DIRECTORY
  (IsADirectoryError) → False (fail-open) with rate-limited warning. Confirms a broken
  pause flag does not wedge the loop.

### Group 5 — `_SHELL_ALLOW` / `_decide_shell` hardening (hook-loading agents)

**TC-5.1 — dropped write verbs are now denied**
- Target: `gemini.pre_tool._decide_shell`.
- Scenario: feed `{'command': 'tee x'}`, `'cp a b'`, `'mv a b'`, `'ln -s a b'`,
  `'chmod 755 x'`, `'rm -rf /tmp/x'`, `'python3 -c "..."'`,
  `'python3 harness/sandbox.py'`. Expected: ALL `deny`.
- Suspected incompleteness: the deny **reason string** (`:160`) still advertises the OLD
  allowlist ("Allowed prefixes: ... python3 -c, python3 harness/sandbox.py, cat <<, tee,
  ... rm -rf"). Assert the *decision* is deny but ALSO flag the stale reason text as a
  doc/UX bug (the message lies to the agent about what's allowed).

**TC-5.2 — retained verbs still allowed**
- Scenario: `'pytest'`, `'pytest tests/x.py'`, `'python3 -m pytest'`, `'mkdir -p x'`,
  `'touch x'` → `allow`.

**TC-5.3 — `pytest`/`python -m pytest` are arbitrary code (documented non-barrier)**
- Scenario: assert `'pytest -p no:cacheprovider'` is allowed → document that pytest
  collection auto-imports conftest/plugins = arbitrary code execution; the test asserts
  the allow AND records that `_SHELL_ALLOW` is explicitly NOT the code-exec barrier (per
  the §3.3 comment). Containment is cwd + §1b only.

**TC-5.4 — bare `cat` read path still open within allowed roots**
- Target: `_decide_shell` `_CAT_BARE_RE` branch (`:146`-`:156`).
- Scenario: `{'command': 'cat <work_dir>/inbox/task.json'}` with a session whose
  `_read_allowed_roots` includes work_dir → `allow`. `'cat /etc/passwd'` → deny (outside
  roots). `'cat -n x'` (flag) → deny. `'cat'`/`'cat -'` (stdin) → deny.
- Suspected incompleteness: `cat` reads were NOT dropped from the hardening — the §3.3
  comment claims "cat<<EOF" was dropped, but the bare-cat reader remains a read primitive
  (acceptable for reads, but verify it cannot be used to read arbitrary absolute paths
  outside the allowed roots — assert the root check is enforced).
- Mocking: monkeypatch `_env.work_dir` / `_paths` so `_read_allowed_roots` returns tmp
  roots; no agent.

**TC-5.5 — `_decide_write_or_replace` outbox containment**
- Scenario: `write_file` to a path OUTSIDE outbox → deny; to `outbox/submission.py` in
  synthesis mode → routes to `_decide_submission`; to `outbox/plan_draft.json` in
  synthesis mode → deny (mode mismatch). Pins that the write gate (which IS the
  submission path) still confines writes to the outbox per mode.

**TC-5.6 — hook gate inertness for bare agy (gap documentation test)**
- Target: config wiring. Scenario: load `harness/config.yaml`; assert `agents.gemini`
  command endswith `/agy` and its args contain `--sandbox` but NOT `--settings`
  `gemini_settings.json`. Conclusion asserted: the BeforeTool hook (and thus
  `_SHELL_ALLOW`/`_decide_shell`) is NEVER registered for the production gemini/agy spawn,
  so Group-5 hardening protects only a hypothetical settings-wired invocation.

### Group 6 — `_env` workdir fallback

**TC-6.1 — fallback uses outside-repo workroot, not dead state/workdirs**
- Target: `hooks._env._work_dir`.
- Scenario: ensure `JANUSMASK_WORK_DIR` UNSET; set `JANUSMASK_STATE_DIR`,
  `JANUSMASK_AGENT_WORKROOT` (tmp). Call `_work_dir(session_id='s', agent='gemini')`.
- Expected: returns `<workroot>/gemini/s` resolved; NOT under `state_dir/workdirs`; NOT
  under PROJECT_ROOT. A second sub-case: `JANUSMASK_WORK_DIR` SET → returns it verbatim
  (env wins).
- Suspected incompleteness: `_resolve_agent(None)` returns `''` when `JANUSMASK_AGENT`
  unset and no explicit agent → produces `<workroot>//s` (empty agent segment). Assert the
  per-agent shims always pass an explicit agent; flag the empty-agent fallback as a latent
  split-brain (orchestrator writes `<workroot>/gemini/...` but a hook with no agent arg
  reads `<workroot>//...`).

---

## 5. Incompleteness & gap candidates (file:line)

- **`harness/hooks/gemini/pre_tool.py:160`** — `_decide_shell` deny reason string is STALE:
  still advertises tee/cp/mv/ln/cat<</python -c/sandbox.py/`rm -rf` as "Allowed prefixes"
  after §3.3 dropped them. Misleads the agent; decision is correct but the message lies.
- **`harness/hooks/gemini/pre_tool.py:146-156`** — bare-`cat` read primitive survives the
  §3.3 "drop write verbs" hardening; the §3.3 comment lists "cat<<EOF" as dropped but the
  reader path remains. Verify root-confinement is airtight (no absolute-path escape).
- **`harness/hooks/gemini/pre_tool.py` (whole module) / `harness/config.yaml:32-36`** —
  the hook gate NEVER LOADS for the production gemini/agy command (`agy -p --sandbox`, no
  `--settings`/BeforeTool). All §3.3 hardening is inert for the real agent; containment
  rests entirely on cwd + §1b. (Acknowledged in the code comment — confirms vaporware
  status of Layer C for agy.)
- **`harness/paths.py:agent_workroot`** — `$JANUSMASK_AGENT_WORKROOT` override is NOT
  validated to be outside `PROJECT_ROOT`; a misconfigured/inside-repo override silently
  re-opens the relative-path hole (Layer A) for ALL spawn sites at once.
- **`harness/autowork_daemon.py:630,1661`** — self-heal agent_cfg fallback hardcodes
  `agy -p --sandbox` for any non-claude agent; if `autobrief_default_agent` is set to
  gemini, the self-heal spawns a hook-less agy whose only containment is the prompt scrub
  + cwd + §1b (no per-tool gate).
- **`harness/hooks/_env.py:50` (`_resolve_agent`→`''`)** — when both `agent` arg and
  `JANUSMASK_AGENT` are absent, the fallback workdir gets an EMPTY agent segment
  (`<workroot>//<sid>`), diverging from the orchestrator's `<workroot>/<agent>/<sid>` —
  latent split-brain if any hook calls `_work_dir` without the explicit agent kwarg.
- **`harness/autowork_daemon.py:558`** — `_get_errors_for_task` truncates combined errors
  to the LAST 100000 chars; the degenerate guard's `_no_errors` test then depends on this
  truncated body — edge: a 100KB+ error blob is fine, but verify the truncation marker
  doesn't equal the sentinel.
- **`harness/autowork_daemon.py:768` (`_spawn_worker`)** — only spawn site WITHOUT `cwd=`.
  Correct today (spawns the trusted harness worker, not an agent) but undocumented; a
  future change that routes an agent command through here would bypass Layer A unnoticed.
- **`tests/test_autowork_escalation.py` / `tests/adversarial/test_autowork_self_healing.py`
  (5× `test_escalate_to_autobrief_*`)** — SHOULD BE REPAIRED: broken by the degenerate
  guard + `mock_open` (they mock the task JSON read so the guard's `task_json_path.exists()`
  / error reads behave unexpectedly). Repair by writing a real temp blocked-task JSON +
  fuzz/ledger error fixture instead of `mock_open`. (Known pre-existing; not re-flagged as
  new.)
- **`tests/...test_orchestrator_timeout_fixes.py` (2× `*_exits_with_status_2_use_retry_module`)**
  — known pre-existing failures; candidate for repair, out of this area's primary scope.

---

## 6. Runbook

Venv: `/home/xnihil0zer0/JanusMaskJR/.venv/bin/python` (3.13). Run from repo root.

### Test file to create
`tests/adversarial/test_daemon_control_isolation_hooks.py`
(co-locate with the existing `tests/adversarial/test_agent_isolation.py`, whose
`_FakePopen`, `workroot` fixture, `_is_outside_repo`, `_git`/`tmp_repo` helpers are the
canonical templates — reuse them).

### Mandatory hermeticity (every test)
```python
@pytest.fixture
def workroot(tmp_path, monkeypatch):
    root = tmp_path / "agentwork"
    monkeypatch.setenv("JANUSMASK_AGENT_WORKROOT", str(root))
    return root
```
- Mock Popen at the module under test: `monkeypatch.setattr(autowork_daemon.subprocess,
  "Popen", FakePopen)` and `...orchestrator.subprocess...`. NEVER allow a real subprocess.
- For Group 2/3, write a REAL temp `tasks/blocked/<id>.json` (avoid `mock_open` — it is the
  cause of the known-failing tests). Telemetry assertions: read
  `state_dir/impl_progress.jsonl` and parse JSON lines for `event=="skip_degenerate_escalation"`.
- For Group 4 commit-path tests, build a tmp git repo (init + commit a seed file) per the
  `tmp_repo` fixture; pass `worktree_root`. No agents.
- Group 5: monkeypatch `harness.hooks.gemini._env.work_dir` / `harness.hooks._paths` so
  `_read_allowed_roots` resolves to tmp dirs; call `_decide_shell` / `_decide_write_or_replace`
  directly with synthetic `tool_input` dicts.
- Group 6: control `JANUSMASK_WORK_DIR`, `JANUSMASK_STATE_DIR`, `JANUSMASK_AGENT`,
  `JANUSMASK_AGENT_WORKROOT` via `monkeypatch.setenv`/`delenv`.

### Invocations
```bash
# Full new file
/home/xnihil0zer0/JanusMaskJR/.venv/bin/python -m pytest \
  tests/adversarial/test_daemon_control_isolation_hooks.py -q

# By group (example: isolation cwd + guard)
/home/xnihil0zer0/JanusMaskJR/.venv/bin/python -m pytest \
  tests/adversarial/test_daemon_control_isolation_hooks.py -q -k "cwd or guard"

# Regression-confirm the existing isolation suite still green
/home/xnihil0zer0/JanusMaskJR/.venv/bin/python -m pytest \
  tests/adversarial/test_agent_isolation.py -q
```

### Hard constraints reminder for the tester
- Read-only on `harness/` source; do NOT modify it.
- Do NOT run the daemon/pipeline/agy; all spawns mocked.
- Do NOT touch `state/control/autowork/full_stop` (halted),
  `auto_promote.allowlist` (deny-all), or `autowork.enabled`. Group-1.4/2.5 allowlist
  reads MUST use a tmp `state_dir`, never the real repo state.
- Do NOT re-assert the 7 known pre-existing failures as new regressions.
