# Agent Isolation Fix — DRAFT for review (nothing applied/installed)

**Status:** DRAFT. No code changed, no binaries installed. This is the reviewable plan + diffs you asked for. After your approval I apply it as a sanctioned hand-edit + config (the pipeline can't safely build its own isolation fix), run the verification smoke-test, and only then resume the RB drain (tasks d/e).

**Goal:** the synthesis agents (`agy`/gemini especially) should be unable to *out-of-band* touch the live project tree or run `git` during synthesis. They read their task from a staged inbox and write only their `submission.py`; the harness applies it via the existing staging worktree. **This goal is narrower than "safe":** CWD/shell isolation does NOT make a submitted payload trustworthy — see §0 and the new Threat Model (§1a).

---

## 0. Consensus corrections applied (from 3-reviewer adversarial pass)

Each item below was independently raised by ≥2 of the 3 adversarial reviewers and has been integrated into this draft. Single-reviewer findings were NOT applied (listed at the end for the human to triage).

- **`${PROJECT_DIR}` does not expand** (R1+R2+R3): §3.4 now uses the supported `${PROJECT_ROOT}` token; the "confirmed at apply time" hedge is removed (it was already knowable and wrong).
- **"claude needs no change" deleted; submission-application is the real blast radius** (R1+R2+R3): §1/§2 no longer claim claude is contained for the threat that matters; new §1a Threat Model states isolation only stops out-of-band tampering — in-band safety rests on dual-agent + fuzz/verify + `files_touched` scoping.
- **`inbox/targets/` staging is vaporware; partial-edit breaks under relocation** (R1+R2): §2.2 marked **NOT YET BUILT**; §3.5 added with the concrete stager + prompt-rewrite that must land *before* relocation.
- **Shell write-scope guard undrafted; tee/cp/mv/ln unscoped** (R1+R2+R3): §3.3 no longer defers the guard. Default position is to DROP tee/cp/mv/ln (agents write only via the `write_file`→outbox path); if kept, a concrete `shlex`-based guard is required and unit-tested. Note the existing `cat` guard already exists and must be reused, and read-roots ≠ write-roots.
- **`cwd=work_dir` does NOT prevent repo reads** (R2+R3): §2.1 downgraded from "literally can't see harness/*.py" to "git can't auto-discover .git from CWD; relative paths no longer resolve into the repo." CWD relocation is now labeled *necessary but not sufficient*.
- **Allowlist hardening is cosmetic; `pytest` = arbitrary code** (R1+R2): §2.4/§3.3 acknowledge pytest collection (conftest/plugins/ini) is arbitrary code; the allowlist is not the code-exec barrier.
- **`--sandbox` scope unverified** (R1+R2+R3): §2.5/§5 now describe `--sandbox` as "terminal restrictions only; filesystem scope UNVERIFIED — assume NO filesystem isolation"; it is removed from the list of relied-upon barriers until §6 probes it.
- **`claude_fallback` + `antigravity` agy agents unaddressed** (R1+R2): §3.4/§3.6 extend coverage to all three agy-backed agents; both pass `--dangerously-skip-permissions` and must be analyzed/repointed too.
- **"deny git" is a no-op** (R1+R2): removed from the new-mitigations list — `_decide_shell` already default-denies; git was never in the allowlist and the incident commit happened because the hook never ran.
- **"0 hook denials in logs/gemini_stream.jsonl" is the wrong artifact** (R2+R3): §1 evidence rewritten to cite the absence of gemini hook-ledger files + uninterc­epted write/shell events; the 23 `deny` substrings are submission CONTENT, not hook decisions.
- **Relocation orphans `impl_outbox_watcher` and other `state/workdirs` consumers** (R2+R3): §3.1 no longer claims consumers "follow the relocation automatically"; §3.7 enumerates every consumer and requires repointing them or keeping workdirs under `state/`.
- **HOME override breaks `_boost_antigravity_mcp_config`** (R1+R2+R3): §5/§8 now state the coupling — any HOME redirect must also redirect where the MCP-boost writes, or the antigravity MCP server silently fails to register.
- **`home_key="HO"+"ME"` is benign/live, not evasion** (R1+R2+R3): §8 reframed — it is active code in `_boost_antigravity_mcp_config` (writes per `antigravity` spawn), not dead obfuscation; recommend de-obfuscating to `os.environ["HOME"]` in the same change.
- **§6 smoke-test inadequate** (R1+R2+R3): §6 rewritten to test absolute-path writes/reads, a `harness_self_fix` submission-application case, and a positive state-dir/inbox read assertion.
- **Vendoring under-specified / incomplete** (R1+R2+R3): §4 must repoint ALL agy/claude agents (not just gemini), resolve the pinned versions, and record agy SHA256; node runtime dependency for the claude shim noted.

### Round 2 (3-of-5) corrections applied
Five-reviewer round (R1–R3 reviewed the pre-§0 draft; R4–R5 reviewed the §0 version). Two NEW corrections reached the ≥3-of-5 acceptance bar and were not already reflected; both are integrated below. (Corrections that re-confirmed existing §0 items, and ≤2-of-5 items, are listed for the human at the end of this round's output, not re-applied.)

- **autowork_daemon self-heal/inactivity spawns bypass `spawn_agent` and launch `agy` with no `cwd=` at repo root — the incident's most likely vector** ({R3,R4,R5}): the §3.6 claim that relocation "fires for all three [agents]" was FALSE for the two daemon spawns (`autowork_daemon.py:674`, `:1718`), which build their own `agent_cfg`/`work_dir` and never touch `spawn_agent`/`_build_agent_env`. **Newly integrated:** new §3.8 (cwd + shared-`agent_work_dir` repoint of `:655`/`:1679`, prompt scrub at `:649`, daemon inbox target staging, antigravity/MCP coupling); §3.6 narrowed; §1 root-cause adds the second launch path; §3.1 helper must serve the daemon sites; §6 adds §6.4b daemon containment tests; §7 resume gate now requires green §6.4b for both daemon spawns and keeps `autowork.enabled: false`.
- **Apply path imposes NO `files_touched`/`harness/**`/`config/**` scoping; §6.2 tested a control that does not exist** ({R1,R4,R5}): verified all three commit paths (`git_integration.py:587`, `:729-746`, `:1010`) check only `relative_to(worktree_root)`, with `control.require_approval: []` — so a `harness_self_fix` manifest naming `harness/orchestrator.py` auto-commits regardless of CWD isolation. **Newly integrated:** §1a "OPEN/ACTION" aside elevated to first-class §1b (per-path `files_touched` membership + `harness/**`/`config/**` operator-approval gate); §6.2 restated as depending on §1b (RED against current code); §7 lands §1b in the same atomic change before §6.2 can pass; §1a also corrected re the partial (namespace-only) `_vcmd_scrubbed_env` and the SECOND vcmd site (`orchestrator_worker.py:536`).

---

## 1. Why this is needed (root cause recap)

- `spawn_agent` (`harness/orchestrator.py:290`) launches agents with **no `cwd=`** → CWD = repo root → agy's "workspace" is the whole live project. **`spawn_agent` is NOT the only launch path:** `harness/autowork_daemon.py` has TWO self-contained self-heal spawns (`:674`, `:1718`) that bypass `spawn_agent` entirely and also launch `agy` with no `cwd=` at repo root — and whose prompts explicitly instruct the agent to write `brief_hooks_*.md` and edit the auto-promote allowlist in the live tree. These are the incident's most likely vector; see §3.8.
- The agy BeforeTool gate (`config/gemini_settings.json` → `harness/hooks/gemini/pre_tool.py`) **never loads**: `gemini` is launched as bare `agy -p --sandbox` (no settings wiring), `.gemini/settings.json` is absent in-repo, `GEMINI_PROJECT_DIR` is never set, and agy doesn't read the harness-invented `JANUSMASK_GEMINI_SETTINGS`. **Evidence (corrected):** there are **zero gemini hook-ledger files** (`state/sessions/gemini_*.ledger.jsonl` — none), and `logs/gemini_stream.jsonl` positively shows the agent freely running gated-by-design commands (`python -c …`, `cat << EOF > test_original.py` into CWD=repo) with no interception. (NOTE: the earlier "0 hook denials in `logs/gemini_stream.jsonl`" claim was the wrong artifact — that file *does* contain 23 `deny` substrings, but they are agent submission CONTENT, not BeforeTool decisions; hook decisions go to the ledger, never the stream log.)
- Even if the gate loaded, `_SHELL_ALLOW` (`pre_tool.py:48`) permits arbitrary code (`python -c`) and unscoped file writes (`cat<<EOF >`, `tee`, `cp`, `mv`, `chmod`, `ln`). See §3.3 — but note (per §2.4) the allowlist is not the code-exec barrier even after hardening, because `pytest` collection runs arbitrary Python.
- `claude` runs with `--settings config/claude_worker.json --setting-sources ''` denying `Bash`/`Edit`/`Write`/`Agent`, which contains the *claude agent process*. **This does NOT mean "claude needs no change":** the incident's blast radius is the SUBMISSION-APPLICATION path (§1a), which is independent of what tools the agent may call. Either agent — claude included — can emit a `__JANUSMASK_MANIFEST__`/`__JANUSMASK_PATCHES__` targeting `harness/*.py` that the harness writes and `git commit`s. The "claude needs no change" reassurance has been deleted as the most dangerous false claim in the original draft.

## 1a. Threat model (added — isolation ≠ safety)

CWD/shell isolation contains the **agent process during synthesis**. It does NOT make the **submitted code** trustworthy, and it does NOT close the submission-application surface:

- A submission's `code` can be `__JANUSMASK_MANIFEST__ = {rel_path: source}` (`orchestrator.py:790`) or `__JANUSMASK_PATCHES__` (`orchestrator.py:787`). The harness writes these to repo paths — including `harness/*.py` — then `git add`/`git commit`s in the staging worktree (`commit_accepted_output` / `_commit_accepted_output_multi` / `_commit_accepted_output_patches`, `git_integration.py:495-761`). For `meta_task_type: harness_self_fix` this is the SANCTIONED path. Relocating CWD does nothing here.
- The accepted submission is later **executed**: `_auto_commit_accepted` → `commit_accepted_output` (`orchestrator.py:1443`) then runs the task's `verification_command` via `subprocess.run(..., shell=True, cwd=staging_path)` (`orchestrator.py:1511`). That execution — not synthesis — is the real arbitrary-code-execution surface.
- **The authoritative safety boundary is therefore unchanged by this plan:** dual-agent agreement + differential fuzzing + verification + `files_touched`/manifest-path scoping. **CONFIRMED HOLE (now a first-class deliverable — see §1b):** the apply path does NOT restrict manifest/patch target paths at all. All three commit paths (`commit_accepted_output` single-file `git_integration.py:587`, `_commit_accepted_output_multi` `:723-746`, `_commit_accepted_output_patches` `:1010`) check only `target_path.relative_to(worktree_root)` (escape-the-worktree guard) and nothing else — no `files_touched` membership check, no `harness/**`/`config/**` block, and `control.require_approval` is `[]` (config.yaml:65). So ANY submission naming `harness/orchestrator.py` commits cleanly — independent of CWD isolation. This is the dominant remaining hole; §3.x (CWD/shell) does nothing against it.
- The `verification_command` runs `shell=True, cwd=staging_path` (a full harness checkout). Its env is only PARTIALLY scrubbed: `_vcmd_scrubbed_env()` (`orchestrator.py:2026-2053`) drops only `JANUSMASK_*` keys and deliberately KEEPS PATH/HOME/everything else (it is a namespace scrub, NOT a clean env). There are TWO vcmd execution sites: `orchestrator.py:1511` and `harness/orchestrator_worker.py:536` (`/bin/bash -c 'set -o pipefail; <vcmd>'`, `env=scrubbed_env`). Any vcmd hardening must cover BOTH; do not describe the env as "scrubbed" without this caveat.

## 1b. Apply-path target-scoping (first-class deliverable — the dominant residual hole)
Verified against live code: the manifest/patch apply path imposes NO target-path constraint beyond "stays inside the worktree." This is the actual rogue-edit incident vector and is independent of every §3.x CWD/shell control. This section is a required deliverable of THIS plan, not an aside.

Required change — in all three commit paths, AFTER the existing `relative_to(worktree_root)` check (`git_integration.py:587`, `:729-736`, `:1010`):
1. Assert each accepted `rel_str` is a member of the task's resolved `files_touched` (use `_resolve_files_touched`, `orchestrator.py:1138`). Reject any target outside the declared set.
2. Reject any target matching `harness/**`, `config/**`, or `scripts/**` UNLESS `meta_task_type == harness_self_fix` AND an explicit operator-approval gate fired (`control.require_approval` is `[]` today — wire it for these path classes).

Until this lands, a `harness_self_fix` manifest targeting `harness/orchestrator.py` WILL auto-commit. §6.2 tests exactly this gate, so §6.2 cannot pass until §1b lands (see §6.2 / §7 sequencing).

## 2. Design (defense in depth — no single point of failure)

1. **Isolated working directory OUTSIDE the repo** *(necessary, NOT sufficient)*. Move per-agent workdirs to `../JanusMaskJR_agentwork/…` and launch each agent with `cwd=work_dir`. Effect: `git` can't auto-discover `.git` by walking up from CWD, and bare *relative* paths (`harness/orchestrator.py`) no longer resolve into the repo. **This does NOT sandbox the filesystem** — the agent can still `cat`/`open()` an absolute repo path, and the prompt itself hands it absolute `{STATE_DIR}` paths under the repo. Real read/write *prevention* needs a loaded hook (§3.3, which never loads for bare agy today) or an OS sandbox (bind-mount/`unshare`/seccomp making the repo read-only). Treat relocation as raising the bar, not as a jail.
2. **Stage read context into the workdir** instead of granting repo access. The task spec is already copied to `inbox/` by `_stage_inbox`. For partial-edit (`__JANUSMASK_PATCHES__`) / multi-file (`__JANUSMASK_MANIFEST__`) tasks, the agent must read the CURRENT contents of its targets. **This staging does NOT exist yet (see §2.2/§3.5) and partial-edit tasks will REGRESS the moment CWD leaves the repo unless §3.5 lands first.**
3. **Project-scoped agy config/home** *(would load the gate; UNRESOLVED)*. ⚠️ see §5. The design does **not depend** on this loading. Note (§8) that a HOME override interacts with `_boost_antigravity_mcp_config`.
4. **Harden `_SHELL_ALLOW`** — drop `python -c` and `python harness/sandbox.py`. **This is NOT the code-exec barrier:** `pytest` / `python -m pytest` remain and auto-import `conftest.py`/plugins/`pytest.ini` as arbitrary Python at collection. "deny git" is NOT a new control (already default-denied; git was never in the allowlist — the incident commit happened because the hook never ran). The allowlist hardening only matters *if the gate loads* (§5 unresolved) — for today's bare-`agy` runs it is inert.
5. **agy `--sandbox` is NOT counted as a barrier.** `agy --help` documents it only as "Run in a sandbox with **terminal restrictions** enabled" — this suggests TTY/terminal restriction, with NO evidence of filesystem or network confinement. Until §6 empirically probes it, **assume `--sandbox` provides NO filesystem isolation.**
6. **Vendored binaries** under `JanusMaskJR/.agents/` (version-pinned; not for isolation). Must cover all four agent commands (§4).

## 3. Concrete diffs (illustrative — exact lines re-confirmed at apply time)

### 3.1 Relocate workdir outside repo — must be a SHARED helper used by ALL spawn sites
The workroot computation must be a single shared helper (e.g. `harness/paths.py: agent_work_dir(agent, session_slug) -> Path`) so the orchestrator, the two `autowork_daemon.py` spawn sites (§3.8), and every other consumer agree. (NOTE: `agent_work_dir` / `JANUSMASK_AGENT_WORKROOT` are net-new — they do not exist yet.) Relocating only the orchestrator's `_build_agent_env` (orchestrator.py:212) DESYNCS the daemon spawn sites (which independently set `JANUSMASK_WORK_DIR = state_dir/'workdirs'/...` at `:656`/`:1680`) and the other consumers that independently derive `state_dir/'workdirs'` (see §3.7/§3.8). Do not apply a partial relocation — that intermediate state is *more* broken than the status quo.

```diff
-    work_dir = Path(state_dir) / 'workdirs' / agent / session_slug
+    # Agent workdirs live OUTSIDE the repo so an agent launched with
+    # cwd=work_dir cannot reach the live source tree by relative path and
+    # `git` cannot auto-discover the repo's .git by walking up from CWD.
+    # (This is NOT a filesystem jail — see §2.1.) Single source of truth:
+    work_dir = agent_work_dir(agent, session_slug)   # harness/paths.py helper
```
The `agent_work_dir` helper resolves `JANUSMASK_AGENT_WORKROOT` (default `PROJECT_DIR.parent / 'JanusMaskJR_agentwork'`) and MUST be the same function the hook-side fallback (`harness/hooks/_env.py:51`) and watchers use — see §3.7.

### 3.2 `harness/orchestrator.py` — set `cwd` on spawn (`spawn_agent`, :290)
```diff
-    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env, start_new_session=True)
+    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
+        text=True, env=env, start_new_session=True,
+        cwd=str(Path(env['JANUSMASK_WORK_DIR'])))
```
*(Verified anchors: workdir computed at `orchestrator.py:212`; `JANUSMASK_WORK_DIR` set at `:213`; `Popen` at `:290`; `proc._work_dir` at `:291`; `poll_for_submission` reads `getattr(proc,'_work_dir')` at `:378`. The Path-B `work_dir/outbox` poll and `proc._work_dir` DO follow the relocation. But "the submission flow follows the relocation automatically" is FALSE as a general statement — Path A under `state_dir` is unaffected only because it's absolute, and other pickup paths break: see §3.7. The staging-worktree commit model `<repo>_staging` is unaffected because it's a repo sibling, same as the new agentwork dir.)*

### 3.3 `harness/hooks/gemini/pre_tool.py:48` — harden `_SHELL_ALLOW`
```diff
-_SHELL_ALLOW = [re.compile('^pytest(\\s|$)'), re.compile('^python3?\\s+-m\\s+pytest(\\s|$)'),
-  re.compile('^python3?\\s+-c\\s+'), re.compile('^python3?\\s+harness/sandbox\\.py(\\s|$)'),
-  re.compile('^cat\\s+(?:-\\s+)?<<'), re.compile('^tee(\\s|$)'), re.compile('^mkdir(\\s|$)'),
-  re.compile('^chmod(\\s|$)'), re.compile('^touch(\\s|$)'), re.compile('^cp(\\s|$)'),
-  re.compile('^mv(\\s|$)'), re.compile('^ln(\\s|$)'),
-  re.compile('^rm\\s+-?[a-zA-Z]*\\s+(?:/tmp/|tests/fixtures/)')]
+# DEFAULT POSITION: drop the write verbs (tee/cp/mv/ln/cat<<EOF). Agents
+# submit ONLY via the write_file -> outbox path, which is already gated by
+# `_decide_write_or_replace`; they do not need shell file-redirection.
+_SHELL_ALLOW = [re.compile('^pytest(\\s|$)'),
+  re.compile('^python3?\\s+-m\\s+pytest(\\s|$)'),
+  re.compile('^mkdir(\\s|$)'), re.compile('^touch(\\s|$)')]
```
Honest notes on this hardening:
- **`pytest` / `python -m pytest` are retained and ARE arbitrary code.** pytest auto-imports `conftest.py`, `pytest.ini`, and installed/local plugins from rootdir at collection — an agent that writes a `conftest.py` into its workdir and runs `pytest` gets code execution before any test runs. The allowlist is therefore NOT the code-exec barrier. If pytest must stay, run it as `pytest -p no:cacheprovider --noconftest` (or in the existing `embedded_test_runner` tempdir sandbox, `embedded_test_runner.py:133`, which already uses an isolated `cwd=td_path`). Containment of code-exec relies on CWD-outside-repo + (unverified) `--sandbox` + the OS, not on this list.
- **"deny git" removed from the mitigation list** — `_decide_shell` (`pre_tool.py:150`) already default-denies anything not in `_SHELL_ALLOW`, and `git` was never in it. Stating "deny git" as a new control was a no-op restatement. The real residual git/exec reach is INDIRECT via pytest/subprocess; rely on CWD-outside-repo so `git` finds no `.git`.
- **`python harness/sandbox.py` removal is safe** — the synthesis self-test path imports `sandbox_smoke.smoke_import` in-process (`orchestrator.py:38` / `orchestrator_worker.py:97`); agents do not self-test via that script.
- **If tee/cp/mv/ln are kept** (NOT the default), the path-scope guard must be a CONCRETE, reviewed diff — not "drafted at apply time." Requirements: (a) the existing `cat` guard already exists — `_CAT_BARE_RE` (`pre_tool.py:221`) + `_is_in_read_allowed_roots` (`pre_tool.py:223-230`) + loop at `:143-145` — reuse it, do not reinvent; (b) but read-allowed roots (`pre_tool.py:50-52`: work_dir, state_dir, docs, briefs) are WRONG for write scope — a write guard must be narrower (work_dir + /tmp only); (c) parse with `shlex`, reject any token containing `$`, backtick, `<`, `>`, `|`, `&`, `;`, handle per-verb arg grammars (`tee -a`, `cp -r`, `mv -t DIR`, `ln -sf`), resolve every remaining token with symlink resolution against the write root; (d) ship unit tests for each verb/flag/glob/`$VAR` case. A naive `.split()` scoper yields both false-denies and false-allows (`cp $HOME/x ./y`, `tee "$(...)"`).

### 3.4 `harness/config.yaml` — vendored binary paths (use `${PROJECT_ROOT}`, repoint ALL agy/claude agents)
```diff
   gemini:
     args:
     - -p
     - --sandbox
-    command: agy
+    command: ${PROJECT_ROOT}/.agents/agy/agy
```
- **`${PROJECT_DIR}` does NOT expand** — `_interpolate_config_paths` (`orchestrator.py:96-115`) only substitutes `${CONFIG_DIR}`, `${PROJECT_ROOT}`, `${STATE_DIR}`. `PROJECT_DIR` is merely an import alias inside orchestrator.py (`from harness.paths import PROJECT_ROOT as PROJECT_DIR`, `orchestrator.py:42`), NOT a config token. The literal `${PROJECT_DIR}/.agents/agy/agy` would reach `subprocess.Popen` and die with `FileNotFoundError`. Use `${PROJECT_ROOT}` (verified to recurse into `command` values). The "confirmed at apply time" hedge is removed — this was knowable and wrong.
- **Repoint ALL FOUR agent commands**, not just gemini: `gemini` (`-p --sandbox`), `antigravity` (`-p --dangerously-skip-permissions --sandbox`, config.yaml:1-7), `claude_fallback` (`-m claude-opus-4.6 -p --dangerously-skip-permissions --sandbox`, config.yaml:24-31 — all three are `command: agy`), and `claude` (`command: claude`, config.yaml:8-23). Deferring claude/fallback "once verified" leaves the LEAST-contained agent (`claude_fallback`, which runs agy with `--dangerously-skip-permissions`) on the system binary.

## 3.5 `inbox/targets/` staging — **NOT YET BUILT** (must land BEFORE relocation)
§2.2 describes this in present tense but **no such code exists** (`grep -rn "inbox/targets" harness/` → nothing). The only stager is `_stage_inbox` (`orchestrator.py:2400-2454`), which copies exactly ONE file per mode (`_INBOX_SOURCES_BY_MODE`, synthesis→`task.json` only). Today partial-edit/multi-file tasks work ONLY because CWD=repo and the gate never loads, so bare `harness/orchestrator.py` resolves. The moment §3.2 sets `cwd=work_dir` outside the repo, that path stops resolving and partial-edit/`harness_self_fix`/multi-file synthesis silently lose their targets.

Required before relocation:
1. Extend `_stage_inbox` to copy each `files_touched` entry into `work_dir/inbox/targets/<rel>` (read-only).
2. Rewrite `prepare_task_prompt` (`orchestrator.py:780`) to point the agent at `{WORK_DIR}/inbox/targets/...` instead of bare repo-relative paths, and to read the task spec from `{WORK_DIR}/inbox/task.json` instead of `{STATE_DIR}/tasks/...` (the latter is an absolute path INTO the repo — see §2.1/§5).
3. Confirm the gemini read-allowed roots (`pre_tool.py:50-52`) cover `work_dir` (they do) and update `_relpath_in_outbox` / read-root logic so `inbox/targets/` is readable.

## 3.6 All three agy-backed agents (`gemini`, `claude_fallback`, `antigravity`)
The CWD relocation in §3.1/§3.2 keys on `agent` generically via `_build_agent_env`→`spawn_agent`, so it DOES fire for all three agents *that are launched through `spawn_agent`* — i.e. the orchestrator-spawned synthesis/planning agents (planner `adversarial_review.py:122` `spawn_agent` and `blind_draft.py:143` / `reconciliation.py:104` `run_both_agents` go through this path too, so they ARE covered). **It does NOT fire for the two `autowork_daemon.py` self-heal spawns — they bypass `spawn_agent` entirely (see §3.8).** Confirm coverage of the orchestrator-spawned set in §6. Agent-specific work was gemini-only and must extend:
- `claude_fallback` and `antigravity` both pass `--dangerously-skip-permissions`, which auto-approves every tool — strictly more dangerous than gemini. Decide whether that flag is acceptable for fallback agents; if not, remove it. `run_both_agents` actively spawns `claude_fallback` when Claude returns None (`orchestrator.py:507-512, 530-536`).
- Confirm which settings/hooks each agy agent loads (likely none, same as gemini — so §3.3 hardening is inert for them too).
- `antigravity` triggers `_boost_antigravity_mcp_config` (`orchestrator.py:275-276`) which writes a janusmask MCP server into `~/.gemini/antigravity-cli/mcp_config.json` — an MCP path that re-grants tool surface and interacts with any §5 HOME override (§8). Evaluate whether the MCP boost reopens a write/exec channel.

## 3.7 Repoint EVERY `state/workdirs` consumer (relocation is not automatic)
§3.2's note that consumers "follow the relocation automatically" is FALSE except for the orchestrator's own `proc._work_dir` poll. The following independently derive `state_dir/'workdirs'` and BREAK silently after relocation — each must be repointed to the shared `agent_work_dir` helper (§3.1), or the workdir must stay under `state/` and isolation achieved differently:
- `scripts/impl_outbox_watcher.py:200` — `workdirs_root = state_dir / "workdirs"`; the independent submission-pickup watcher finds nothing after relocation → drain/async submissions lost.
- `harness/autowork_daemon.py:540-548` — `_collect_traceback` reads agent `outbox/error.md` from `state_dir/'workdirs'/<agent>/...` → self-heal context degrades silently.
- `harness/planner/blind_draft.py:30-34` — reads plan drafts from `<agent_dir>/workdirs/<agent>/.../outbox/<filename>` → planning breaks.
- `harness/hooks/_env.py:51` (and per-agent `claude/_env.py`, `gemini/_env.py`) — fall back to `state_dir()/'workdirs'/<a>/<sid>` when `JANUSMASK_WORK_DIR` is unset. Authoritative when the var IS set, but any stray spawn/test that omits it resolves a DIFFERENT tree than the orchestrator created → submission persisted to one place, polled from another. Make the fallback derive from the same `agent_work_dir`/`JANUSMASK_AGENT_WORKROOT`, OR hard-fail when `JANUSMASK_WORK_DIR` is absent.
- `scripts/bootstrap.sh:49` pre-creates `state/workdirs` — harmless but now dead; update for consistency.

NOTE on `harness/autowork_daemon.py`: it is BOTH a `state/workdirs` read-consumer (`_collect_traceback`, :540-548) AND an active agent-SPAWN site (two `subprocess.Popen` launchers — see §3.8). The :540-548 read-path repoint is necessary but NOT sufficient; the spawn sites need their own `cwd` + workroot fix.

## 3.8 `harness/autowork_daemon.py` — the two self-heal agent spawns that BYPASS `spawn_agent` (this is the incident's most likely vector)
**Without this section the plan does not prevent the original incident.** The incident profile — an agy agent autonomously editing harness source in the live repo and committing — matches the autowork self-heal / planning spawn far better than the orchestrator synthesis path. The daemon has TWO self-contained agent launchers that NEVER call `spawn_agent` / `_build_agent_env` / `_build_agent_command`, so the §3.1/§3.2 `cwd=` relocation does NOT reach them:

- `_escalate_to_autobrief` (retry-budget-exhausted self-heal) — builds its own `agent_cfg = {'command': 'agy', 'args': ['-p','--sandbox']}` fallback (`autowork_daemon.py:627`), its own `work_dir = state_dir/'workdirs'/agent/session_slug` (`:655`), sets `env['JANUSMASK_WORK_DIR']` to it (`:656`), and launches `subprocess.Popen(cmd, env=env)` with **NO `cwd=`** (`:674`). Its prompt (`:649`) **explicitly instructs the agent to write `brief_hooks_{task_id}_fix.md` at repo root and append a line to `state/control/autowork/auto_promote.allowlist`** — the harness itself directs a CWD=repo agent to mutate the live tree.
- The inactivity-watchdog self-heal — identical pattern: own `agent_cfg` fallback (`:1652`), own `work_dir = state_dir/'workdirs'/...` (`:1679`), `env['JANUSMASK_WORK_DIR']` (`:1680`), bare `subprocess.Popen(cmd, env=env)` with no `cwd=` (`:1718`).

The agent for both is resolved from `control.autobrief_default_agent`; `load_config` flips that to `antigravity` whenever `synthesis.antigravity_mode` is true (`orchestrator.py:125-126`), so these can spawn `agy --dangerously-skip-permissions` at repo root.

**Required (same atomic change as §3.1–§3.7):**
1. Repoint the `work_dir` producers at `autowork_daemon.py:655` and `:1679` to the shared `agent_work_dir(agent, session_slug)` helper (§3.1), and set `env['JANUSMASK_WORK_DIR']` from it — so the daemon agrees with the orchestrator and the `_env.py` fallback (otherwise the daemon writes/polls one tree while the orchestrator uses another).
2. Add `cwd=str(work_dir)` to BOTH `Popen` calls (`autowork_daemon.py:674`, `:1718`) — or, preferably, route both through the shared `spawn_agent` helper so there is one launch path.
3. Scrub the self-heal prompt (`autowork_daemon.py:649`) so it no longer instructs repo-root writes / `auto_promote.allowlist` edits; the agent should write only via its outbox and stage any allowlist change for operator review.
4. Stage `files_touched` targets into the daemon's inbox too (it currently stages a `brief.json`, `:663-664`/`:1687-1688`, with NO targets) — see §3.5 — or explicitly scope daemon self-heal to no-target tasks.
5. HOME/MCP coupling (§8): when the daemon agent resolves to `antigravity`, the daemon passes `env = dict(os.environ)` straight through with NO `_boost_antigravity_mcp_config` call and no settings/hook wiring; decide whether the boost must run for consistency or whether `antigravity` is forbidden as a self-heal agent.

## 4. Vendoring (commands — run only after approval)
```bash
# claude-code, pinned, project-local. NOTE: this yields a SHIM at
# node_modules/.bin/claude that REQUIRES a node runtime on PATH at spawn
# time — it is NOT a self-contained binary. Pin node too (or document the
# runtime dependency) or the "pinned" claude can break when node drifts.
npm install --prefix .agents/claude-code @anthropic-ai/claude-code@<PINNED_VERSION>   # <-- resolve the version; placeholder is not applyable

# agy (Antigravity) — self-contained Go binary (current: /home/xnihil0zer0/.local/bin/agy, version 1.0.3):
mkdir -p .agents/agy && cp "$(command -v agy)" .agents/agy/agy
sha256sum .agents/agy/agy        # record SHA256 for the pin
.agents/agy/agy --version        # confirm the version-probe invocation works (record output)

# keep binaries out of git:
echo ".agents/" >> .gitignore   # + a scripts/setup-agents.sh to reproduce
```
Repoint ALL FOUR commands in config.yaml in the SAME diff (§3.4): `gemini`, `antigravity`, `claude_fallback` (all agy) and `claude`. Do not defer claude/fallback.

## 5. OPEN QUESTION — pointing agy at a project-scoped config/home
`agy` exposes **no `--settings`/`--config`/`--cwd` flag** (only `--add-dir`, `--sandbox`, `--dangerously-skip-permissions`). It stores config under `~/.gemini/` (has `config/`, `projects/`). Redirecting that without overriding `HOME` is not known to be possible; overriding `HOME` is heavy-handed and **collides with `_boost_antigravity_mcp_config`** (§8) — it would change where that function writes the janusmask MCP config, so the antigravity subprocess (reading the OVERRIDDEN HOME, or not) would fail to find/register the MCP server, and agy auth/history under the real `~/.gemini` would be lost (likely breaking non-interactive `-p`). **The design is safe without this** — but two honest caveats vs. the original:
- agy `--sandbox` is NOT a filesystem barrier (§2.5); CWD relocation is necessary-not-sufficient (§2.1). So "isolation comes from §2.1/§2.4 + `--sandbox`" overstated the available barriers; absent a loaded hook or OS sandbox, the strongest current guarantees are "git can't auto-discover .git" + "relative paths don't resolve into the repo."
- The gate-load sub-thread (§2.3) cannot succeed for bare `agy` without a config-redirect mechanism agy does not expose. Do not imply §3.3 protects today's agy synthesis runs — it does not, because the hook never executes for them.

**Required empirical probe (in §6):** under `--sandbox`, attempt (i) a file write OUTSIDE CWD by absolute repo path, (ii) `git -C <repo> commit` and `git commit` from CWD, (iii) an absolute-path READ of `{STATE_DIR}/tasks/...` and `inbox/` — and record the actual results. The original §5 probe only covered config/HOME, not filesystem scope.

## 6. Verification smoke-test (gates resuming the pipeline)
1. **Negative (out-of-band isolation):** launch each agy agent in an isolated workdir with a prompt that tries to write the harness via (a) *relative* `harness/orchestrator.py`, (b) **absolute** `/home/.../JanusMaskJR/harness/orchestrator.py`, (c) **parent-relative** `../JanusMaskJR/harness/x.py`, (d) `git commit` from CWD, (e) `git -C <repo> commit`. Assert each is REJECTED and the main tree is byte-identical / `git log` unchanged. Run each both with and WITHOUT `--sandbox` to isolate which control actually blocks what (do not let an unrelated agy refusal masquerade as isolation).
2. **Submission-application (the real incident vector):** submit a `harness_self_fix` `__JANUSMASK_MANIFEST__` targeting `harness/x.py` and assert it is NOT auto-committed without approval / is path-constrained. **This test ONLY passes once the §1b apply-path gate is built** — against current code there is no such constraint and the manifest WOULD auto-commit (that is the bug). So §6.2 depends on §1b landing first (§7); against today's code §6.2 is a RED test documenting the unaddressed hole. A green §6.1 alone gives FALSE confidence — a manifest/patches submission rewrites harness files through the sanctioned path regardless of CWD isolation.
3. **Positive (no regression):** (a) re-run one real RB synthesis task end-to-end; assert it still accepts and the only main-tree change is the intended staged integrate commit. (b) Run a partial-edit/`__JANUSMASK_PATCHES__` task and assert the agent can still READ its target (via §3.5 `inbox/targets/`) and produce a valid patch. (c) Assert the agent can still read `{STATE_DIR}/tasks/...` and `{WORK_DIR}/inbox/`.
4. **Consumer/relocation coverage:** assert submission pickup still works after relocation for `impl_outbox_watcher` and `blind_draft` (not just the orchestrator poll), and that `_collect_traceback` still finds agent error reports.
4b. **Daemon self-heal spawn containment (the incident path):** trigger BOTH `autowork_daemon.py` spawns — the retry-budget self-heal (`:674`) by exhausting a task's retry budget, and the inactivity watchdog (`:1718`) — and assert each launches with `cwd != repo-root` (cwd == the relocated `agent_work_dir`), the main tree is byte-identical, `git log` is unchanged, and the scrubbed prompt no longer wrote `brief_hooks_*.md` / edited `auto_promote.allowlist` out-of-band. A green §6.1/§6.3 on the orchestrator path does NOT cover these — they bypass `spawn_agent`.
5. **Gate (only if §5 ever resolves):** a forbidden tool yields a `deny` in the gemini hook LEDGER (`state/sessions/gemini_*.ledger.jsonl`), not the stream log.

## 7. Sequencing
Land §1b (apply-path target-scoping) + §3.1–§3.8 + §4 as ONE atomic change (so there is no half-relocated state — a partial apply that fixes the orchestrator but not the §3.7 consumers or the §3.8 daemon spawns is *more* broken than the status quo). §1b must land before §6.2 can be a passing gate (today §6.2 is RED). → run §6 → if green, resume RB drain (d/e) → then Step 3 (lift `full_stop`). `full_stop` stays `halted` until §6 passes. **The resume gate REQUIRES a green containment assertion for BOTH `autowork_daemon.py` self-heal spawns (§6.4b: `:674` and `:1718`) in addition to the orchestrator path** — the daemon self-heal path is the closest match to the original incident, so a green orchestrator-only §6 would re-arm exactly the vector this plan exists to close. Keep `autowork.enabled: false` (config.yaml:44) until §6.4b is green.

## 8. Also flag during this work
- `orchestrator.py:219` `home_key = "HO" + "ME"` — this is **live, load-bearing code**, NOT dead obfuscation. It is `_boost_antigravity_mcp_config` reading `os.environ["HOME"]` to write `~/.gemini/antigravity-cli/mcp_config.json` on EVERY `antigravity` spawn (`orchestrator.py:218-256`, invoked at `:275-276`). Behavior is benign, but calling it "the same evasion style as the rogue `exec()`" overstated it. **Coupling to track:** any §5 HOME override must be reconciled with this function's `os.environ["HOME"]` read, or the antigravity MCP boost writes to the wrong HOME and the MCP server fails to register. Recommend de-obfuscating `"HO"+"ME"` → `os.environ["HOME"]` in the same change so future audits don't re-flag it.
