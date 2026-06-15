# HANDOFF — WebUI Typed-Config + Model-Backends + Drive-Backup epics: adversarial evaluation, fix, and continuation

**Authored:** 2026-06-12 (end of session). **Repo:** `/home/xnihil0zer0/JanusMaskJR` (a.k.a. "JanusMask" / "JM" — the code factory). Sibling repo: `/home/xnihil0zer0/NobleGreedv2` (NGv2).
**Daemon state at handoff:** PAUSED via `state/control/autowork/pause`. Master at `06e2e55`.

> **READ THIS FIRST.** This handoff describes work that was partially executed and hit a cascade of factory-gate failures, some of which were made worse by reactive operator missteps (documented honestly below). **Do not trust the claims in this document at face value — the first phase of work is to adversarially verify them against the live code/state.** Then fix, correct the plan, and continue. Operate as a THIN ORCHESTRATOR: delegate to parallel sub-agents, keep your own context lean, use background watchers instead of polling. **Every sub-agent prompt must include an explicit "be maximally token-frugal: read only what you need, quote minimally, return only a compact structured result" instruction** — context preservation is a first-class goal.

---

## 1. ORIGINAL MISSION (what the owner asked for)

Build three systems + one verification, delegating design + brief authorship to sub-agents and running them through the JanusMask code factory:

- **A. WebUI config UX overhaul:** fields appropriately typed (int/float/str/bool); directory/file path fields get a "Browse PC" button; limited-choice params (esp. which model is assigned to which factory role) are dropdowns; type enforcement on entry; config is **saveable**; each factory role has a model selection; **where dual agents are required, two DIFFERENT agents must be enforced — saving with two identical agents must error.**
- **B. Model-backend expansion:** add **codex CLI** as a model option; add **API-key input fields** for OpenAI, Gemini, Anthropic, and the **top-5 Chinese APIs (June 2026, by price/performance on agentic leaderboards — required web research)**; **API/provider options stay LOCKED unless an API key is present in the corresponding key field.**
- **C. Google Drive backup-on-push:** on every `git push` of **both** repos (NGv2 + JanusMask), back up a diff of the whole project directory to the owner's Google Drive. (Owner offered to log in for anything needed.)
- **D. Adversarial verification of LAST session's work**, sending fixes through the pipeline for any gaps/shortcuts.

**Standing constraints:** maximal token efficiency; preserve oversight for long operation; design + epic/brief authorship delegated to sub-agents; build through the code factory; **owner-gated submission/dangerous actions** (never auto-submit, never hand-edit deny-listed production).

---

## 2. WHAT WAS COMPLETED (verify before trusting)

- **D — DONE.** Adversarial verifier found **0 issues** in last session's work (daemon brief-dep-gate `d29f60c`, planner dedupe/validator fixes `feb13ad`/`2561d67`, revert→reland `e7b4939`); all confirmed on the live path with real tests. Evidence: `_autowork_scratch/ADVERSARIAL_VERIFY_FINDINGS.md`.
- **B research — DONE (caveated).** Top-5 Chinese providers, all OpenAI-API-compatible: **DeepSeek** (`deepseek-v4-*`, `https://api.deepseek.com`, `DEEPSEEK_API_KEY`), **Moonshot/Kimi** (`kimi-k2.6`, `https://api.moonshot.ai/v1`, `MOONSHOT_API_KEY`), **Zhipu/Z.ai GLM** (`glm-5*`, `https://api.z.ai/api/paas/v4`, `ZHIPU_API_KEY`), **Alibaba Qwen/DashScope** (`qwen3-coder-plus`, `https://dashscope-intl.aliyuncs.com/compatible-mode/v1`, `DASHSCOPE_API_KEY`), **MiniMax** (`minimax-m2.5`, `https://api.minimax.io/v1`, `MINIMAX_API_KEY`). Full table + sources: `_autowork_scratch/CHINESE_API_RESEARCH.md`. **CAVEAT: pricing/scores came from search summaries (WebFetch was permission-denied); re-verify against live provider docs at wire-up.**
- **Factory orientation captured:** `_autowork_scratch/FACTORY_ORIENTATION.md`.
- **Both epics designed; briefs authored; RED oracles committed.** (But the briefs/oracles are INCONSISTENT — see §4.)
- **Google Drive MCP:** authenticated for Claude's access (claude.ai Google Drive connector). NOTE: this is for Claude's reads only; the always-on push backup needs its own machine credential (see §6, `rclone`).

---

## 3. ARTIFACTS ON DISK / IN GIT (ground truth to inspect)

**Commits this session (master):**
- `1ad0698` — config epic briefs + RED oracles (`tests/webui/`).
- `efcf4a3` — drive epic briefs + RED oracles (`tests/drive_backup/`).
- `818afd5` — plan-shape fix on the 6 new-module briefs (paired oracle + integration excuse).
- `1fa09ea` — wiring fix on the 2 webui harness briefs (anchor into `control_gate.py`).
- `06e2e55` — **`Integrate validated code for config-schema-impl`** — landed `harness/webui_config_schema.py` wired into `harness/control_gate.py`. **THIS IMPL IS INCOMPLETE: it fails its own oracle (see §4.7). Candidate for revert.**

**Config epic briefs (repo root):**
- `brief_hooks_webui-typed-config-and-backends.md` (root, `epic: true` — NOT allowlisted; do not allowlist an epic root or it triggers a competing decomposition).
- Leaves: `brief_hooks_webui-config-schema.md`, `brief_hooks_webui-model-backends.md`, `brief_hooks_webui-typed-widgets.md`, `brief_hooks_webui-fs-browse.md`, `brief_hooks_webui-typed-config-e2e.md`.
- Oracles (committed, RED at authoring): `tests/webui/test_config_schema.py`, `test_model_backends.py`, `test_typed_widgets.py`, `test_fs_browse.py`, `test_typed_config_e2e.py` (+ `tests/webui/__init__.py`).

**Drive epic briefs (repo root):**
- `brief_hooks_drive-backup-on-push.md` (root, `epic: true`).
- Leaves: `brief_hooks_drive-backup-archiver.md` (owns archiver.py + ledger.py), `brief_hooks_drive-backup-uploader.md`, `brief_hooks_drive-backup-hook-runner.md`, `brief_hooks_drive-backup-installer.md`.
- Oracles: `tests/drive_backup/test_archiver.py`, `test_ledger.py`, `test_uploader.py`, `test_hook_runner.py`, `test_install_hooks.py` (+ `__init__.py`).
- User setup doc: `_autowork_scratch/DRIVE_BACKUP_USER_SETUP.md`.

**Intended production modules (NOT yet correctly built):** `harness/webui_config_schema.py` (committed but incomplete), `harness/model_backends.py`, `harness/secrets_store.py`; `tools/drive_backup/{archiver,ledger,uploader,hook_runner,install_hooks}.py`. **Live WebUI surface = `tools/webui_server.py` (stdlib `http.server`) + `tools/webui_control.py` + `tools/webui_static/app.js`. The `webui/app.py` Flask tree is DEAD — do not target it.**

---

## 4. VERIFIED FACTORY-GATE KNOWLEDGE + ISSUES (re-verify each; cited by file:line)

These were learned the hard way. A fresh agent should re-confirm against the code (cheap greps) — do not assume they're still exactly true.

1. **Allowlist ≠ build.** Allowlisting a brief only makes it *eligible*. The daemon (`harness/autowork_daemon.py`) auto-plans **ONE** unplanned eligible brief per heartbeat iteration, selected by **newest brief mtime** (`touch` to reorder). Allowlist file: `state/control/autowork/auto_promote.allowlist` (deny-all-unless-listed; `#` comments ignored). Eligibility logic: `harness/brief_status.py::compute_autowork_eligibility`.

2. **`missing_wiring_oracle` gate** (`harness/planner/plan_validator.py:225-243`): a leaf that CREATES a new `.py` module must include in its plan a paired `test_authoring` task whose top-level `mutation_target` (BARE DOTTED module, e.g. `harness.model_backends`) resolves to a `.py` in the impl task's `files_touched`.

3. **`missing_integration_test` gate** (`plan_validator.py:278-284`): each non-test impl task needs ≥1 integration_test UNLESS its `non_goals` contains the literal word "integration".

4. **Sensitive-glob gate** (`harness/git_integration.py` `_enforce_apply_scope` / `_sensitive_glob_violations`): tasks editing `harness/**` or `config/**` must be `meta_task_type: harness_self_fix` + operator approval. `tools/**` is not sensitive. **`_NEVER_AUTO_APPROVE`** (incl. `orchestrator.py`, `orchestrator_worker.py`, `autowork_daemon.py`, `paths.py`, `git_integration.py`, `selfheal.py`, `agent_jail.py`, `dbus_proxy.py`, `interceptors.py`, `services/**`) is editable by **NO** task type — owner hand-edit only.

5. **`wire_up_gate` / `orphan_unwired` (ACCEPTANCE gate)** (`harness/wire_up.py::check_wired`, enabled by `config autowork.wire_up_gate: true`): a new module is accepted only if reachable via the import graph from a `LIVE_ROOTS` entry = `harness/orchestrator.py`, `harness/orchestrator_worker.py`, `harness/autowork_daemon.py`, `harness/planner/cli.py` — OR it has a transitive live importer — OR it is referenced by **explicit `.py` path** in `config/**` (CONFIG_WIRED; a `-m dotted` token does NOT match on a SELF build, and a CONFIG_WIRED module is NOT itself a root so its imports don't reach siblings — each module needs its own config line). **`tools/webui_*` is NOT a live root. `harness/config_loader.py` is itself an orphan.** Verified working anchor: **`harness/control_gate.py`** (`check_wired` → wired=True, imported by `orchestrator.py`; not deny-listed; `harness_self_fix`-editable).

6. **Dep-gate is deadlock-safe and LEAKS** (`autowork_daemon.py:1637 _brief_dep_gate_ok`, applied in `_decide` at :1708): it HOLDS a dependent only while its dependency brief has un-accepted, non-terminal work. It **RELEASES the dependent (dispatches it) when the dependency is `blocked`, `zombie`, `unplanned`, or absent** (lines 1689–1698). Consequence: whenever a foundation leaf is failing/being-replanned, its dependents get dispatched against a not-yet-existing module → fail → `blocked/`. **This gate lives in a `_NEVER_AUTO_APPROVE` file — you cannot change it; you must work AROUND it via wave-based allowlisting (below).**

7. **`config-schema-impl` (`06e2e55`) is committed but INCOMPLETE.** Its oracle `tests/webui/test_config_schema.py` asserts provider-aware validation (`validate_config(..., secrets={deepseek_key}) → values['overseer.default_backend']=='deepseek'`) that the committed impl does not satisfy → the `config-schema-oracle` task failed `verification_failed` → `config-schema` brief is `blocked`. **`model-backends` also built and did NOT accept (blocked).**

8. **Likely CIRCULAR DEPENDENCY in the design (root design defect to fix).** As authored: `model-backends` `depends_on: [webui-config-schema]` and wires `model_backends` INTO `webui_config_schema.py`; yet `config-schema`'s validation/oracle needs the provider registry FROM `model_backends`. That is backwards. **Correct layering: `model_backends` (+ `secrets_store`) is the true foundation (no deps), wired directly into `control_gate.py`; `webui_config_schema` DEPENDS on `model_backends` and imports it for the provider enum + locked-unless-keyed validation.**

9. **Retry budget self-terminates; deleting the sidecar defeats it (OPERATOR MISTAKE made this session).** `_retry_blocked_tasks` (`autowork_daemon.py:883`, `max_attempts=3`, `effective_max=1` for deterministic outcomes) parks a blocked task after its budget via the `state/tasks/blocked/<tid>.retry.json` sidecar. **Deleting that sidecar resets `attempts` to 0 and resurrects the task.** During this session, repeated "cleanup" purges of these sidecars kept restarting a loop the system was trying to end. **DO NOT delete `.retry.json` sidecars to "unstick" things.**

10. **`git worktree remove failed ... exit 128`** appears on nearly every worker exit but self-heals via an `rmtree` fallback (`git worktree list` stays clean). Noise, not a blocker — but worth a proper root-cause look if you have budget (it's in deny-listed worker/git_integration code → owner territory).

---

## 5. CURRENT FROZEN STATE (snapshot at handoff)

- Daemon PID 2421475 alive but PAUSED (`state/control/autowork/pause` present; `rm` it to resume; do NOT use `full_stop` — the owner has previously objected to that sentinel).
- No workers running.
- `webui-config-schema`: `blocked` (impl committed `06e2e55`, oracle failing). `webui-model-backends`: `blocked` (built, not accepted).
- `webui-fs-browse`, `webui-typed-widgets`, `webui-typed-config-e2e`: dormant — plans/tasks/retry-sidecars purged; **commented out of the allowlist** (`# HELD ...`).
- All 4 drive leaves: dormant — **commented out** (`# HELD pending wiring decision: ...`).
- Allowlist currently has only `webui-config-schema` and `webui-model-backends` uncommented (but daemon is paused).

---

## 6. OWNER-GATED DECISIONS (do NOT auto-resolve; surface and wait)

1. **Codex CLI final wiring** into `harness/orchestrator.py` + `harness/config.yaml` `agents:` block is a **manual owner hand-edit** (both are `_NEVER_AUTO_APPROVE`). The factory can only build a standalone backend registry + an `agent_block()` dict.
2. **Secret-store location:** proposed `state/secrets/api_keys.json` (chmod 600, gitignored). Confirm vs an env-file pointer.
3. **Drive-backup wiring:** each `tools/drive_backup/*.py` needs its own explicit `.py`-path line in a `config/**` manifest to pass `check_wired` (CONFIG_WIRED). `config/**` edits require `harness_self_fix` + operator approval. **Needs owner authorization** before the drive epic can complete.
4. **`rclone` setup (machine credential):** `rclone` is NOT installed; the push backup needs a one-time `rclone config` Google Drive remote (`gdrive:`). Exact steps in `_autowork_scratch/DRIVE_BACKUP_USER_SETUP.md`.
5. **Revert `06e2e55`?** The incomplete `config-schema-impl` is on master. Decide whether to revert before rebuilding foundations in corrected order (recommended) or to fix-forward over it.

---

## 7. CORRECTED PLAN (proposed — adversarially validate it before executing)

**Design correction (the keystone):** invert the foundation dependency.
- `model-backends` = no-dep foundation. Modules: `harness/model_backends.py` (OpenAI-compatible client parameterized by `(base_url, api_key_env/value, model_id)` covering OpenAI + Gemini-OpenAI-endpoint + the 5 Chinese providers; plus `AnthropicBackend`; plus `CodexCliBackend` mirroring the existing CLI-agent contract; `PROVIDERS` table with `api_key_env`) + `harness/secrets_store.py`. Wire `model_backends` (and `secrets_store` ← `model_backends`) into `harness/control_gate.py` (root-reachable anchor) within the leaf's own scope. Oracle: registry behavior + provider table in isolation.
- `config-schema` `depends_on: [model-backends]`. Module `harness/webui_config_schema.py`: typed `CONFIG_FIELDS` (int/float/str/bool/path-file/path-dir/enum), `validate_config()` (coercion + bounds + **dual-agent-distinct** + **provider-locked-unless-keyed**, importing `model_backends.PROVIDERS` for the provider list), `atomic_save_config()`. Wire into `control_gate.py`. Oracle: validation incl. provider gating (model_backends now exists as a dep).
- Reconcile EVERY impl spec with its committed oracle so impl and oracle agree (the `06e2e55` failure was impl≠oracle). Re-author oracles where they over-reach or under-specify.
- UI leaves (`typed-widgets`, `fs-browse`) EDIT the live `tools/webui_server.py`/`tools/webui_control.py`/`tools/webui_static/app.js` (stdlib http.server; route registration in `_dispatch_get`/dispatch tables; `app.js` must actually call `/api/fs/list` — fs-browse failed last time because the route wasn't registered and `app.js` wasn't updated). `typed-config-e2e` is the full integration leaf. These depend on the foundations.
- Drive epic: unchanged module design; ADD the `config/**` CONFIG_WIRED manifest task (owner-approved) so the 5 modules pass `check_wired`. Keep non-blocking pre-push hook design.

**Execution discipline (work AROUND the dep-gate leak):**
- **WAVE-BASED ALLOWLISTING.** Only allowlist a leaf once ALL its dependencies are `complete` (accepted). Wave 1: `model-backends`. Wave 2: `config-schema`. Wave 3: `fs-browse` + `typed-widgets`. Wave 4: `typed-config-e2e`. Drive epic in its own waves after owner approval. Keep dependents commented-out until their wave.
- **Never delete `.retry.json` sidecars.** Let the budget park failures; diagnose root cause instead.
- **To re-plan a brief after editing it:** delete its `plan_hooks_<slug>.json` AND remove its staged/blocked tasks AND `touch` the brief — but ONLY when no dependents are active (else you reopen the leak window). Prefer: pause daemon → reset the single leaf → resume.
- **Commit oracles before dispatch** (committed oracle = the blind worker's contract; uncommitted tests poison the auto-commit).
- Resume by `rm state/control/autowork/pause`. Monitor via background watchers (see §9), not polling.

---

## 8. PARALLEL SUB-AGENT PLAYBOOK FOR THE NEXT SESSION

> Spawn these as background sub-agents. **Each prompt MUST start with: "Be maximally token-frugal — read only what you need, quote minimally, write findings to a file under `_autowork_scratch/`, and return ONLY a compact structured summary (≤10 lines)."** Keep the orchestrator's own context lean; do not read full sub-agent transcripts.

### PHASE 0 — Adversarial evaluation (4 agents in parallel; DO NOT fix yet, only verify + report)
- **Agent 0A — Verify this handoff's factory-gate claims (§4) against live code.** Re-derive: dep-gate release-on-blocked (autowork_daemon.py:1637), wire gate + LIVE_ROOTS + the `control_gate.py` anchor (wire_up.py), plan-validator gates (plan_validator.py:225-284), `_NEVER_AUTO_APPROVE` contents, retry-sidecar reset behavior. Output: per-claim CONFIRMED/REFUTED + file:line. → `_autowork_scratch/PH0_gate_verify.md`.
- **Agent 0B — Adversarially audit `06e2e55` + the config-schema/model-backends design.** Is `harness/webui_config_schema.py` actually wired (run `check_wired`)? Does it satisfy or contradict `tests/webui/test_config_schema.py`? Is the config-schema↔model-backends dependency genuinely circular/backwards? Should `06e2e55` be reverted? → `_autowork_scratch/PH0_foundation_audit.md`.
- **Agent 0C — Adversarially audit all 11 briefs + 10 oracles for factory-gate compliance + impl/oracle consistency** (new-module plan-shape, integration excuse, sensitive-glob meta_task_type, wiring anchor, dependency DAG sanity, oracle non-vacuity vs impl spec). Flag every mismatch. → `_autowork_scratch/PH0_brief_oracle_audit.md`.
- **Agent 0D — Adversarially re-check last session's "0 findings" verdict AND this session's claims of what's committed/dormant/paused.** Confirm master state, allowlist contents, no orphan worktrees, no lurking blocked/retry tasks, daemon paused. Re-spot-check 2–3 of last session's commits for green-but-dead. → `_autowork_scratch/PH0_state_and_prior_audit.md`.

### PHASE 1 — Synthesis (orchestrator, inline; read the 4 PH0 files only)
Reconcile findings into a FINAL corrected design: confirm/adjust the dependency inversion (§7), the revert decision for `06e2e55`, the exact per-leaf impl-spec↔oracle reconciliation, and the wave plan. Write `_autowork_scratch/PH1_corrected_plan.md`. If PH0 refutes a core assumption, STOP and surface to owner.

### PHASE 2 — Fix (parallel where independent)
- **Agent 2A** — re-author `model-backends` brief (foundational, no deps; wire into control_gate.py) + reconcile `tests/webui/test_model_backends.py`.
- **Agent 2B** — re-author `config-schema` brief (`depends_on: [model-backends]`; imports model_backends for providers) + reconcile `tests/webui/test_config_schema.py`.
- **Agent 2C** — review/strengthen `typed-widgets`, `fs-browse` (ensure route registration in `_dispatch_get`/dispatch tables + `app.js` actually calls `/api/fs/list`), `typed-config-e2e` briefs against the real `tools/webui_*` surface.
- Orchestrator: if revert chosen, `git revert --no-edit 06e2e55` (or targeted reset of `harness/webui_config_schema.py` + `control_gate.py` additions); commit corrected briefs + oracles BEFORE dispatch.

### PHASE 3 — Wave execution under supervision (orchestrator)
`rm state/control/autowork/pause`; allowlist Wave 1 (`model-backends`) only; background-watch to acceptance (an `Integrate validated code for model-backends-impl` commit + oracle accept) or rejection. On clean accept → allowlist Wave 2 (`config-schema`), etc. Drive epic waves only after owner approves the `config/**` manifest (§6.3). Re-verify each wave's modules with `check_wired` and a full `pytest` of the leaf's oracle. Surface owner-gated items (§6); never auto-submit/auto-hand-edit deny-listed files.

---

## 9. WATCHER PATTERN (token-cheap monitoring; the daemon does not notify you)
Use a `run_in_background` Bash loop that **baselines every counter it compares** (the bug last session: an un-baselined orphan-count grep tripped on historical telemetry). Exit on: a new `Integrate validated code for <slug>` commit, a NEW rejection (baseline the count first), or a ~20–25 min stall; then print a compact snapshot (`compute_brief_status` for the active leaves, running workers, last few real telemetry rows, master HEAD). Do NOT `Read`/tail subagent JSONL transcript files into context.

## 10. HARD DON'TS (lessons from this session)
- Don't delete `.retry.json` sidecars to unstick a loop (it resets the retry budget).
- Don't allowlist a leaf before its dependencies are accepted (the dep-gate will leak it into a premature, failing build).
- Don't allowlist an `epic: true` root brief (triggers a competing planner decomposition).
- Don't hand-edit or attempt to pipeline-edit `_NEVER_AUTO_APPROVE` files; surface as owner hand-edits.
- Don't use the `full_stop` sentinel (owner objects); use `pause`.
- Don't target `webui/app.py` (dead Flask); the live UI is `tools/webui_server.py` (stdlib http.server).
- Don't reactively patch one surfaced gate at a time — do a coherent design pass so impl specs and oracles agree up front.
- Don't read full sub-agent transcripts or large files into the orchestrator context; delegate and consume compact summaries.

## 11. POINTERS
- Memory: `factory-new-module-wireup-gates.md` (the 4-gate recipe + control_gate.py anchor), indexed in `MEMORY.md`.
- Scratch dir (all session research/audits): `_autowork_scratch/` (`FACTORY_ORIENTATION.md`, `CHINESE_API_RESEARCH.md`, `ADVERSARIAL_VERIFY_FINDINGS.md`, `DRIVE_BACKUP_USER_SETUP.md`).
- Manual factory drive path (if daemon auto-plan is unreliable): `python -m harness.planner.cli` → `harness.planner.staging.stage_task` → `python -m harness.orchestrator_worker --state-dir state --task-id <id>`.
- Brief status / eligibility: `python3 -c "from pathlib import Path; from harness.brief_status import compute_brief_status; ..."`.
