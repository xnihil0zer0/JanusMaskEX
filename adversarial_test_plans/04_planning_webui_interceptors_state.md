# Adversarial Test Plan 04 — Planning, WebUI, Interceptors, State & Replication

> Exploration agent 4 of 4. READ-ONLY analysis. Tests below are authored for a
> later tester sub-agent and MUST run WITHOUT real agents (no agy/claude, no
> live webui spawns). Do NOT weaken the dual-agent agreement invariant or the
> fuzzer bypass. `.venv`: `/home/xnihil0zer0/JanusMaskJR/.venv/bin/python` (3.13).

---

## 1. Area & scope

Files owned by this plan:

- **Planner**: `harness/planner/blind_draft.py` (`run_blind_drafts`,
  `collect_agent_draft`, `_resolve_outbox_artifact`, `_PerAgentConfig`),
  `adversarial_review.py`, `reconciliation.py`, `plan_validator.py`,
  `brief_loader.py`, `taxonomies.py`, `cli.py`.
- **WebUI control**: `tools/webui_control.py` (`post_brief_autocomplete`,
  `_subst`/`${PROJECT_ROOT}` interpolation, `_agents_override` seam,
  `_spawn_tracked`, planner dry-run kickoff, config cache, `ALLOWED_AGENTS`).
  `tools/webui_server.py` (NOTE: `webui.app` imports `psutil`, which is NOT
  installed — pre-existing env gap; any test importing `webui.app` will error at
  collection. Plan around it; the autobrief tests do not import it.)
- **Interceptors**: `harness/interceptors.py` (registry + 2 built-ins).
- **State/ledger**: `harness/state.py`, `scripts/impl_outbox_watcher.py`
  (`write_jsonl_row` via `harness._journal`).
- **Replication/config**: `harness/config.yaml` (vendored `${PROJECT_ROOT}`
  command paths), `harness/orchestrator.py:_interpolate_config_paths`/`load_config`,
  `harness/paths.py` (`agent_workroot`, `*_STR` constants),
  `scripts/bootstrap.sh`, `scripts/setup-agents.sh`.

---

## 2. 24h changes (the AGENT_ISOLATION hand-edit)

Single dominant commit: **`9e0fc64`** "AGENT_ISOLATION: sanctioned hand-edit —
apply-path scoping + CWD relocation" (Fri May 29 05:41). Relevant slices:

- **`harness/config.yaml`**: all 4 agent commands re-pointed from bare
  `agy`/`claude` to vendored absolute tokens:
  `command: ${PROJECT_ROOT}/.agents/agy/agy` (antigravity, claude_fallback,
  gemini) and `${PROJECT_ROOT}/.agents/claude-code/node_modules/.bin/claude`
  (claude). YAML now ships **tokens, not host paths** — every consumer must
  interpolate `${PROJECT_ROOT}` or it spawns a literal nonexistent path.
- **`harness/planner/blind_draft.py:30-33`** (`_resolve_outbox_artifact`):
  `workdirs_root = agent_dir/'workdirs'/agent` → `agent_workroot()/agent`.
- **`scripts/impl_outbox_watcher.py:199-204`** (`_scan_once`):
  `state_dir/"workdirs"` → `agent_workroot()`. The agent-name filter (line 209)
  and session regex (line 40) were **left untouched** — see §5 GAP-1.
- **`scripts/bootstrap.sh:49`**: dropped `mkdir state/workdirs` (relocated out
  of repo).
- **`scripts/setup-agents.sh`** (NEW): vendors agy + claude-code under
  `.agents/` (gitignored). NOTE in-script: the claude shim
  `.agents/claude-code/node_modules/.bin/claude` REQUIRES node on PATH at spawn;
  it is NOT self-contained.
- **`tools/webui_control.py`**: added `_agents_override` class seam (line ~78)
  and inline `_subst` for `${PROJECT_ROOT}/${CONFIG_DIR}/${STATE_DIR}` in
  `post_brief_autocomplete` (lines 188-213). webui reads config **raw** (NOT via
  `orchestrator.load_config`), so substitution had to be duplicated here.
- New paths source: **`harness/paths.py`** — `PROJECT_ROOT_STR`/`CONFIG_DIR_STR`/
  `STATE_DIR_STR` constants and `agent_workroot()` (honors
  `$JANUSMASK_AGENT_WORKROOT`, else `<repo>.parent/<repo>_agentwork`).

---

## 3. Architecture map

### Config interpolation — who interpolates `${PROJECT_ROOT}` and who does NOT

| Consumer | Reads command from | Interpolates `${PROJECT_ROOT}`? |
|---|---|---|
| `orchestrator.load_config` (`orchestrator.py:97-128`) | YAML | YES — recursive `_interpolate_config_paths` |
| `orchestrator.spawn_agent`/`_build_agent_command` (`orchestrator.py:172-185`) | config dict | relies on caller having called `load_config` (no local subst) |
| `autowork_daemon._spawn_worker` self-heal (`autowork_daemon.py:635-646`) | `_load_config` raw YAML | YES — local `subst()` at spawn site |
| `autowork_daemon` 2nd self-heal Popen (`autowork_daemon.py:1666-1677`) | `_load_config` raw YAML | YES — local `subst()` |
| `tools/webui_control.post_brief_autocomplete` (`webui_control.py:188-213`) | raw YAML or `_agents_override` | YES — local `_subst()` |
| `planner.adversarial_review` (`adversarial_review.py:114`) | `derived_config` (caller's config) | NO local subst — depends on caller having interpolated; then `shutil.which(parts[0])` (§4 CASE-C) |
| `planner.reconciliation` / `planner.cli` | none directly | go through `spawn_agent` |

**KEY**: `autowork_daemon._load_config` (`autowork_daemon.py:50-60`) does the raw
`yaml.safe_load` and **does NOT interpolate** — it is salvaged only because the
two spawn sites do their own `subst()`. Any *other* daemon code path that reads
`config['agents'][x]['command']` from `_load_config` output and spawns it
WITHOUT calling `subst()` would ship the literal `${PROJECT_ROOT}` token. The
audit found no such third reader, but the asymmetry is fragile — CASE-A/B below
pin it.

### Planner blind-draft flow (`blind_draft.py`)

`run_blind_drafts(brief, config, state_dir)` → writes brief.json → builds
`_PerAgentConfig(deepcopy(config), claude_dir, gemini_dir)`. **`_PerAgentConfig`
state_dir trick** (`blind_draft.py:92-114`): subclasses `dict`; `get('state_dir')`
walks `inspect.stack()` for a frame named `run_agent_phase`/`spawn_agent`, reads
its local `agent`, and returns the matching per-agent session dir — so the two
agents write into distinct planning session dirs from the SAME config object.
`__getitem__('state_dir')` delegates to `get`. → `run_both_agents` →
`collect_agent_draft(agent, agent_dir, ...)` search order: per-agent canonical
(`agent_dir/planning/sessions/<agent>_draft.json`) → top-level canonical
(`state_dir/...`) → `_resolve_outbox_artifact(...)` (glob
`agent_workroot()/<agent>/<agent>-r<round>-*/outbox/plan_draft.json`,
mtime-newest, `spawn_start_epoch` floor) → latency floor
(`min_response_seconds=10` → `suspect_hallucination`) → `_validate_plan`.

### WebUI autobrief spawn (`post_brief_autocomplete`)

`req_agent` checked against `ALLOWED_AGENTS=('claude','gemini','antigravity')`
(line 162). Resolve command: if `_agents_override` set, use it; else raw YAML.
`_subst` interpolates tokens. Build argv (insert prompt after `-p`).
`run_attempt`: `_spawn_tracked(argv, stdin=rough_draft)` → poll `exit_code`
file → SIGTERM/SIGKILL on timeout → parse stdout JSON (needs `slug`+`content`)
→ 1 retry on parse-fail only. Then slug regex `^[a-z0-9_]+$` ≤48 → write
`draft.md` → planner `--dry-run` subprocess (`sys.executable -m
harness.planner.cli`, cwd=repo_root → goes through `load_config`, interpolates
fine) → 200 with validation block.

### Interceptor registry (`interceptors.py`)

Global `registry` registers `ASTVerificationInterceptor` +
`BashSafetyInterceptor`. Both implement only `pre_tool_use`; their
`pre_invocation`/`post_tool_use` are inherited no-ops. Wiring:
- `orchestrator.py:291` calls `registry.pre_invocation(...)` at spawn — invokes
  only the base-class `pass` (NO built-in does anything here).
- `orchestrator.py:398/414/431/444` call `registry.pre_tool_use(agent,
  'submit_code', {'code': code})` in `poll_for_submission` and at 406/419/436/449
  call `post_tool_use`. So AST gating fires only for the `submit_code` synthesis
  artifact, NOT for live Write/Bash (those are CLI-hook territory).
- `BashSafetyInterceptor.pre_tool_use` is **dead in this harness**: only fires
  for `tool_name in ('Bash','execute_command','mcp__janusmask__execute')`, but
  the only caller passes `'submit_code'`. Plus its default workspace fallback
  is a hardcoded foreign path `/home/xnihil0zer0/NobleJanus` (line 95).

### State / ledger

`state.py`: `locked_read_modify_write` (flock LOCK_EX), `read_state` (LOCK_SH),
`set_phase`/`set_agent_status` validate against `VALID_PHASES`/`VALID_AGENTS`
(`{'claude','gemini','antigravity'}` — **no `claude_fallback`**) /
`VALID_AGENT_STATUSES`. Self-import shims at lines 168-205 are dead defensive
re-imports of names already defined above (`if 'X' not in globals(): from
harness.state import X`). Ledger rows via `harness._journal.write_jsonl_row`
(used by `impl_outbox_watcher._append_ledger`).

### Outbox-watcher pickup (`impl_outbox_watcher.py`)

`_scan_once` iterates `agent_workroot()`, **skips any dir whose name is not
`claude`/`gemini`** (line 209), then for each session dir reads
`outbox/submission.py`, parses the slug via `_SESSION_RE =
^(claude|gemini)-r\d+-...`, runs `rpc_submit_code.ensure_valid`, writes canonical
submission JSON + ledger row. This is the async sidecar replaying the dropped
PostToolUse persist; the in-process `orchestrator.poll_for_submission` →
`_path_b_outbox_fallback` is the primary path.

---

## 4. Adversarial test plan (enumerated)

> Common mocking: pin `JANUSMASK_AGENT_WORKROOT` to `tmp_path` (monkeypatch
> env) — see `tests/adversarial/test_planning_outbox_fallback_adversarial.py::
> _isolate_agent_workroot`. For webui, use `ControlHandlers._agents_override`
> to inject bare PATH-resolvable stub commands and PATH-stage stub binaries —
> see `tests/integration/test_webui_control_autobrief.py` (`stub_binaries`
> fixture writes `claude`/`gemini` shells, `_agents_override` injects them).
> NEVER spawn real agy/claude. Always reset `_agents_override = None` in teardown.

### CASE-A — every config-command consumer interpolates `${PROJECT_ROOT}` (PRIORITY)
- **Target**: `orchestrator.load_config` + `_interpolate_config_paths`
  (`orchestrator.py:97-128`).
- **Scenario**: Load the real `harness/config.yaml`; assert NO interpolated
  command/arg string still contains the literal substring `${PROJECT_ROOT}`,
  `${CONFIG_DIR}`, or `${STATE_DIR}` for all 4 agents (antigravity, claude,
  claude_fallback, gemini).
- **Expected**: every `agents.*.command`/`args` is fully resolved to an absolute
  path under `PROJECT_ROOT`.
- **Suspected incompleteness**: none in `load_config`; this is the regression
  pin proving the YAML→runtime contract.
- **Assertion**: `cfg = load_config(); for a in cfg['agents']: assert '${' not
  in cfg['agents'][a]['command']; assert all('${' not in x for x in args)`.

### CASE-B — daemon self-heal spawn interpolates despite raw `_load_config` (PRIORITY)
- **Target**: `autowork_daemon._spawn_worker` self-heal block
  (`autowork_daemon.py:633-646`) and the 2nd Popen (`1664-1677`).
- **Scenario**: Call the spawn-prep with `subprocess.Popen` monkeypatched to a
  capture stub; feed config from `_load_config` (raw, token-bearing). Capture
  the final `cmd[0]`.
- **Expected**: `cmd[0]` is an absolute resolved path (no `${PROJECT_ROOT}`),
  because the local `subst()` ran. Also assert `cwd` == an `agent_workroot()`
  subdir (outside repo).
- **Suspected incompleteness**: the raw `_load_config` (`autowork_daemon.py:50`)
  does NOT interpolate — this test pins that the spawn site compensates. If a
  future refactor removes the local `subst`, this fails. ALSO directly assert
  `_load_config(config_path)['agents']['claude']['command']` STILL contains
  `${PROJECT_ROOT}` (documents the asymmetry as intentional, not a bug to fix
  by interpolating in `_load_config` — which would double-interpolate).
- **Assertion**: capture argv via monkeypatched Popen; substring checks.

### CASE-C — adversarial_review early command check vs interpolated path (PRIORITY)
- **Target**: `adversarial_review.py:114-120`.
- **Scenario**: Pass a `config` whose reviewer `command` is the RAW token
  `${PROJECT_ROOT}/.agents/agy/agy` (i.e. caller forgot `load_config`). Run the
  reviewer entry with `spawn_agent` mocked.
- **Expected/Suspected**: `shutil.which('${PROJECT_ROOT}/.agents/agy/agy')`
  returns None → `write_synthetic_failure("Command not found: ${PROJECT_ROOT}...")`.
  This is a latent foot-gun: the reviewer does NOT interpolate, so it depends on
  the caller. Test BOTH branches: (a) interpolated absolute path that exists
  (stub on disk, made executable) → proceeds to `spawn_agent`; (b) raw token →
  synthetic failure. Document (b) as a gap candidate (GAP-2).
- **Assertion**: assert returned synthetic-failure payload reason mentions
  "Command not found" for the raw-token case; assert `spawn_agent` IS called for
  the interpolated case.

### CASE-D — outbox-watcher silently drops claude_fallback submissions (PRIORITY — known bug)
- **Target**: `impl_outbox_watcher._scan_once` (line 209) + `_SESSION_RE` (line 40).
- **Scenario**: Pin `JANUSMASK_AGENT_WORKROOT=tmp`. Stage a valid submission at
  `tmp/claude_fallback/claude_fallback-r1-T123-deadbeef/outbox/submission.py`
  with trivially-valid code. Run `main(['--state-dir', str(state), '--once'])`.
- **Expected (current/buggy)**: `_scan_once` returns 0 touched; NO canonical
  submission JSON written; NO ledger row. The submission is silently lost.
- **Suspected incompleteness**: GAP-1 — `claude_fallback` (a real synthesis
  fallback agent, `orchestrator.py:517/541`) and `antigravity` (default autobrief
  agent + daemon loop `autowork_daemon.py:546`) both produce workdirs named
  `claude_fallback`/`antigravity`, which the watcher filter and regex reject.
- **Assertion**: assert no file matching `*submission*.json` under
  `state/sessions/` and no `*.ledger.jsonl` row. Add a companion test staging an
  `antigravity/antigravity-r1-*` outbox → also dropped. Frame these as
  characterization tests that FAIL once the filter is widened to include
  `claude_fallback`/`antigravity` (the intended fix). Do NOT fix source.

### CASE-E — outbox-watcher accepts claude/gemini (control)
- **Target**: same `_scan_once`.
- **Scenario**: Stage `tmp/claude/claude-r1-T1-aaaaaaaa/outbox/submission.py` with
  valid code → `--once`.
- **Expected**: one canonical submission JSON in `state/sessions/`, one ledger
  row with `outcome="allow"`, `_process_submission` returns `"accept"`.
- **Assertion**: file exists; ledger row `detail.source == "outbox_watcher"`.
  Contrast CASE-D to make the silent-drop asymmetry explicit.

### CASE-F — outbox-watcher AST deny path lands a ledger row
- **Target**: `_process_submission` deny branch (lines 150-173).
- **Scenario**: Stage `claude` outbox `submission.py` containing code that trips
  `rpc_submit_code.ensure_valid` (e.g. a banned-nondeterminism / disallowed
  construct). Run `--once`.
- **Expected**: returns `"deny"`; NO canonical JSON; ledger row
  `outcome="deny"`, `detail.reason=="persist_time_ast_gate"`, non-empty
  `violations`.
- **Assertion**: parse the `.ledger.jsonl`; assert the deny row shape mirrors
  `AstValidationError`.

### CASE-G — `_resolve_outbox_artifact` relocation correctness (PRIORITY)
- **Target**: `blind_draft._resolve_outbox_artifact` (lines 20-42).
- **Scenarios** (pin `JANUSMASK_AGENT_WORKROOT=tmp`):
  1. Single outbox `tmp/claude/claude-r1-x/outbox/plan_draft.json` → returns it.
  2. Multiple outboxes, differing mtimes → newest wins.
  3. `spawn_start_epoch` set above all candidate mtimes → returns None
     (stale-outbox guard).
  4. Wrong round (`claude-r2-*` while asking round=1) → filtered by glob → None.
  5. Other-agent dir (`gemini-r1-*` while asking `claude`) → None.
  6. `agent_workroot()/<agent>` missing entirely → None (no crash).
- **Expected**: matches the relocated-root semantics; proves the §3.7 repoint
  resolves to `agent_workroot()/<agent>`, NOT the dead `agent_dir/workdirs`.
- **Assertion**: equality / None checks. (Existing test
  `test_planning_outbox_fallback_adversarial.py` covers much of this — extend
  for the stale-epoch + missing-root edges if not present.)

### CASE-H — `collect_agent_draft` status ladder
- **Target**: `blind_draft.collect_agent_draft` (lines 44-83).
- **Scenarios**: (a) no draft anywhere, elapsed ≥ timeout-1 → `"timeout"`;
  (b) no draft, elapsed small → `"crashed"`; (c) outbox draft with mtime <10s
  after `spawn_start_epoch` → `"suspect_hallucination"`; (d) malformed JSON →
  `"invalid"`; (e) schema-violating draft (fails `_validate_plan`) → `"invalid"`;
  (f) valid draft → `("…","ok")`.
- **Expected**: the exact status strings above.
- **Assertion**: tuple equality on `(draft, status)`.

### CASE-I — `_PerAgentConfig` state_dir frame trick
- **Target**: `blind_draft._PerAgentConfig` (lines 92-114).
- **Scenario**: Build `_PerAgentConfig(base, claude_dir, gemini_dir)`. Call
  `.get('state_dir')` from inside a function literally named `spawn_agent` with a
  local `agent='gemini'` (define a helper named `spawn_agent`) → returns
  `gemini_dir`. From an unrelated frame → returns base default. Also
  `cfg['state_dir']` delegates to `get`.
- **Expected**: agent-specific dir only when called within a
  `run_agent_phase`/`spawn_agent` frame whose `agent` local is set; else default.
- **Suspected incompleteness**: stack-inspection coupling is brittle — if either
  spawn function is renamed/inlined the trick silently returns the default
  state_dir (planning sessions would collide). Pin the function-name contract.
- **Assertion**: define stand-in frames; assert returned path.

### CASE-J — interceptor registry wiring (PRIORITY)
- **Target**: `interceptors.py` registry + the orchestrator submit_code calls.
- **Scenarios**:
  1. `registry.pre_tool_use('claude','submit_code',{'code': <AST-bad>})` returns
     `{'decision':'deny', ...}`.
  2. Same with clean code returns None (no deny).
  3. `registry.pre_invocation('claude','prompt',{})` returns None and does NOT
     deny/raise — documents that the spawn-time hook is a no-op (no built-in
     implements `pre_invocation`).
  4. `BashSafetyInterceptor.pre_tool_use('claude','submit_code',{...})` returns
     None for ANY input (tool_name guard excludes `submit_code`) — proving the
     bash interceptor is unreachable via the only live caller (GAP-3).
  5. Direct unit: `BashSafetyInterceptor.pre_tool_use('claude','Bash',
     {'command':'rm -rf /'})` with no `JANUSMASK_PROJECT_DIR` set — assert it
     does NOT crash on the hardcoded `/home/xnihil0zer0/NobleJanus` fallback
     (line 95) and returns a deny/allow; flag the foreign hardcoded path (GAP-4).
- **Expected**: per above; existing `tests/unit/test_interceptors.py` may
  overlap — extend with the wiring/no-op assertions.
- **Assertion**: dict shape checks; monkeypatch `ASTVerifier`/`validate_command`
  to deterministic stubs where helpful.

### CASE-K — `set_agent_status` rejects claude_fallback
- **Target**: `state.set_agent_status` / `VALID_AGENTS` (`state.py:12,144-149`).
- **Scenario**: `set_agent_status(state_dir, agent='claude_fallback',
  status='submitted')` → raises `InvalidAgentError`.
- **Expected**: raises. Confirms the orchestrator records fallback runs under the
  canonical `claude` identity (it never passes `'claude_fallback'` to
  `set_agent_status`; `orchestrator.py:1722-1727` uses `agent_a`/`agent_b`).
- **Assertion**: `pytest.raises(InvalidAgentError)`; plus a positive control with
  `agent='antigravity'`.

### CASE-L — `locked_read_modify_write` corrupt/missing state
- **Target**: `state.locked_read_modify_write` + `_read_state_from_disk`.
- **Scenarios**: (a) corrupt `STATE.json` → `StateCorruptError`; (b) missing →
  `StateMissingError`; (c) concurrent modifiers under flock serialize (two
  threads each incrementing `round`, final value deterministic).
- **Expected**: typed errors / serialized increments.
- **Assertion**: `pytest.raises`; threaded increment count == N.

### CASE-M — webui autobrief uses `_agents_override` + `_subst`, rejects unknown agent (PRIORITY)
- **Target**: `webui_control.post_brief_autocomplete` (lines 161-292).
- **Scenarios** (reuse `test_webui_control_autobrief.py` fixtures; do NOT import
  `webui.app`):
  1. `_agents_override = {'claude': {'command':'<stub>', 'args':['-p']}}`,
     stub on PATH echoing `{"slug":"x","content":"..."}` → 200, validation block.
  2. Config carries `${PROJECT_ROOT}/.agents/...`; assert `_subst` resolves it
     (set override to a value containing `${PROJECT_ROOT}` and a stub at that
     resolved path) → command actually invoked is the resolved path.
  3. `req_agent='evil'` not in `ALLOWED_AGENTS` → 400 `unknown agent`/400.
  4. Timeout stub (never writes exit_code) → 504 after SIGTERM/SIGKILL.
  5. Parse-fail twice → 502 (one retry only).
  6. Bad slug (`Invalid!`) → 422.
- **Expected**: per above. Always `ControlHandlers._agents_override = None` in
  teardown (class-level seam leaks across tests otherwise — itself a test
  hazard worth asserting).
- **Assertion**: status code + envelope keys; for case 2, capture argv via a
  spawn_fn stub and assert no `${` remains.

### CASE-N — plan_validator coverage (PRIORITY)
- **Target**: `plan_validator.validate_plan` / `check_missing_fields` /
  `validate_plan_wrapper`.
- **Scenarios** (one violation code per case): missing each top-level/spec/
  test_spec/budget/attr field; `unknown_meta_task_type`; empty/non-str
  meta_task_type → `missing_meta_task_type`; non-str priority →
  `invalid_priority_type`; non-canonical priority → `invalid_priority_encoding`;
  `duplicate_task_id`; `dependency_cycle` (A→B→A) emitted EXACTLY once;
  `test_ratio_violation` (test_tokens < 1.5×impl; impl=0 & test=0);
  `insufficient_unit_tests`; `missing_integration_test` (and EXCUSED via non_goal
  containing "integration" → no violation); `missing_edge_case_tests`;
  `insufficient_total_tests`; test_ tasks (`meta_task_type` startswith `test_`)
  SKIP the ratio/test-count rules. Wrapper: missing `source_brief_path`/
  `source_brief_sha256`, wrong sha length/charset → `invalid_sha256`; wrapper
  raises `ValueError` on a task with blank `verification_command`.
- **Suspected incompleteness**: GAP-5 — `dfs` (lines 150-167) is dead code; only
  `dfs2` (187-189) runs cycle detection. Add a test asserting a cycle is reported
  once (proves `dfs2` path) and note `dfs` is unreachable.
- **Assertion**: assert the expected violation `code` is present (and absent in
  the excused/skip cases).

### CASE-O — replication: bootstrap no longer makes state/workdirs; setup-agents pins
- **Target**: `scripts/bootstrap.sh`, `scripts/setup-agents.sh`, `paths.agent_workroot`.
- **Scenarios**: (static, no execution) assert `bootstrap.sh` does NOT contain
  `state/workdirs`; assert `agent_workroot()` with `$JANUSMASK_AGENT_WORKROOT`
  unset resolves to `<repo>.parent/<repo>_agentwork` (outside repo); with the env
  set, resolves there (absolute, not expanduser). Static-grep `setup-agents.sh`
  for the version pins + the node-shim caveat.
- **Assertion**: file substring checks; `agent_workroot()` path equality with
  env set/unset.

---

## 5. Incompleteness & gap candidates

- **GAP-1 (HIGH — silent submission drop)**: `scripts/impl_outbox_watcher.py:209`
  `agent_dir.name not in ("claude","gemini")` and `:40`
  `_SESSION_RE=^(claude|gemini)-r...` exclude `claude_fallback` and `antigravity`,
  both of which are REAL spawn agents producing workdirs under those names
  (`orchestrator.py:517,541`; `autowork_daemon.py:546`; config.yaml agents
  `antigravity`,`claude_fallback`). The §3.7 24h edit repointed the root to
  `agent_workroot()` but left the name filter — so a fallback/antigravity outbox
  submission is silently dropped by the async sidecar (the in-process
  `_path_b_outbox_fallback` still recovers it, masking the bug in normal runs).
- **GAP-2 (MEDIUM)**: `harness/planner/adversarial_review.py:114-119` reads
  `command` from `derived_config` and runs `shutil.which(parts[0])` WITHOUT local
  `${PROJECT_ROOT}` interpolation. If a caller passes a non-`load_config`'d config
  (raw token), the reviewer emits a spurious "Command not found: ${PROJECT_ROOT}…"
  synthetic failure. Fragile dependency on caller-side interpolation.
- **GAP-3 (LOW — dead interceptor)**: `harness/interceptors.py:72-114`
  `BashSafetyInterceptor.pre_tool_use` only fires for tool names
  `Bash`/`execute_command`/`mcp__janusmask__execute`, but the only live caller
  (`orchestrator.py:398…`) always passes `'submit_code'`. The bash interceptor is
  unreachable in the orchestrator path.
- **GAP-4 (LOW — foreign hardcoded path)**: `harness/interceptors.py:95`
  default workspace fallback is `/home/xnihil0zer0/NobleJanus` (a different
  project), not `PROJECT_ROOT`. Non-portable; only matters if the bash path were
  ever reached.
- **GAP-5 (LOW — dead code)**: `harness/planner/plan_validator.py:150-167` `dfs`
  is defined but never invoked; only `dfs2` (187-189) does cycle detection.
- **GAP-6 (LOW — dead defensive shims)**: `harness/state.py:168-205` self-import
  guards (`if 'X' not in globals(): from harness.state import X`) are unreachable
  no-ops for names defined earlier in the same module; the final
  `locked_read_modify_write` shim raises `NotImplementedError` only in an
  impossible branch.
- **OBSERVATION (not a fix target)**: `autowork_daemon._load_config`
  (`autowork_daemon.py:50-60`) does NOT interpolate `${PROJECT_ROOT}`; correct
  ONLY because both spawn sites do local `subst()`. Pin via CASE-B so a future
  refactor cannot regress it; do NOT "fix" by interpolating in `_load_config`
  (would double-interpolate the spawn-site subst).
- **TEST HAZARD**: `ControlHandlers._agents_override` is class-level state that
  leaks across tests if not reset to `None` in teardown.

---

## 6. Runbook

**Interpreter**: `/home/xnihil0zer0/JanusMaskJR/.venv/bin/python` (3.13).
Run from repo root `/home/xnihil0zer0/JanusMaskJR`.

**Env-gap guard**: do NOT import `webui.app` / `tools/webui_server.py` in any new
test — `psutil` is not installed and collection will error. The autobrief tests
import `tools.webui_control.ControlHandlers` directly and pass.

**Pre-existing failures to IGNORE** (do not re-flag, confirmed on `f1a746b`):
the 5× `test_escalate_to_autobrief_*` and the 2×
`test_orchestrator_timeout_fixes::test_*_exits_with_status_2_use_retry_module`.

**Existing tests to reuse / extend** (stub + seam patterns):
- `tests/adversarial/test_planning_outbox_fallback_adversarial.py` — the
  `_isolate_agent_workroot` fixture (`monkeypatch.setenv("JANUSMASK_AGENT_WORKROOT",
  str(tmp_path))`) and `_write_outbox_plan` helper. Reuse for CASE-D/E/G.
- `tests/integration/test_webui_control_autobrief.py` — `stub_binaries`
  fixture (PATH-staged `claude`/`gemini` shell stubs honoring
  `TEST_AUTOBRIEF_MODE`) + `ControlHandlers._agents_override` injection +
  teardown reset. Reuse for CASE-M.
- `tests/unit/test_interceptors.py` — extend for CASE-J.
- `tests/adversarial/test_planner_cli_config_substitution_adversarial.py` — for
  CASE-A/B substitution assertions.

**Suggested invocations** (author new files under `tests/adversarial/` and
`tests/unit/`):

```
# Planner / outbox / state / interceptors (fast, no spawns)
.venv/bin/python -m pytest -q \
  tests/adversarial/test_planning_outbox_fallback_adversarial.py \
  tests/unit/test_interceptors.py \
  -p no:cacheprovider

# Outbox-watcher silent-drop characterization (CASE-D/E/F) — new file
.venv/bin/python -m pytest -q tests/adversarial/test_outbox_watcher_agent_filter.py

# WebUI autobrief seam (CASE-M) — pin override, NEVER real spawns
.venv/bin/python -m pytest -q tests/integration/test_webui_control_autobrief.py

# plan_validator coverage (CASE-N)
.venv/bin/python -m pytest -q tests/unit/test_plan_validator_coverage.py
```

**Stub / seam notes**:
- Pin `JANUSMASK_AGENT_WORKROOT` to `tmp_path` for any test exercising
  `agent_workroot()` / `_resolve_outbox_artifact` / the outbox-watcher (absolute
  path; NOT expanduser).
- WebUI: set `ControlHandlers._agents_override = {<agent>: {'command': '<bare
  stub on PATH>', 'args': [...]}}`; PATH-stage the stub; ALWAYS reset
  `_agents_override = None` in teardown.
- Mock `subprocess.Popen`/`subprocess.run` (capture argv) for spawn-site
  substitution tests (CASE-B/C); never invoke real agy/claude/agy node shim.
- Monkeypatch `ASTVerifier` / `services.neurosymbolic.bash_validator.validate_command`
  to deterministic stubs for interceptor decision tests.
- Treat CASE-D as a characterization test (asserts the CURRENT silent-drop) so it
  flips to a fix-detector once the filter is widened. Do NOT modify source in
  this plan's tests.
```
