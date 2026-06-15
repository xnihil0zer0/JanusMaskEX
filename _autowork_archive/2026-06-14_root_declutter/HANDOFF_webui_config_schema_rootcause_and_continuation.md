# HANDOFF — WebUI/Drive epics + codex/rclone: adversarially verify this session, fix the config-schema ROOT CAUSE, continue

**Authored:** 2026-06-13. **Repo:** `/home/xnihil0zer0/JanusMaskJR` (JanusMask / JM — the code factory). Sibling: `/home/xnihil0zer0/NobleGreedv2`.
**Daemon at handoff:** PAUSED via `state/control/orchestrator.flag` = `pause` (PID 2421475 alive). **Master HEAD:** `dcf697a`.

> **READ FIRST.** The previous operator (me) made real progress but then **slid into reactive one-gate-at-a-time patching of config-schema** — the exact anti-pattern the prior handoff's HARD DON'Ts warned against. The owner interrupted and asked for this handoff. **Phase 1 is to adversarially verify the claims below against live code/state — do NOT trust them at face value.** Then do the coherent root-cause fix (§5), then continue (§7). Operate as a THIN ORCHESTRATOR: delegate to parallel token-frugal sub-agents (each prompt must start with "Be maximally token-frugal — read only what you need, quote minimally, write findings to a file under `_autowork_scratch/`, return ONLY a compact ≤10-line summary"). Use background watchers, not polling. Keep your own context lean.

---

## 1. MISSION (owner's standing goals)

Build, through the JM code factory (never hand-edit production outside the pipeline), with preserved oversight and owner-gated dangerous actions:
- **A. WebUI config UX:** typed fields (int/float/str/bool/path/enum), Browse-PC buttons for paths, dropdowns for limited choices, **per-factory-role model selection**, type enforcement, **saveable** config, and **two-different-agents enforced where dual agents are required** (saving identical pair must error).
- **B. Model backends:** add **codex CLI** + API-key fields for OpenAI/Gemini/Anthropic + **top-5 Chinese APIs**; provider options **locked unless an API key is present**.
- **C. Google Drive backup-on-push** for both repos (diff of project dir → owner's Drive on every `git push`).
- **D. Adversarially verify prior sessions' work**, route fixes through the pipeline.

**This session the owner additionally authorized:** set up rclone, wire up codex CLI (the `_NEVER_AUTO_APPROVE` hand-edit is owner-cleared), confirmed secret-store at `state/secrets/api_keys.json`, and asked to re-verify Chinese-provider prices (playwright OK).

---

## 2. WHAT THIS SESSION COMPLETED (commit SHAs — VERIFY each, watch for green-but-dead)

- **`1e41ecb` — codex CLI wired (owner-authorized).** `harness/config.yaml` `agents:` block gained `codex` → `codex exec --dangerously-bypass-approvals-and-sandbox --skip-git-repo-check --color never -p ''` (no `-m`, so codex uses its authenticated default, observed **gpt-5.5**; JM's bwrap jail is the real sandbox). `harness/orchestrator.py:459` generalized `_is_agy = basename in ('agy','codex')` so codex reuses the agy stdin→fenced-`python`→outbox extraction path. **`synthesis.active_agents` stays `[claude, gemini]`** — codex is *selectable*, not in the default pair. Smoke-tested: `echo PROMPT | codex exec …` emits a clean fenced ```python block; codex is logged in (ChatGPT). **VERIFY:** (a) run a REAL synthesis task with codex actually in `active_agents` end-to-end (smoke ≠ in-pipeline); (b) `_extract_python_block` robustness — codex prints the block twice + a banner; (c) is "selectable not default" the right reading of "add codex as a model option"? (d) confirm `claude_fallback` literal-`'claude'` special-cases at orchestrator.py:~1188 correctly skip codex.
- **`41685dc` — model-backends DONE (daemon-built, FRESH new-module).** `harness/model_backends.py` (129 lines): `BackendSpec(kind, provider_id, *, base_url=None, api_key_env=None, model_id=None, command=None, args=None)`, `BACKEND_REGISTRY` of 12 (openai, gemini_api, anthropic, deepseek, moonshot, zhipu, qwen, minimax, claude, gemini, antigravity, codex), `resolve_backend(provider_id, secrets)` raising on locked, `agent_block()`. `harness/secrets_store.py` (56 lines): `state/secrets/api_keys.json` @0600. Both wired into `harness/control_gate.py`. **Oracle `tests/webui/test_model_backends.py` = 9/9 GREEN** (verified this session). **VERIFY:** (a) is the oracle ADEQUATE (does it really exercise resolve_backend locking, agent_block shape, every provider's base_url+env)? (b) green-but-dead: is model_backends actually *consumed* anywhere, or wired-but-inert? (c) `model_id` is None for all providers — fine for now (per-role selection sets it) but confirm that's intended; (d) base_urls/env match the RE-VERIFIED research (see below) — note the registry was built before reverification, so model_ids like `deepseek-v4-flash`/`kimi-k2.7-code`/`MiniMax-M3`/`glm-5.1`/`qwen3-coder-next` are NOT baked in.
- **Prices re-verified (doc-confirmed)** → `_autowork_scratch/CHINESE_API_RESEARCH.md`. Corrections from the prior session's claims: Kimi `k2.6`→**`k2.7-code`**; MiniMax `m2.5` does NOT exist → **`MiniMax-M3`**; Qwen pricing was wrong (actual tiered ~$1/$5 plus `qwen3-coder-next` ~$0.30/$1.50); DeepSeek has no separate coder model (flash/pro tiers, FIM built in); GLM → **`glm-5.1`**. All base_urls + env-var names confirmed correct. **VERIFY:** spot-check 1–2 against live docs.
- **rclone v1.74.3 installed** (no-sudo) at `~/.local/bin/rclone` (already on PATH via `.bashrc`). `[gdrive]` remote skeleton pre-created in `~/.config/rclone/rclone.conf` (type=drive, scope=drive, **NO token yet**). **OWNER ACTION PENDING:** `rclone config reconnect gdrive:` (browser login) then `rclone lsd gdrive:`.
- **Drive epic PREPPED (uncommitted, NOT dispatched)** — see §6.
- **Reconciliation/tightening commits:** `1e666bc` (decouple config-schema↔model-backends, AST-safe briefs+oracles, add gemini_api), `23dbdc8` (tighten both briefs ~70 lines each), `dcf697a` (config-schema brief test-spec balance).
- **Memory:** `webui-foundation-corrected-plan.md` (+ `MEMORY.md` pointer) updated with this session's facts.

**Refuted the prior handoff's keystone:** config-schema↔model-backends are NOT circular. config-schema is self-contained (own PROVIDERS table, no model_backends import), model-backends is a separate foundation. They were DECOUPLED, not inverted. (PH0 evidence: `_autowork_scratch/PH0_foundation_audit.md`.)

---

## 3. CURRENT STATE SNAPSHOT (ground truth at handoff — re-verify)

- **HEAD** `dcf697a`. **Daemon** PAUSED (`orchestrator.flag`=`pause`, PID 2421475 alive). Real pause control = this flag; the file `state/control/autowork/pause` is a **NO-OP** (a prior-prior operator's misconception — do not rely on it).
- **Allowlist** (`state/control/autowork/auto_promote.allowlist`): among webui/drive, ONLY `webui-config-schema` is uncommented. `webui-model-backends` commented `# DONE 41685dc`. `webui-typed-widgets`/`fs-browse`/`typed-config-e2e` and all 4 drive leaves are commented/HELD. (Many unrelated ngv2_* slugs remain allowlisted from prior sessions — leftover blocked tasks for those get retried-then-exhausted on resume; benign noise.)
- **config-schema** reset to a CLEAN baseline: committed buggy module `harness/webui_config_schema.py` (`06e2e55`), committed CORRECT oracle `tests/webui/test_config_schema.py` (RED: **2 failed / 9 passed** against the buggy module — exactly the two real bugs), committed fixed brief. **No plan_hooks, no staged/blocked config-schema tasks** (I cleared my half-patched plan + a stale `.processing` claim).
- **model-backends** DONE (9/9 green), its state markers were cleared but the module is committed (`41685dc`); brief commented off the allowlist.
- **Uncommitted in working tree:** `config/drive_backup_modules.yaml` (NEW, hand-created — see §6/§8); `brief_hooks_drive-backup-{archiver,on-push,uploader}.md` (drive-epic hygiene edits). Lots of pre-existing untracked research/handoff files (ignore).
- **Killed this session:** a stale model-backends-impl worker (PID 2750622, building from a stale pre-tighten plan) — model-backends had already landed via `41685dc`, so nothing was lost. Cleared several stale `git_commit.lock`s.

---

## 4. THE config-schema PROBLEM — full root-cause analysis (the heart of this handoff)

config-schema is the ONLY stuck foundation. It is a **fix-forward** of `06e2e55`, which landed a wired-but-buggy `webui_config_schema.py` with TWO real bugs:
1. **Role-value propagation:** `validate_config` validates each role assignment but never writes the accepted value into `ValidatedConfig.values[role.config_key]` → `out.values["overseer.default_backend"]` KeyErrors.
2. **Save-key nesting:** `atomic_save_config` writes short keys at top-level instead of mapping `parallel_cap`→`autowork.parallel_cap` etc., so `loaded["autowork"]["parallel_cap"]` stays stale.

The committed oracle correctly catches both (2 failed / 9 passed). The problem is the factory never *forces a fix*. Three symptoms surfaced, each of which I REACTIVELY patched (mistake):
- (i) the test_authoring oracle worker improvised a constant `OVERSEER_KEY` → tripped `ast_enforcer.py:78` hardcoded-credential gate. Patched via a brief instruction to reproduce the oracle verbatim.
- (ii) planner discarded both drafts as `empty_plan` / `PlanViolation(insufficient_unit_tests: len(unit_tests) >= len(functional_requirements))`. Patched via a TEST-SPEC BALANCE block in the brief.
- (iii) the planner gives `config-schema-impl` a weak `verification_command: python -c "import …"` (import smoke), so the EDIT is never gated on the oracle → impl no-diffs / under-fixes and still "passes"; then the dep-gate leak dispatches the oracle task, which runs against the still-buggy module and fails `auto_commit_failed`.

**THE UNIFYING ROOT CAUSE: fix-forward is the wrong pattern for this factory.** The proven, frictionless pattern (model-backends and every prior epic) is **FRESH new-module synthesis**: the blind agents build the *complete* module from scratch to satisfy the embedded committed oracle; the impl's import-smoke verification is sufficient because the module is built correct-and-complete; a separate test_authoring task validates the oracle. In that flow:
- the impl runs first (deps=[]), ACCEPTS, and the dep-gate then correctly releases the oracle task against a now-correct module → green. (model-backends did exactly this → 9/9.)

Fix-forward breaks every assumption of that flow:
- (a) the planner's default impl verification (import smoke) does not force an EDIT to actually change behavior;
- (b) when the impl doesn't produce an accepted real fix, it is effectively "absent/blocked", which trips the **dep-gate LEAK** (`harness/autowork_daemon.py` `_brief_dep_gate_ok` ~line 1637, applied in `_decide` ~1708: releases a dependent when its dependency is blocked/zombie/unplanned/absent) → the oracle task dispatches against the unfixed module → fails;
- (c) so the leaf never converges, and I kept patching symptoms.

**Why I was about to "stage with the oracle":** staging `config-schema-impl` with `verification_command = pytest tests/webui/test_config_schema.py` hand-forces the impl to be gated on the real oracle. That IS the correct gate for a fix-forward — but it is a **manual override of the planner's default**, i.e. a workaround that masks the root cause rather than removing it. The owner correctly questioned it.

---

## 5. ROOT-CAUSE FIX — do the coherent pass (do NOT keep patching gates)

**RECOMMENDED — Option 1: eliminate the fix-forward; rebuild config-schema FRESH (the proven model-backends path).**
The brief is already fixed (`dcf697a`: test-spec balance + AST verbatim instruction) and the oracle is committed + correct. So a from-scratch build should converge exactly like model-backends did.
Steps:
1. Remove the buggy pipeline-built code so config-schema becomes a clean new-module build: delete `harness/webui_config_schema.py` AND the two trailing lines it added to `harness/control_gate.py` (`from harness import webui_config_schema` + `def typed_config_schema(): …`). This is a **deletion of pipeline-built harness code to enable a clean rebuild** — `control_gate.py` is NOT in `_NEVER_AUTO_APPROVE`, but it is sensitive; treat the deletion as an owner-cleared git operation (the owner authorized fixing this). Prefer `git revert --no-commit 06e2e55` then resolve the `control_gate.py` conflict (KEEP the `41685dc` model_backends wiring, REMOVE only the webui_config_schema wiring), then commit; OR do the 1-file delete + 2-line edit directly and commit. **VERIFY after:** `python -c "import harness.control_gate"` still imports, `tests/webui/test_model_backends.py` still 9/9, `harness/webui_config_schema.py` gone.
2. Confirm config-schema clean baseline (no plan_hooks, no tasks — already true at handoff).
3. `touch brief_hooks_webui-config-schema.md`; ensure ONLY `webui-config-schema` active in the allowlist; `echo resume > state/control/orchestrator.flag`.
4. Background-watch (see §9). Expect: plan_kickoff → config-schema-impl builds the FULL module → ACCEPT (import-smoke ok because module is complete+correct) → config-schema-oracle validates → leaf green. Then run `pytest tests/webui/test_config_schema.py` yourself to confirm 9+/9+ green (not 2-failed).
   - If it empty_plans once, that's planner flakiness (model-backends did too); it retries. If it empty_plans repeatedly, re-examine the test-spec balance block.

**Option 2 (fallback, if revert is undesirable): keep fix-forward but gate it correctly.** Manually (or by teaching the planner) set `config-schema-impl.verification_command = python -m pytest tests/webui/test_config_schema.py -q` and `files_touched = [harness/webui_config_schema.py]`, then `stage_task` + run `python -m harness.orchestrator_worker --state-dir state --task-id config-schema-impl`. This is legitimate (the oracle is the correct gate for a fix) but is a manual override; the *durable* fix would be a `harness/planner` change so the planner uses an existing committed oracle as the impl's verification when one exists (sensitive `harness_self_fix`, larger lift — only do if the owner wants fix-forward to be a first-class supported path).

**Owner decision needed:** Option 1 (revert+fresh, recommended) vs Option 2 (gated fix-forward). Surface this and pick per owner.

**Also consider fixing the dep-gate leak properly** (it is the second-order cause that turns a stuck impl into a failing-oracle cascade). It lives in `harness/autowork_daemon.py` which is `_NEVER_AUTO_APPROVE` → **owner hand-edit only**; surface as a separate owner-gated item, do not pipeline it.

---

## 6. DRIVE EPIC — prepped, ready, NOT dispatched

Prep agent output: `_autowork_scratch/DRIVE_EPIC_PREP.md`. Done:
- **`config/drive_backup_modules.yaml`** (NEW, hand-created, uncommitted): CONFIG_WIRED manifest listing the 5 module `.py` paths so they pass `check_wired` (`tools/drive_backup/{archiver,ledger,uploader,hook_runner,install_hooks}.py`). The drive modules are **orphan-by-design** (run from a git pre-push hook, not a live import edge). Format verified against `harness/wire_up.py` `_grep_config` regex `(?<![\w.])<stem>\.py\b` (leading `/` is not `[\w.]`, so each explicit `.py` path matches; a `-m dotted` token would only register one). **The earlier `archiver-impl` failed `orphan_unwired` precisely because this manifest didn't exist.**
- **Resource-hygiene constraint** added to `brief_hooks_drive-backup-{archiver,uploader}.md` (the self-heal at `outbox/brief_hooks_archiver-impl_fix.md` diagnosed the `auto_commit_failed_r1`/`git worktree remove exit 128`: the impl wrote artifacts into the staging worktree / left handles open). Constraint: write to tempdirs/caller paths OUTSIDE the repo, no nested `.git`, close all handles via context managers.
- **Wave plan:** commit the manifest first (no build task) → Wave A `drive-backup-archiver` (owns archiver.py+ledger.py) → B `drive-backup-uploader` → C `drive-backup-hook-runner` → D `drive-backup-installer`. Allowlist one wave at a time. Modules BUILD without rclone (all rclone/tar/git/fs are injected seams; oracles make no live calls); full e2e needs the owner's `gdrive:` OAuth.

**OPEN QUESTION (§8): is hand-creating `config/drive_backup_modules.yaml` acceptable?** It is static wiring DATA (a path list, like the allowlist/oracles), and the factory's patch path can't create new files, so a `harness_self_fix` task for it is awkward. But `config/**` is the sensitive tier. **Surface to owner: commit the hand-created manifest, OR route its creation through a `harness_self_fix` whole-file task.** Until decided, the drive modules can't pass `check_wired`.

---

## 7. CONTINUATION ORDER (after config-schema is green)

1. **config-schema** → green via §5 (Option 1 recommended).
2. **Drive epic** waves A→D (§6), after the manifest decision (§8) and ideally after owner's rclone OAuth.
3. **WebUI UI leaves** (these EDIT the live `tools/webui_server.py` / `tools/webui_control.py` / `tools/webui_static/app.js` — stdlib http.server, NON-sensitive; the dead `webui/app.py` Flask tree is NOT the target):
   - `webui-fs-browse` — MUST register the `/api/fs/list` route in the dispatch table AND make `app.js` actually call it (the prior attempt failed because neither happened).
   - `webui-typed-widgets` — render typed fields/dropdowns/Browse buttons from `webui_config_schema.CONFIG_FIELDS` + `model_backends.BACKEND_REGISTRY`; enforce dual-distinct + provider-locked on save.
   - `webui-typed-config-e2e` — full integration leaf.
4. **Codex per-role model selection** in the webui (owner's "each role has a model selection" + "two different agents enforced") — depends on config-schema + typed-widgets. Note `synthesis.active_agents` is currently a flat 2-slot list; a true role→model map is new config surface.
5. **Owner hand-edits** (surface, do not pipeline): codex into a default role if desired; the dep-gate leak fix.

---

## 8. OWNER-GATED — surface and WAIT (do not auto-resolve)

1. **config-schema approach:** Option 1 revert+fresh (recommended) vs Option 2 gated fix-forward (§5).
2. **`config/drive_backup_modules.yaml`:** accept the hand-created static manifest, or require a pipelined `harness_self_fix`? (§6)
3. **rclone OAuth:** `rclone config reconnect gdrive:` (browser) — owner only.
4. **codex default model:** observed default `gpt-5.5`; confirm acceptable / whether to pin `-m` per role.
5. **dep-gate leak** (`autowork_daemon.py`, `_NEVER_AUTO_APPROVE`): owner hand-edit if a real fix is wanted.
6. **Never auto-submit / never hand-edit `_NEVER_AUTO_APPROVE`** (orchestrator.py was edited THIS session ONLY because the owner explicitly authorized the codex wiring; that authorization does not generalize).

---

## 9. WATCHER PATTERN (token-cheap; daemon does not notify)
`_autowork_scratch/wave1_watcher.sh` exists: a `run_in_background` bash loop that BASELINES line-count + HEAD, then exits on (a) a `Integrate validated code for <slug>` commit, (b) a NEW reject/`task_blocked`/`ast_validation_failed`/`verification_failed`/`retry_exhausted`/`dependency_failed` for the watched slugs, (c) a `planner_hallucination_discarded` for them, or (d) a 25-min stall — then prints a compact snapshot. Re-baseline counters each launch. Do NOT tail subagent JSONL transcripts into context.

---

## 10. HARD DON'TS (lessons, several learned the hard way THIS session)
- **DON'T reactively patch one surfaced gate at a time.** Do a coherent design pass (this is why config-schema thrashed). Decide FRESH-vs-fix-forward up front.
- **DON'T conflate BUILT with WORKS.** model-backends is 9/9 green — still adversarially confirm it's not green-but-dead, the oracle is adequate, and it's actually consumed.
- **DON'T trust `state/control/autowork/pause`** — it's a no-op; the real control is `orchestrator.flag`.
- **DON'T delete `.retry.json` sidecars to "unstick"** (resets the retry budget). To re-plan, clear the WHOLE task set + plan_hooks + `touch` the brief (a clean retirement, not a budget reset).
- **DON'T allowlist a leaf whose deps aren't accepted** (dep-gate leak dispatches it prematurely). One wave at a time.
- **DON'T hand-edit `_NEVER_AUTO_APPROVE` files** (agent_jail/dbus_proxy/paths/git_integration/orchestrator/orchestrator_worker? — NOTE: PH0 found `orchestrator_worker.py` is NOT actually in the tuple; verify the live list/interceptors/selfheal/autowork_daemon/services) without explicit per-change owner authorization.
- **DON'T read full sub-agent transcripts / large files into the orchestrator context.**

---

## 11. POINTERS
- **Scratch (all this session's research/audits):** `_autowork_scratch/` — `PH0_gate_verify.md`, `PH0_foundation_audit.md`, `PH0_brief_oracle_audit.md`, `PH0_state_and_prior_audit.md`, `PH1_corrected_plan.md`, `PH2A_model_backends.md`, `PH2B_config_schema.md`, `PH2_brief_tighten.md`, `CHINESE_API_RESEARCH.md`, `DRIVE_EPIC_PREP.md`, `CODEX_WIRING_PROPOSAL.md`, `DRIVE_BACKUP_USER_SETUP.md`, `FACTORY_ORIENTATION.md`, `ADVERSARIAL_VERIFY_FINDINGS.md`, `wave1_watcher.sh`.
- **Memory:** `webui-foundation-corrected-plan.md`, `factory-new-module-wireup-gates.md`, `daemon-supervisor-respawn.md`, `dont-conflate-built-with-works.md`, `never-hand-edit-production-outside-pipeline.md` (all in `MEMORY.md`).
- **Self-heal diagnosis of the drive archiver failure:** `outbox/brief_hooks_archiver-impl_fix.md` (or under `/home/xnihil0zer0/JanusMaskJR_agentwork/claude/claude-r1-archiver-impl-*/outbox/`).
- **Manual factory drive:** edit `plan_hooks_<slug>.json` → `from harness.planner.staging import stage_task; stage_task(Path('plan_hooks_<slug>.json'), '<task_id>', Path('state'))` → `python -m harness.orchestrator_worker --state-dir state --task-id <id> --config harness/config.yaml`.
- **Brief status:** `python3 -c "from pathlib import Path; from harness.brief_status import compute_brief_status; ..."`.

---

## 12. PHASE 0 ADVERSARIAL VERIFICATION CHECKLIST (run these first, in parallel sub-agents)
- **0A — codex wiring (`1e41ecb`):** is the config entry + orchestrator.py:459 change correct and complete? Run a real task with codex temporarily in `active_agents` and confirm it produces an accepted candidate (not just the smoke test). Confirm `_extract_python_block` handles codex's double-block+banner. → `_autowork_scratch/PHV_codex.md`.
- **0B — model-backends (`41685dc`):** re-run the oracle; audit the oracle for ADEQUACY (locking, agent_block, every provider); green-but-dead check (is it consumed anywhere?); confirm base_urls/env vs reverified research; is `model_id=None` for all intended? → `PHV_model_backends.md`.
- **0C — config-schema root cause:** confirm the 2-bug diagnosis, the import-smoke-verification claim (re-plan and inspect `plan_hooks_webui-config-schema.json` `config-schema-impl.verification_command`), and that a FRESH build (Option 1) would converge. Reproduce the dep-gate-leak path. → `PHV_config_schema.md`.
- **0D — state & this session's churn:** confirm HEAD, daemon paused, allowlist, no orphan worktrees/locks, the committed contracts intact; confirm nothing was lost by my state deletions / killed worker; confirm `config/drive_backup_modules.yaml` format truly satisfies `check_wired`. → `PHV_state.md`.
Then synthesize → decide Option 1 vs 2 with the owner → execute §5 → §7.
