# HANDOFF — Two concurrent tracks: (A) JanusMask factory autonomy + drive-backup epic, (B) NobleGreedv2 3-agent live bounty hunt

**Authored:** 2026-06-13. **Repo (factory):** `/home/xnihil0zer0/JanusMaskJR` (JM). **Sibling (runtime/bounty):** `/home/xnihil0zer0/NobleGreedv2` (NGv2).
**Master HEAD at handoff:** `ece3e4c` (PUSHED to origin/master). **Daemon:** PAUSED via `state/control/orchestrator.flag` = `pause`.
**Live synthesis config:** `harness/config.yaml` `synthesis.active_agents: [claude, gemini]` — DUAL-AGENT (solo mode is NOT in the live config; see §0).

> **OWNER STANDING DIRECTIVE FOR THIS HANDOFF:** maximize parallelism + token efficiency; **delegate as much as possible to the factory** (daemon-driven, not hand-driven); **solo model mode DISABLED** (dual-agent claude+gemini); **all owner gates are AUTHORIZED** (factory-internal: `harness_self_fix` decisions, `_NEVER_AUTO_APPROVE` hand-edits via pipeline+decision files, approvals); **maintain factory workflow** (build through the pipeline, never hand-edit production outside it except owner-cleared decisions). **Concurrently dispatch a 3-agent live bounty hunt** (Track B) alongside the factory work (Track A). **One carve-out that does NOT generalize:** external bounty *submission* to third-party programs is outward-facing + irreversible — keep a lightweight per-target owner confirm before each submit (§B.5); never blind-batch-submit.

> **OPERATE AS A THIN ORCHESTRATOR.** Delegate to parallel token-frugal sub-agents. Every sub-agent prompt MUST start with: *"Be maximally token-frugal — read only what you need, quote minimally, write findings to a file under `_autowork_scratch/`, return ONLY a compact ≤10-line summary."* Use `run_in_background` watchers (§7), NOT polling. Never read full agent JSONL transcripts or large files into your own context. Run independent work in parallel (multiple tool calls / multiple background agents in one turn).

---

## 0. SOLO MODE / DUAL-AGENT POSTURE (verify first)

- The live `harness/config.yaml` is dual-agent: `synthesis.active_agents: [claude, gemini]`. The daemon and any worker run with `--config harness/config.yaml` use BOTH agents. **This is the required posture — keep it.**
- A scoped single-agent override file exists at `_autowork_scratch/config_gemini_solo.yaml` (`active_agents: [gemini]`). It was used ONLY for the now-COMPLETE large-whole-file webui leaves (Claude structurally balks at ~147KB whole-file manifests — see §6 recipe). **Do NOT pass it to the daemon or to drive-epic workers.** Drive modules are fresh single-file new modules that dual-agent handles fine.
- `synthesis.enable_single_agent_promotion: true` is currently set (resilience: a leaf can be accepted from one agent if the other dies). If the owner wants STRICT dual-agent acceptance, set it `false` — but note the webui leaves genuinely needed single-agent, so leaving it as a fallback is defensible. Operator's call; default = leave it, rely on `active_agents` being dual.

---

## 1. WHAT IS DONE (this + prior sessions — all on origin/master, all green)

**✅ WEBUI TYPED-CONFIG + MODEL-BACKENDS EPIC — COMPLETE.** All 5 leaves green, webui integration 24/24 no-regression, full `tests/webui/` 47/47:
- `config-schema` `3ea7988` (impl) + `7230f90` (oracle) — `harness/webui_config_schema.py` (typed ConfigField/RoleSpec/ProviderSpec, validate_config w/ dual-distinct + provider-lock, atomic_save_config), oracle **18/18**. Built via FRESH rebuild (reverted buggy `06e2e55`→`69eae38`, manual-drove impl gated on the real oracle).
- `model-backends` `41685dc` — `harness/model_backends.py` (12-provider BACKEND_REGISTRY incl. codex + 5 Chinese APIs) + `harness/secrets_store.py` (`state/secrets/api_keys.json` @0600). Now LIVE (consumed by typed-widgets). Oracle 9/9.
- `typed-widgets` `f80a61b` — `GET /api/config/schema` + `POST /api/config/typed` on the live stdlib webui + `app.js` typed widgets (per-role dropdowns, twin selects for dual roles, provider-lock, Browse buttons). Oracle 7/7.
- `fs-browse` `ece3e4c` — sandboxed `GET /api/fs/list` + `app.js` picker. Oracle 7/7.
- `typed-config-e2e` — 6/6 (pure integration-verification leaf, no impl; passes now all 4 upstreams are built).
- Owner mission items **A** (typed config UX) + **B** (model backends incl. codex) are BUILT on the live webui (`tools/webui_server.py`, `tools/webui_control.py`, `tools/webui_static/app.js`).

**✅ Supporting:** codex wired as selectable agent (`1e41ecb`); `config/drive_backup_modules.yaml` CONFIG_WIRED manifest committed (`3a7dca0`); rclone v1.74.3 installed at `~/.local/bin/rclone`, `[gdrive]` remote skeleton present (NO token yet).

**Phase-0 verification findings (carry forward):** model-backends oracle was thin (harden when convenient); codex `_extract_python_block` is first-match and breaks on codex's banner fence (§A.3); dep-gate leak + planner-ignores-brief-verification are the two live harness defects that forced manual driving (§A.1/A.2).

---

## 2. UNFINISHED WORK (continue — both tracks CONCURRENTLY)

### TRACK A — JanusMask factory: harden → delegate the drive epic to the daemon
### TRACK B — NobleGreedv2: 3-agent live bounty hunt (parallel, owner-gated submit)

Launch both tracks in parallel and supervise with background watchers. Track A is mostly delegated to the daemon once hardened; Track B is 3 background hunter agents. Keep your context lean while both run.

---

## A. TRACK A — FACTORY AUTONOMY + DRIVE-BACKUP EPIC

**Goal:** make the daemon able to build the drive epic (and future epics) AUTONOMOUSLY in dual-agent mode, then let it. Two live harness defects currently force manual driving — fix them first (now authorized), then delegate.

### A.1 — DEP-GATE LEAK (owner-authorized hand-edit, route via pipeline)
`harness/autowork_daemon.py` `_brief_dep_gate_ok` (~L1692): `if state in ('blocked','zombie'): continue` and `rec is None: continue` RELEASE a dependent task when its dependency is blocked/zombie/absent/unplanned. On a fresh 2-task plan (impl + paired test_authoring oracle, oracle deps=[impl]), at plan time the impl record doesn't exist yet → oracle's dep reads "absent" → oracle dispatched BEFORE impl → runs against a missing/buggy module → fails. This is why config-schema thrashed and why I had to manually drive impl-first.
- **Fix intent:** a dependent must NOT be released when its dependency is merely *not-yet-dispatched/absent*; only release on a genuine terminal-accepted dependency (or a true unbreakable-deadlock with explicit telemetry). Preserve the deadlock-safety for genuinely-stuck deps but stop the premature release.
- `autowork_daemon.py` is `_NEVER_AUTO_APPROVE`. Per [[issue-fix-via-pipeline-then-rerun]]: author a RED oracle (a test that proves the leak: a dependent with an absent dependency must stay gated), then a `harness_self_fix` leaf touching `autowork_daemon.py`, write the approval decision file (authorized), run through the pipeline, rerun. Do NOT hand-edit directly.

### A.2 — PLANNER IGNORES THE BRIEF'S `verification_command` (owner-authorized fix via pipeline)
For NEW-module / `harness_self_fix` tasks the planner emits a WEAK `verification_command` (`python -c "import ..."` import-smoke) even when the brief's Required-plan-shape explicitly specifies `pytest <oracle>`. So a buggy-but-importable module ACCEPTs. (For `refactor`/edit tasks the planner DID honor pytest — bug is scoped to new-module/self-fix.) An impl that isn't gated on its real oracle is the §A.1 leak's fuel.
- **Fix intent:** when a committed oracle exists for a leaf (brief names it / a paired test file exists), the planner must set the impl's `verification_command` to that oracle, not import-smoke. `harness/planner/**`. Route via pipeline (RED oracle proving the planner picks the brief's verification_command, + harness_self_fix + decision). 
- **Together A.1+A.2 make the daemon trustworthy for 2-task plans** → then the drive epic (and everything) can be daemon-delegated without manual impl-first driving.

### A.3 — codex `_extract_python_block` banner-fence fix (lower priority, via pipeline)
`harness/test_author.py` (`_extract_python_block`, ~L150) is FIRST-MATCH; codex prints a banner + the python block twice, so a leading non-python fence becomes "block #1" and the real code is dropped; whole-text `ast.parse` fallback also fails with a banner present. Fix: pick the longest valid-AST ```python block (or language-tag filter). Non-blocking (codex is selectable, not in the default pair) but needed before codex is used in a real synthesis pair. Pipeline + RED oracle.

### A.4 — DRIVE-BACKUP EPIC (delegate to the daemon, dual-agent)
**Goal (owner mission C):** Google Drive backup-on-push for BOTH repos — diff/snapshot of the project dir → owner's Drive on every `git push`.
- **Manifest already committed** (`3a7dca0`, `config/drive_backup_modules.yaml`) so the 5 modules pass `check_wired` (they are orphan-by-design: run from a git pre-push hook, not a live import edge). Modules: `tools/drive_backup/{archiver,ledger,uploader,hook_runner,install_hooks}.py`.
- **Briefs + RED oracles exist** (committed `efcf4a3`). Three drive briefs have UNCOMMITTED working-tree edits at handoff (`brief_hooks_drive-backup-{archiver,on-push,uploader}.md` — resource-hygiene constraints: write to tempdirs OUTSIDE the repo, no nested `.git`, close handles via context managers; these fixed the `git worktree remove exit 128` / `auto_commit_failed_r1` seen earlier). **Commit these as drive-epic prep**, or fold into the tightening below.
- **THE DRIVE BRIEFS LIKELY NEED THE SAME plan-shape TIGHTENING** the webui briefs needed (the planner-validation gates: `spec_author:null`, `len(unit_tests)>=len(functional_requirements)`, ≥2 edge_cases mirrored in regression/property tests, `integration` excuse in per-task `non_goals`, ONE-task-per-leaf). Check each brief for a `# Required plan shape` block; if absent, add one (template in §6). New `.py` modules under `tools/` are NON-sensitive (NOT `harness_self_fix`); they ARE new-module-creating so they go through the [[factory-new-module-wireup-gates]]: paired `test_authoring` oracle w/ dotted `mutation_target`, integration excuse, and `check_wired` (satisfied by the committed manifest).
- **Wave plan (allowlist ONE wave at a time — never allowlist a leaf whose deps aren't accepted, or the leak dispatches it early):** A `drive-backup-archiver` (archiver.py + ledger.py) → B `drive-backup-uploader` → C `drive-backup-hook-runner` → D `drive-backup-installer`. There may also be a `drive-backup-on-push` integration leaf — verify the brief set.
- **Modules BUILD without rclone** (all rclone/tar/git/fs are injected seams; oracles make no live calls). **Full e2e needs the owner's `gdrive:` OAuth** — a physical browser login the owner must run: `rclone config reconnect gdrive:` then `rclone lsd gdrive:`. Surface this; the build does not block on it.
- **Delegation:** once A.1/A.2 are fixed, allowlist Wave A, `touch` its brief (newest mtime → daemon plans it), `echo resume > state/control/orchestrator.flag`, and let the daemon build it dual-agent. Watch with §7. Repeat per wave.

### A.5 — Live webui verification (delegate to a playwright sub-agent)
The leaf oracles drive the real sidecar, but the rendered `app.js` UI is only string-matched. For true "works" (not just "built" — [[dont-conflate-built-with-works]]): launch the webui (`scripts/run-webui.sh` or `python -m tools.webui_server --host 127.0.0.1 --port 8765 --state-dir state --logs-dir logs`), and a playwright sub-agent clicks through `#/config`: typed widgets render, per-role dropdowns + twin selects, Browse opens the fs picker, a valid save persists, an invalid save shows field_errors, dual-same is refused. Token-frugal; report pass/fail.

---

## B. TRACK B — NGv2 3-AGENT LIVE BOUNTY HUNT (concurrent)

**Repo:** `/home/xnihil0zer0/NobleGreedv2`. **Read first (token-frugally, via a sub-agent):** repo-root `HANDOFF_ngv2_bounty_hunt_continuation.md` (full inventory + recipe + ranked leads) and memory [[ngv2-financial-viability-parallel-hunt]].

### B.1 — Standing state
- **9 parked NOVEL jail-confirmed PoCs** already exist (onyx ×3, flowise ×2, modeldb HQLi, windmill, h2ogpt, realchar) awaiting owner-gated submission.
- Gadget/deserialization class is corpus-EXHAUSTED. **UNLOCK = PARALLELIZE Opus hunters + PIVOT off deser** to multi-tenant **authz/IDOR/BOLA + SSRF + SQLi** on REAL products.

### B.2 — Dispatch 3 parallel Opus hunter agents (background)
Launch 3 `run_in_background` hunter agents (Opus), each with the token-frugal preamble, each assigned a DISTINCT product/vuln-lens so they don't collide (e.g. H1: authz/IDOR/BOLA on product set X; H2: SSRF on set Y; H3: SQLi/injection on set Z — pick targets from the continuation handoff's ranked leads). Each hunter: source target → locate attacker-reachable sink → build a real PoC → **confirm it detonates in the bwrap jail** → write a compact PoC package to `_autowork_scratch/` (or NGv2's PoC dir) → return ≤10-line summary. Do NOT read their transcripts into context; collect via their summary files.

### B.3 — Machinery
NGv2 MCP tools are available (via ToolSearch): `mcp__noblegreed__get_task`, `mcp__noblegreed__submit_code`, `mcp__noblegreed__get_feedback`. The bwrap jail is the real sandbox for detonation. Confirm a PoC is jail-`confirmed` (not just regex-detected) before parking it — don't conflate detected with claimable.

### B.4 — Completeness
After the first round, a completeness-critic pass: what target/vuln-class wasn't covered? Loop hunters until ~2 dry rounds, accumulating confirmed PoCs.

### B.5 — ★ SUBMISSION GATE (the one outward-facing carve-out)
The owner authorized "all owner gates," but external submission to third-party bounty programs is **irreversible + outward-facing**. So: hunt + confirm + PARK autonomously; before EACH external submit, surface the PoC package (target, CWE, repro, impact) and get a one-line owner GO. **Never blind-batch-submit.** Standing rule [[ngv2-financial-viability-parallel-hunt]]: submission owner-gated. (If the owner explicitly says "auto-submit all confirmed," then proceed — but get that explicit statement.)

---

## 3. CONCURRENCY MODEL (how to run both tracks without thrash)

- **Track A** is largely self-running once the daemon is hardened: fix A.1/A.2 (each via a pipeline harness_self_fix leaf you supervise), then the daemon builds the drive waves dual-agent on its own — you just watch + allowlist the next wave.
- **Track B** is 3 background hunter agents on NGv2.
- **Critical isolation rule** [[concurrency-isolation-and-ngv2-solver-ast-epic]]: T1 external-root serialization is live, but DO NOT run NGv2 agents (agy/hunters) with cwd in the JM main tree — they are uncontained and can tamper. Hunters operate in `/home/xnihil0zer0/NobleGreedv2`. Verify tree integrity (`git status` on JM) after any agy run. Two stale uncontained `agy` procs in the JM tree were killed this session — re-check `pgrep -af agy` and ensure JM-tree ones are not orphans.
- Launch the 3 hunters AND kick off the A.1 fix in the SAME turn (parallel). Use one watcher for the JM daemon (§7) and collect hunter results from their scratch summaries.

---

## 4. FACTORY WORKFLOW — exact recipes (token-efficient; don't re-derive)

**Daemon control (REAL pause = `orchestrator.flag`; `state/control/autowork/pause` is a NO-OP):**
- Pause: `echo pause > state/control/orchestrator.flag`. Resume: `echo resume > state/control/orchestrator.flag`.
- Daemon auto-plans 1 allowlisted brief/iter by NEWEST mtime → `touch brief_hooks_<slug>.md` to prioritize. Supervisor [[daemon-supervisor-respawn]]: `scripts/run-autowork.sh` respawns the child; kill the CHILD only; never nohup a 2nd daemon.

**Standalone planner (to inspect/correct a plan before driving):**
`python -m harness.planner.cli brief_hooks_<slug>.md --output-plan plan_hooks_<slug>.json` (dual-agent; ~4–5 min; LLM — may need a tightened brief to pass plan-validation).

**Manual drive (deterministic; use if a leaf needs controlled ordering):**
`python3 -c "from pathlib import Path; from harness.planner.staging import stage_task; stage_task(Path('plan_hooks_<slug>.json'),'<task_id>',Path('state'))"` → optionally edit `state/tasks/<task_id>.json` (e.g. `verification_command`) → `python -m harness.orchestrator_worker --state-dir state --task-id <task_id> --config harness/config.yaml`. Worker auto-commits on accept. ALWAYS run the broader suite after (e.g. `tests/integration/test_webui_server.py`) — the leaf oracle won't catch regressions a whole-file edit introduces.

**Hygiene before re-dispatch:** clear stale sidecars `state/output/<id>.{py,patches.json,files.json}`, `state/sessions/*_<id>_submission.json`, blocked records — they take precedence on re-dispatch [[stale-sidecar-precedence-gotcha]]. Do NOT delete `.retry.json` to "unstick" (resets budget); to re-plan, clear the WHOLE task set + plan_hooks + `touch` the brief.

---

## 5. PLANNER-VALIDATION GATES (every new/edited leaf brief needs a `# Required plan shape` block)

The planner rejects drafts missing: `spec_author` (emit exactly `null`), `len(unit_tests) >= len(functional_requirements)`, ≥2 `edge_cases` mirrored in `regression_tests`/`property_tests`, ≥1 `integration_test` UNLESS the word **integration** is in the task's `spec.non_goals`, `minimum_test_count >= 1.5*len(FR)`, `token_budget_ratio.test_tokens >= 1.5*implementation_tokens`. **Template (adapt per leaf):**
```
# Required plan shape
EXACTLY ONE task — do NOT split (monolithic oracle). Single working_dir (null). Emit verbatim:
1. task_id: "<slug>-impl"
   - meta_task_type: "<refactor for whole-file EDIT of existing files | the new-module type for fresh .py>"
   - spec_author: null   (REQUIRED — emit exactly null)
   - dependencies: []     (built sibling leaves are NOT task deps)
   - files_touched: [...]  (>1 file or any non-.py auto-routes to whole-file __JANUSMASK_MANIFEST__)
   - verification_command: "python -m pytest <committed oracle> -q"
   - spec.non_goals MUST contain the word "integration"
TEST-SPEC BALANCE: functional_requirements TIGHT (≤6) w/ one unit_test each; ≥2 edge_cases mirrored; minimum_test_count ≥9; test_tokens ≥ 1.5*implementation_tokens.
```
For NEW `.py` modules, add the [[factory-new-module-wireup-gates]] requirements (paired `test_authoring` task w/ bare-dotted `mutation_target`, `check_wired` satisfied).

---

## 6. ★ GEMINI-SOLO RECIPE (ONLY for large whole-file edits of EXISTING files — NOT needed for fresh modules)

The webui UI leaves whole-file-edited 3 large files (~147KB; non-.py app.js forces `_requires_verbatim_manifest`→whole-file manifest, no partial-edit). **Claude balks at ~147KB reproduction (emits `@@PLACEHOLDER@@` stubs → L1 SyntaxError); gemini produces valid large manifests** but may DROP additive in-class methods. Recipe (owner-approved single-agent, scoped — live config untouched): tighten brief (§5) → planner → stage → run worker with `--config _autowork_scratch/config_gemini_solo.yaml` → if it drops additive content, append a pointed diagnostic nudge to the staged task's `spec.implementation_notes` (quote the exact error + "include the complete method bodies INSIDE the class") and re-run. **Drive-epic modules are fresh single-file new modules → use DUAL-AGENT (the live config); do not reach for this.** The durable fix (multi-file base+additive manifest mode) is an owner hand-edit to `orchestrator.py` (`_NEVER_AUTO_APPROVE`) — optional, lower priority than A.1/A.2.

---

## 7. WATCHER PATTERN (token-cheap; daemon does not notify)
`_autowork_scratch/wave1_watcher.sh` — a `run_in_background` loop that baselines line-count + HEAD, exits on (a) `Integrate validated code for <slug>` commit, (b) a new reject/`task_blocked`/`ast_validation_failed`/`verification_failed`/`retry_exhausted`/`dependency_failed` for the watched slugs, (c) `planner_hallucination_discarded`, or (d) a stall. Edit the `OURS=` regex to the current wave's slugs and re-launch per wave. Inspect structured telemetry in `state/impl_progress.jsonl` (parse JSON, filter by task_id) — NEVER tail `logs/autowork.log` (that's the streaming agent transcript, not the daemon log) into your context.

---

## 8. OWNER-GATED ITEMS — ALL AUTHORIZED except the two physical/outward-facing
1. ✅ Factory-internal gates (harness_self_fix decisions, `_NEVER_AUTO_APPROVE` hand-edits via pipeline+decision, approvals) — AUTHORIZED. Maintain pipeline workflow (RED oracle + decision file; don't hand-edit production directly).
2. ⏳ **rclone OAuth** — physical owner browser login (`rclone config reconnect gdrive:`). Surface; drive build doesn't block on it.
3. ⏳ **External bounty submission** — per-target owner GO (§B.5); not blind-batch.
4. codex default model is codex's authenticated default (observed `gpt-5.5`); pin `-m` per role only if the owner wants. codex stays SELECTABLE (not in default pair) until A.3 is fixed.

---

## 9. HARD DON'Ts (learned, several the hard way)
- DON'T leave the factory in gemini-solo for general work — dual-agent is the posture (§0).
- DON'T reactively patch one surfaced gate at a time — coherent design pass per leaf (this is why config-schema thrashed).
- DON'T conflate BUILT (green oracle) with WORKS (live verified). Run the broader suite + live verify.
- DON'T trust `state/control/autowork/pause` (no-op) — use `orchestrator.flag`.
- DON'T allowlist a leaf whose deps aren't accepted (dep-gate leak dispatches it early) — one wave at a time, and fix A.1 first to make this safe.
- DON'T run NGv2/agy/hunter agents with cwd in the JM main tree (uncontained tamper risk) — they live in NGv2; verify JM tree after.
- DON'T read full sub-agent transcripts / large files into the orchestrator context.
- DON'T auto-submit bounties to external programs without a per-target owner GO.

---

## 10. POINTERS
- **Memory (auto-loaded index `MEMORY.md`):** [[webui-foundation-corrected-plan]] (this epic + the gemini-solo recipe + manual-drive + dep-gate-leak details), [[factory-new-module-wireup-gates]], [[ngv2-financial-viability-parallel-hunt]] (bounty hunt), [[concurrency-isolation-and-ngv2-solver-ast-epic]], [[daemon-supervisor-respawn]], [[issue-fix-via-pipeline-then-rerun]], [[stale-sidecar-precedence-gotcha]], [[dont-conflate-built-with-works]], [[never-hand-edit-production-outside-pipeline]].
- **Scratch (this session):** `_autowork_scratch/PHV_*.md` (Phase-0 audits), `config_gemini_solo.yaml` (override — webui-only), `*-DONE-*/` + `*-failed-attempt-*/` (build artifacts), `wave1_watcher.sh`.
- **Prior handoff (executed this session):** `HANDOFF_webui_config_schema_rootcause_and_continuation.md`.
- **Bounty:** NGv2 `HANDOFF_ngv2_bounty_hunt_continuation.md`.
- **Drive:** `_autowork_scratch/DRIVE_EPIC_PREP.md`, `DRIVE_BACKUP_USER_SETUP.md`.

---

## 11. FIRST MOVES (suggested, parallel)
1. Verify state: HEAD `ece3e4c` on origin/master, daemon paused, `active_agents:[claude,gemini]`, `pgrep -af agy` (no JM-tree orphans), JM tree clean.
2. **In one turn, parallel:** (a) launch 3 NGv2 hunter agents (background, §B); (b) spawn a sub-agent to read the NGv2 bounty handoff + report ranked leads; (c) spawn a sub-agent to author the RED oracle + harness_self_fix leaf brief for the dep-gate-leak fix (A.1).
3. Drive the A.1 fix through the pipeline (decision authorized) → then A.2 → then allowlist drive Wave A and let the daemon build it dual-agent (watch §7).
4. Collect hunter PoCs; surface confirmed ones for per-target submission GO.
5. Commit/push as waves land (owner authorized push). End each batch with a compact status.
